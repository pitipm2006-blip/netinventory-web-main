"""Pruebas de la lógica de Sprint 7. Solo requieren la biblioteca estándar (+ reportlab para PDF).
Ejecutar desde la raíz:  python -m unittest discover -s tests -v
"""
import asyncio
import csv
import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.alerts import AlertThresholds, build_message, evaluate  # noqa: E402
from app.cache import TTLCache  # noqa: E402
from app.exports import sanitize_cell, to_csv, to_pdf  # noqa: E402
from app.security import LoginLimiter, is_diagnostic_target_allowed  # noqa: E402

TH = AlertThresholds(failures=3, latency_ms=200, latency_samples=3)
UP, DOWN = "disponible", "sin_respuesta"


class AlertRules(unittest.TestCase):
    def test_caida_tras_fallos_consecutivos(self):
        self.assertEqual(evaluate([(DOWN, 5)] * 3 + [(UP, 10)], TH), "caida")

    def test_dos_fallos_no_alertan(self):
        self.assertNotEqual(evaluate([(DOWN, 5), (DOWN, 5), (UP, 10)], TH), "caida")

    def test_latencia_alta_sostenida(self):
        self.assertEqual(evaluate([(UP, 350), (UP, 400), (UP, 250)], TH), "latencia_alta")

    def test_un_pico_aislado_no_alerta(self):
        self.assertEqual(evaluate([(UP, 900), (UP, 20), (UP, 20)], TH), "ok")

    def test_recuperacion(self):
        self.assertEqual(evaluate([(UP, 12), (DOWN, 5), (DOWN, 5)], TH), "ok")

    def test_pocos_datos(self):
        self.assertEqual(evaluate([], TH), "indeterminado")

    def test_mensaje(self):
        self.assertIn("srv-01", build_message("caida", "srv-01", TH))


class Exports(unittest.TestCase):
    def test_csv_neutraliza_formulas(self):
        self.assertEqual(sanitize_cell("=CMD()"), "'=CMD()")
        self.assertEqual(sanitize_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(sanitize_cell(None), "")
        self.assertEqual(sanitize_cell("sw-core"), "sw-core")

    def test_csv_estructura(self):
        text = to_csv(["Host", "IP"], [["sw-1", "10.0.0.1"], ["=evil", None]])
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
        self.assertEqual(rows, [["Host", "IP"], ["sw-1", "10.0.0.1"], ["'=evil", ""]])

    def test_pdf_valido(self):
        pdf = to_pdf("Inventario", ["Host"], [["sw-1"]] * 200)
        self.assertTrue(pdf.startswith(b"%PDF"))


class CacheTests(unittest.TestCase):
    def test_hit_miss_y_expiracion(self):
        async def scenario():
            cache = TTLCache()
            self.assertIsNone(await cache.get_json("k"))
            await cache.set_json("k", {"a": 1}, ttl=60)
            self.assertEqual(await cache.get_json("k"), {"a": 1})
            await cache.set_json("old", [1], ttl=-1)
            self.assertIsNone(await cache.get_json("old"))
            await cache.invalidate("k")
            self.assertIsNone(await cache.get_json("k"))
            return cache
        cache = asyncio.run(scenario())
        self.assertEqual((cache.hits, cache.misses), (1, 3))


class SecurityTests(unittest.TestCase):
    def test_bloqueo_y_ventana(self):
        now = [0.0]
        limiter = LoginLimiter(max_failures=3, window_seconds=60, clock=lambda: now[0])
        for _ in range(3):
            limiter.register_failure("u")
        self.assertTrue(limiter.is_blocked("u"))
        now[0] = 61
        self.assertFalse(limiter.is_blocked("u"))

    def test_reset_tras_exito(self):
        limiter = LoginLimiter(max_failures=2)
        limiter.register_failure("u"); limiter.register_failure("u")
        limiter.reset("u")
        self.assertFalse(limiter.is_blocked("u"))

    def test_destinos_de_diagnostico(self):
        for bad in ("127.0.0.1", "169.254.169.254", "0.0.0.0", "224.0.0.1", "::1", "no-es-ip"):
            self.assertFalse(is_diagnostic_target_allowed(bad), bad)
        for good in ("10.0.0.5", "192.168.1.10", "172.16.0.2"):
            self.assertTrue(is_diagnostic_target_allowed(good), good)


if __name__ == "__main__":
    unittest.main()
