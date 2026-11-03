"""Auditoría estática (solo `ast` y yaml): rutas, permisos, imports internos,
contrato frontend↔backend, modelos vs init.sql y variables de entorno de Compose."""
import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
PUBLIC = {("POST", "/api/v1/auth/login"), ("GET", "/health"), ("GET", "/")}


def literal(node):
    return node.value if isinstance(node, ast.Constant) else None


def collect_routes():
    """(método, ruta, fuente de parámetros de dependencia, archivo)"""
    routes = []
    files = [APP / "main.py"] + sorted((APP / "routers").glob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if getattr(node.value.func, "id", "") == "APIRouter":
                    for kw in node.value.keywords:
                        if kw.arg == "prefix":
                            prefix = literal(kw.value) or ""
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                    if dec.func.attr in {"get", "post", "patch", "delete", "put"}:
                        sub = literal(dec.args[0]) or ""
                        base = "" if path.name == "main.py" else prefix
                        routes.append((dec.func.attr.upper(), base + sub, ast.unparse(node.args), path.name))
    return routes


class RoutesAudit(unittest.TestCase):
    def setUp(self):
        self.routes = collect_routes()

    def test_hay_rutas_de_sprint7(self):
        paths = {(m, p) for m, p, *_ in self.routes}
        for expected in [
            ("GET", "/api/v1/alerts"), ("GET", "/api/v1/reports/devices"),
            ("GET", "/api/v1/reports/ipam"), ("GET", "/api/v1/reports/alerts"),
            ("GET", "/api/v1/monitoring/status"),
        ]:
            self.assertIn(expected, paths)

    def test_sin_rutas_duplicadas(self):
        keys = [(m, p) for m, p, *_ in self.routes]
        self.assertEqual(len(keys), len(set(keys)), "Hay rutas repetidas")

    def test_toda_ruta_privada_exige_autenticacion(self):
        for method, path, params, fname in self.routes:
            if (method, path) in PUBLIC:
                continue
            self.assertTrue(
                any(k in params for k in ("get_current_user", "_required", "tester_required", "admin_required", "editor_required")),
                f"{method} {path} ({fname}) no declara autenticación/rol",
            )

    def test_escrituras_requieren_rol_editor(self):
        for method, path, params, fname in self.routes:
            if method in {"POST", "PATCH", "DELETE"} and (method, path) not in PUBLIC:
                self.assertRegex(params, r"(editor|admin|tester)_required", f"{method} {path}")

    def test_todos_los_routers_estan_registrados(self):
        main = (APP / "main.py").read_text(encoding="utf-8")
        for f in (APP / "routers").glob("*.py"):
            if f.stem != "__init__":
                self.assertIn(f"routers.{f.stem} import", main, f"{f.stem} no se importa en main.py")
                self.assertIn(f"app.include_router({f.stem}_router)", main)


class ImportsAudit(unittest.TestCase):
    def test_imports_internos_resuelven(self):
        """Cada `from ..x import nombre` debe existir realmente en el módulo destino."""
        for path in APP.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level:
                    base = path.parent if node.level == 1 else path.parent.parent
                    target = base / (node.module.replace(".", "/") if node.module else "")
                    mod = target.with_suffix(".py") if target.with_suffix(".py").exists() else target / "__init__.py"
                    if not mod.exists():
                        self.fail(f"{path.name}: módulo no encontrado {node.module}")
                    defined = set()
                    for n in ast.parse(mod.read_text(encoding="utf-8")).body:
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            defined.add(n.name)
                        elif isinstance(n, ast.Assign):
                            defined |= {t.id for t in n.targets if isinstance(t, ast.Name)}
                        elif isinstance(n, (ast.Import, ast.ImportFrom)):
                            defined |= {(a.asname or a.name).split(".")[0] for a in n.names}
                    for alias in node.names:
                        self.assertIn(alias.name, defined, f"{path.name}: '{alias.name}' no existe en {node.module}")

    def test_requirements_cubren_imports_de_terceros(self):
        reqs = (ROOT / "backend" / "requirements.txt").read_text().lower()
        for lib in ("redis", "reportlab", "fastapi", "sqlalchemy", "asyncpg"):
            self.assertIn(lib, reqs)


class ContractAudit(unittest.TestCase):
    def test_el_frontend_solo_llama_rutas_que_existen(self):
        """Compara segmento a segmento; {param} del backend y ${expr} del frontend son comodines."""
        route_paths = [p.strip("/").split("/") for _, p, *_ in collect_routes()]

        def wild(seg):
            return seg.startswith("{") or seg.startswith("${") or seg == "\0"

        def matches(url, route):
            return len(url) == len(route) and all(
                a == b or wild(a) or wild(b) for a, b in zip(url, route)
            )

        used = set()
        for f in (ROOT / "frontend" / "src").rglob("*.jsx"):
            for m in re.finditer(r"/api/v1/[A-Za-z0-9_\-/${}.]*", f.read_text(encoding="utf-8")):
                used.add(m.group(0).rstrip("/"))
        self.assertGreater(len(used), 10)
        for url in sorted(used):
            segs = re.sub(r"\$\{[^}]+\}", "\0", url).strip("/").split("/")
            self.assertTrue(
                any(matches(segs, r) for r in route_paths),
                f"El frontend llama {url} y no existe en el backend",
            )

    def test_topologia_usa_la_clave_de_token_correcta(self):
        src = (ROOT / "frontend/src/TopologyMap.jsx").read_text(encoding="utf-8")
        self.assertIn("netinventory_token", src)
        self.assertNotIn("getItem('token')", src)
        self.assertNotIn("http://localhost:8000", src.replace("|| 'http://localhost:8000'", ""))

    def test_login_sin_credenciales_precargadas(self):
        src = (ROOT / "frontend/src/pages/Login.jsx").read_text(encoding="utf-8")
        self.assertNotIn("admin123", src)

    def test_dashboard_registra_el_panel_de_alertas(self):
        src = (ROOT / "frontend/src/pages/Dashboard.jsx").read_text(encoding="utf-8")
        self.assertIn("AlertsReportsPanel", src)
        self.assertTrue((ROOT / "frontend/src/components/AlertsReportsPanel.jsx").exists())


class SchemaAndConfig(unittest.TestCase):
    def test_columnas_de_init_sql_existen_en_modelos(self):
        sql = (ROOT / "database/init.sql").read_text(encoding="utf-8")
        models = (APP / "models.py").read_text(encoding="utf-8")
        for table in ("usuarios", "dispositivos", "subredes", "direcciones_ip", "roles"):
            block = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.S).group(1)
            cols = [l.split()[0] for l in block.splitlines() if l.strip() and not l.strip().startswith(("CONSTRAINT", "PRIMARY", "UNIQUE"))]
            for col in cols:
                self.assertIn(col + " =", models.replace("  ", " ").replace(f"{col}  =", f"{col} ="), f"{table}.{col} falta en models.py")

    def test_compose_es_yaml_valido_y_expone_config_sprint7(self):
        import yaml
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        env = compose["services"]["backend"]["environment"]
        for key in ("REDIS_URL", "ALERT_WEBHOOK_URL", "ALERT_FAILURES", "ALERT_LATENCY_MS", "PROBE_RETENTION_DAYS"):
            self.assertIn(key, env)
        for svc in ("postgres", "redis"):
            for port in compose["services"][svc]["ports"]:
                self.assertTrue(port.startswith("127.0.0.1:"), f"{svc} expone {port} a toda la red")

    def test_variables_leidas_por_el_codigo_estan_en_compose_o_tienen_default(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for f in APP.rglob("*.py"):
            for m in re.finditer(r'os\.getenv\(\s*"([A-Z_]+)"', f.read_text(encoding="utf-8")):
                var = m.group(1)
                if var in {"DATABASE_URL", "CORS_ORIGINS", "JWT_ALGORITHM"}:
                    continue
                self.assertIn(var, compose, f"{var} (usada en {f.name}) no está en docker-compose.yml")

    def test_env_ejemplo_no_contiene_secretos_reales(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("netpassword123", text)


if __name__ == "__main__":
    unittest.main()
