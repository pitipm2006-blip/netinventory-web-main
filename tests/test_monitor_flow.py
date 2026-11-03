"""Prueba el flujo REAL de monitoring.process_alerts con SQLAlchemy/BD simuladas.

No requiere dependencias externas: se inyectan dobles de `sqlalchemy`, `app.database`
y `app.models` solo durante la importación y se retiran al terminar.
"""
import asyncio
import pathlib
import sys
import types
import unittest
from unittest import mock

BACKEND = str(pathlib.Path(__file__).resolve().parents[1] / "backend")
sys.path.insert(0, BACKEND)


class Chain:
    def __getattr__(self, _):
        return Chain()

    def __call__(self, *a, **k):
        return Chain()

    def __eq__(self, o):
        return Chain()

    __ne__ = __lt__ = __gt__ = __sub__ = __rsub__ = __eq__

    def __hash__(self):
        return 1


class Entity:
    id_dispositivo = estado = tipo = origen = id_resultado = latencia_ms = fecha_sondeo = Chain()
    nombre_host = ip_gestion = estado_operativo = Chain()

    def __init__(self, **kw):
        self.__dict__.update(kw)


class Alerta(Entity):
    pass


class FakeDB:
    """Estado compartido: sondeos recientes (más nuevo primero) y alertas persistidas."""
    def __init__(self):
        self.probes: list[tuple[str, int | None]] = []
        self.alerts: list[Alerta] = []

    def open_alert(self):
        return next((a for a in self.alerts if a.estado == "abierta"), None)


class FakeSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _q):
        return types.SimpleNamespace(all=lambda: list(self.db.probes))

    async def scalar(self, _q):
        return self.db.open_alert()

    def add(self, obj):
        obj.estado = obj.__dict__.get("estado", "abierta")
        self.db.alerts.append(obj)

    async def commit(self):
        pass


def load_monitoring(db):
    sa = types.ModuleType("sqlalchemy")
    sa.select = sa.delete = Chain()
    sa.func = Chain()
    database = types.ModuleType("app.database")
    database.AsyncSessionLocal = lambda: FakeSession(db)
    models = types.ModuleType("app.models")
    models.Alerta, models.Dispositivo, models.ResultadoSondeo = Alerta, Entity, Entity
    with mock.patch.dict(sys.modules, {"sqlalchemy": sa, "app.database": database, "app.models": models}):
        sys.modules.pop("app.monitoring", None)
        import app.monitoring as monitoring
        sys.modules.pop("app.monitoring", None)
    return monitoring


class ProcessAlertsFlow(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.mon = load_monitoring(self.db)
        self.sent = []

        async def fake_webhook(payload):
            self.sent.append(payload)
            return True

        self.mon.send_webhook = fake_webhook

    def step(self, estado, lat):
        self.db.probes.insert(0, (estado, lat))
        asyncio.run(self.mon.process_alerts(7, "sw-core-01"))

    def test_ciclo_completo_caida_y_recuperacion(self):
        self.step("sin_respuesta", None)
        self.step("sin_respuesta", None)
        self.assertEqual(self.db.alerts, [])          # 2 fallos: aún no alerta
        self.step("sin_respuesta", None)
        self.assertEqual(len(self.db.alerts), 1)
        self.assertEqual(self.db.alerts[0].tipo, "caida")
        self.assertEqual(self.sent[0]["evento"], "alerta_abierta")
        self.step("sin_respuesta", None)               # sigue caído: no duplica
        self.assertEqual(len(self.db.alerts), 1)
        self.assertEqual(len(self.sent), 1)
        self.step("disponible", 10)                    # recupera
        self.assertEqual(self.db.alerts[0].estado, "resuelta")
        self.assertEqual(self.sent[-1]["evento"], "alerta_resuelta")
        self.assertEqual(self.sent[-1]["id_dispositivo"], 7)

    def test_latencia_alta_y_transicion_a_caida(self):
        for _ in range(3):
            self.step("disponible", 400)
        self.assertEqual([a.tipo for a in self.db.alerts], ["latencia_alta"])
        for _ in range(3):
            self.step("sin_respuesta", None)
        self.assertEqual([a.tipo for a in self.db.alerts], ["latencia_alta", "caida"])
        self.assertEqual(self.db.alerts[0].estado, "resuelta")   # la anterior se cierra
        self.assertEqual(self.db.alerts[1].estado, "abierta")

    def test_sin_alertas_con_dispositivo_sano(self):
        for _ in range(10):
            self.step("disponible", 15)
        self.assertEqual((self.db.alerts, self.sent), ([], []))

    def test_pico_aislado_no_genera_alerta(self):
        self.step("disponible", 15)
        self.step("disponible", 900)
        self.step("disponible", 15)
        self.assertEqual(self.db.alerts, [])


if __name__ == "__main__":
    unittest.main()
