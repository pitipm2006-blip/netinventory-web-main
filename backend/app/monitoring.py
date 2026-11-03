import asyncio
import logging
import os
import platform
import socket
import time
from datetime import timedelta

from sqlalchemy import delete, func, select

from .alerts import build_message, evaluate, send_webhook, thresholds_from_env
from .database import AsyncSessionLocal
from .models import Alerta, Dispositivo, ResultadoSondeo

logger = logging.getLogger(__name__)
PROBE_INTERVAL_SECONDS = max(15, int(os.getenv("MONITORING_INTERVAL_SECONDS", "60")))
PROBE_TIMEOUT_SECONDS = 2
MAX_CONCURRENT_PROBES = 20
RETENTION_DAYS = max(1, int(os.getenv("PROBE_RETENTION_DAYS", "30")))
PURGE_EVERY_CYCLES = 60


async def ping_host(host: str) -> tuple[bool, int]:
    if platform.system() == "Windows":
        command = ["ping", "-n", "1", "-w", str(PROBE_TIMEOUT_SECONDS * 1000), host]
    else:
        command = ["ping", "-c", "1", "-W", str(PROBE_TIMEOUT_SECONDS), host]

    started = time.perf_counter()
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return_code = await asyncio.wait_for(
            process.wait(),
            timeout=PROBE_TIMEOUT_SECONDS + 1,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return False, round((time.perf_counter() - started) * 1000)
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    return return_code == 0, round((time.perf_counter() - started) * 1000)


async def check_tcp_port(host: str, port: int) -> dict:
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=1.5,
        )
        writer.close()
        await writer.wait_closed()
        state = "open"
    except ConnectionRefusedError:
        state = "closed"
    except (TimeoutError, OSError):
        state = "filtered"
    return {"port": port, "estado": state, "latencia_ms": round((time.perf_counter() - started) * 1000)}


async def check_udp_port(host: str, port: int) -> dict:
    started = time.perf_counter()
    address = socket.AF_INET6 if ":" in host else socket.AF_INET
    probe_socket = socket.socket(address, socket.SOCK_DGRAM)
    probe_socket.setblocking(False)
    loop = asyncio.get_running_loop()
    try:
        await loop.sock_connect(probe_socket, (host, port))
        await loop.sock_sendall(probe_socket, b"\x00")
        try:
            await asyncio.wait_for(loop.sock_recv(probe_socket, 1024), timeout=0.8)
            state = "open"
        except TimeoutError:
            state = "open|filtered"
        except ConnectionRefusedError:
            state = "closed"
    except ConnectionRefusedError:
        state = "closed"
    except OSError:
        state = "open|filtered"
    finally:
        probe_socket.close()
    return {"port": port, "estado": state, "latencia_ms": round((time.perf_counter() - started) * 1000)}


async def save_probe(
    id_dispositivo: int,
    origen: str,
    tipo: str,
    estado: str,
    latencia_ms: int | None,
    detalle: dict,
) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            ResultadoSondeo(
                id_dispositivo=id_dispositivo,
                origen=origen,
                tipo=tipo,
                estado=estado,
                latencia_ms=latencia_ms,
                detalle=detalle,
            )
        )
        await session.commit()


async def process_alerts(device_id: int, host_name: str) -> None:
    """Abre o resuelve alertas según los últimos sondeos automáticos del activo."""
    thresholds = thresholds_from_env()
    window = max(thresholds.failures, thresholds.latency_samples)
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(ResultadoSondeo.estado, ResultadoSondeo.latencia_ms)
            .where(
                ResultadoSondeo.id_dispositivo == device_id,
                ResultadoSondeo.origen == "automatico",
                ResultadoSondeo.tipo == "icmp",
            )
            .order_by(ResultadoSondeo.id_resultado.desc())
            .limit(window)
        )
        verdict = evaluate([(e, l) for e, l in rows.all()], thresholds)
        open_alert = await session.scalar(
            select(Alerta).where(Alerta.id_dispositivo == device_id, Alerta.estado == "abierta")
        )
        event = None
        if verdict in ("caida", "latencia_alta") and (open_alert is None or open_alert.tipo != verdict):
            if open_alert is not None:
                open_alert.estado, open_alert.fecha_resolucion = "resuelta", func.now()
            message = build_message(verdict, host_name, thresholds)
            session.add(Alerta(id_dispositivo=device_id, tipo=verdict, mensaje=message))
            event = {"evento": "alerta_abierta", "tipo": verdict, "mensaje": message}
        elif verdict == "ok" and open_alert is not None:
            open_alert.estado, open_alert.fecha_resolucion = "resuelta", func.now()
            event = {
                "evento": "alerta_resuelta",
                "tipo": open_alert.tipo,
                "mensaje": build_message("ok", host_name, thresholds),
            }
        await session.commit()
    if event:
        await send_webhook({**event, "id_dispositivo": device_id, "host": host_name})


async def purge_old_results() -> None:
    cutoff = func.now() - timedelta(days=RETENTION_DAYS)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ResultadoSondeo).where(ResultadoSondeo.fecha_sondeo < cutoff))
        await session.commit()


async def monitor_devices() -> None:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    async def probe(device_id: int, host: str, name: str) -> None:
        async with semaphore:
            try:
                online, latency = await ping_host(host)
                await save_probe(
                    device_id,
                    "automatico",
                    "icmp",
                    "disponible" if online else "sin_respuesta",
                    latency,
                    {},
                )
                await process_alerts(device_id, name)
            except Exception:
                logger.exception("No se pudo sondear el dispositivo %s (%s)", device_id, host)

    cycle = 0
    while True:
        cycle += 1
        try:
            if cycle % PURGE_EVERY_CYCLES == 1:
                await purge_old_results()
        except Exception:
            logger.exception("Falló la purga de resultados antiguos")
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(
                        Dispositivo.id_dispositivo, Dispositivo.ip_gestion, Dispositivo.nombre_host
                    ).where(
                        Dispositivo.ip_gestion.is_not(None),
                        Dispositivo.estado_operativo == "activo",
                    )
                )
                devices = result.all()
            await asyncio.gather(
                *(probe(device_id, host, name) for device_id, host, name in devices),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falló un ciclo del monitor de disponibilidad")
        await asyncio.sleep(PROBE_INTERVAL_SECONDS)
