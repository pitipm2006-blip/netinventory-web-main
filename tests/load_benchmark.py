"""Benchmark de la lógica de Sprint 7 con cientos de nodos (sin BD ni red).
Ejecutar:  python tests/load_benchmark.py"""
import asyncio, pathlib, random, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from app.alerts import AlertThresholds, evaluate
from app.cache import TTLCache
from app.exports import to_csv, to_pdf

random.seed(7)
TH = AlertThresholds()
def timeit(fn):
    t = time.perf_counter(); out = fn(); return out, (time.perf_counter() - t) * 1000

for nodes in (300, 1000):
    hist = [[(random.choice(["disponible"] * 9 + ["sin_respuesta"]), random.randint(1, 400)) for _ in range(3)] for _ in range(nodes)]
    _, ms = timeit(lambda: [evaluate(h, TH) for h in hist])
    print(f"{nodes:>5} nodos: evaluar alertas de un ciclo   {ms:7.2f} ms")
    rows = [[f"sw-{i}", f"10.0.{i//250}.{i%250+1}", "activo"] for i in range(nodes)]
    _, ms = timeit(lambda: to_csv(["Host", "IP", "Estado"], rows)); print(f"{nodes:>5} nodos: CSV                              {ms:7.2f} ms")
    _, ms = timeit(lambda: to_pdf("x", ["Host", "IP", "Estado"], rows)); print(f"{nodes:>5} nodos: PDF                              {ms:7.2f} ms")

payload = [{"id_dispositivo": i, "nombre_host": f"sw-{i}", "ultimo_sondeo": {"estado": "disponible", "latencia_ms": 12}} for i in range(1000)]
async def cache_run():
    c = TTLCache(); await c.set_json("monitoring:status", payload, 10)
    t = time.perf_counter()
    for _ in range(1000): assert await c.get_json("monitoring:status") is not None
    return (time.perf_counter() - t) * 1000 / 1000
print(f" 1000 nodos: lectura de caché (memoria), media   {asyncio.run(cache_run()):7.3f} ms/consulta")
