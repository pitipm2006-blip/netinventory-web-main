import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.encoders import jsonable_encoder

from ..cache import cache
from ..database import get_db
from ..security import is_diagnostic_target_allowed
from ..models import Dispositivo, ResultadoSondeo, Usuario
from ..monitoring import check_tcp_port, check_udp_port, ping_host, save_probe
from .auth import get_current_user, require_roles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Diagnóstico y monitoreo"])
tester_required = require_roles("Admin", "Técnico")


class PortScanRequest(BaseModel):
    protocolo: Literal["tcp", "udp"]
    puertos: list[int] = Field(min_length=1, max_length=100)

    @field_validator("puertos")
    @classmethod
    def validate_ports(cls, ports: list[int]) -> list[int]:
        if any(port < 1 or port > 65535 for port in ports):
            raise ValueError("Los puertos deben estar entre 1 y 65535")
        if len(set(ports)) != len(ports):
            raise ValueError("No se permiten puertos duplicados")
        return ports


def serialize_result(result: ResultadoSondeo, device: Dispositivo | None = None) -> dict:
    return {
        "id_resultado": result.id_resultado,
        "id_dispositivo": result.id_dispositivo,
        "nombre_host": device.nombre_host if device else None,
        "ip_gestion": device.ip_gestion if device else None,
        "origen": result.origen,
        "tipo": result.tipo,
        "estado": result.estado,
        "latencia_ms": result.latencia_ms,
        "detalle": result.detalle,
        "fecha_sondeo": result.fecha_sondeo,
    }


async def get_target(db: AsyncSession, device_id: int) -> Dispositivo:
    device = await db.get(Dispositivo, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    if not device.ip_gestion:
        raise HTTPException(status_code=422, detail="El dispositivo no tiene IP de gestión")
    if not is_diagnostic_target_allowed(device.ip_gestion):
        raise HTTPException(
            status_code=422,
            detail="La IP de gestión (loopback, link-local, multicast o reservada) no es un destino de diagnóstico permitido",
        )
    return device


async def run_scan(host: str, request: PortScanRequest) -> list[dict]:
    checker = check_tcp_port if request.protocolo == "tcp" else check_udp_port
    semaphore = asyncio.Semaphore(20)

    async def check(port: int) -> dict:
        async with semaphore:
            return await checker(host, port)

    return await asyncio.gather(*(check(port) for port in request.puertos))


@router.post("/devices/{device_id}/diagnostics/ping")
async def manual_ping(
    device_id: int,
    _: Annotated[Usuario, Depends(tester_required)],
    db: AsyncSession = Depends(get_db),
):
    device = await get_target(db, device_id)
    try:
        online, latency = await ping_host(device.ip_gestion)
    except OSError as exc:
        logger.exception("No se pudo iniciar ping para el dispositivo %s", device_id)
        raise HTTPException(
            status_code=503,
            detail="El ejecutor ICMP no está disponible en el servidor",
        ) from exc

    state = "disponible" if online else "sin_respuesta"
    await save_probe(device_id, "manual", "icmp", state, latency, {})
    return {
        "id_dispositivo": device_id,
        "nombre_host": device.nombre_host,
        "ip_gestion": device.ip_gestion,
        "tipo": "icmp",
        "estado": state,
        "latencia_ms": latency,
    }


@router.post("/devices/{device_id}/diagnostics/ports")
async def scan_ports(
    device_id: int,
    body: PortScanRequest,
    _: Annotated[Usuario, Depends(tester_required)],
    db: AsyncSession = Depends(get_db),
):
    device = await get_target(db, device_id)
    results = await run_scan(device.ip_gestion, body)
    state = "completado"
    await save_probe(
        device_id,
        "manual",
        f"{body.protocolo}_scan",
        state,
        max((result["latencia_ms"] for result in results), default=0),
        {"protocolo": body.protocolo, "resultados": results},
    )
    return {
        "id_dispositivo": device_id,
        "nombre_host": device.nombre_host,
        "ip_gestion": device.ip_gestion,
        "protocolo": body.protocolo,
        "resultados": results,
    }


@router.get("/monitoring/status")
async def monitoring_status(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    cached = await cache.get_json("monitoring:status")
    if cached is not None:
        return cached
    devices_result = await db.execute(
        select(Dispositivo).order_by(Dispositivo.nombre_host)
    )
    devices = devices_result.scalars().all()
    latest_ids = (
        select(func.max(ResultadoSondeo.id_resultado))
        .where(ResultadoSondeo.origen == "automatico", ResultadoSondeo.tipo == "icmp")
        .group_by(ResultadoSondeo.id_dispositivo)
    )
    result = await db.execute(
        select(ResultadoSondeo).where(ResultadoSondeo.id_resultado.in_(latest_ids))
    )
    latest = {probe.id_dispositivo: probe for probe in result.scalars()}
    payload = [
        {
            "id_dispositivo": device.id_dispositivo,
            "nombre_host": device.nombre_host,
            "ip_gestion": device.ip_gestion,
            "estado_operativo": device.estado_operativo,
            "ultimo_sondeo": (
                serialize_result(latest[device.id_dispositivo])
                if device.id_dispositivo in latest
                else None
            ),
        }
        for device in devices
    ]
    encoded = jsonable_encoder(payload)
    await cache.set_json("monitoring:status", encoded, ttl=10)
    return encoded


@router.get("/monitoring/results")
async def monitoring_results(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    result = await db.execute(
        select(ResultadoSondeo, Dispositivo)
        .join(Dispositivo, Dispositivo.id_dispositivo == ResultadoSondeo.id_dispositivo)
        .order_by(ResultadoSondeo.fecha_sondeo.desc(), ResultadoSondeo.id_resultado.desc())
        .limit(limit)
    )
    return [serialize_result(probe, device) for probe, device in result.all()]


@router.get("/devices/{device_id}/history")
async def get_device_monitoring_history(
    device_id: int,
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=200),
):
    """
    Obtiene el historial de latencia y disponibilidad de un activo específico
    para alimentar las gráficas de rendimiento del Sprint 6 (HU-11).
    """
    device = await get_target(db, device_id)

    query = (
        select(ResultadoSondeo)
        .where(ResultadoSondeo.id_dispositivo == device_id)
        .order_by(ResultadoSondeo.fecha_sondeo.desc())
        .limit(limit)
    )
    history_result = await db.execute(query)
    logs = history_result.scalars().all()

    # Invertir para orden cronológico ascendente en la gráfica
    logs.reverse()

    return {
        "id_dispositivo": device_id,
        "nombre_host": device.nombre_host,
        "history": [
            {
                "fecha_sondeo": log.fecha_sondeo.strftime("%Y-%m-%d %H:%M:%S") if log.fecha_sondeo else None,
                "latencia_ms": log.latencia_ms,
                "estado": log.estado,
                "tipo": log.tipo,
                "origen": log.origen,
            }
            for log in logs
        ],
    }