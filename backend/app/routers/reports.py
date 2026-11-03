from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..exports import to_csv, to_pdf
from ..models import Alerta, DireccionIP, Dispositivo, Subred, Usuario
from .auth import get_current_user

router = APIRouter(prefix="/api/v1/reports", tags=["Reportes"])

DEVICE_HEADERS = ["Host", "FQDN", "Categoría", "Fabricante", "Modelo", "IP gestión", "MAC", "Serie", "Rack", "RU", "Estado"]
IPAM_HEADERS = ["VLAN", "Segmento", "CIDR", "Dirección", "Estado", "Propósito"]
ALERT_HEADERS = ["ID", "Host", "Tipo", "Mensaje", "Estado", "Apertura", "Resolución"]


def deliver(name: str, fmt: str, title: str, headers: list[str], rows: list[list]) -> Response:
    if fmt == "pdf":
        content, media = to_pdf(title, headers, rows), "application/pdf"
    else:
        content, media = to_csv(headers, rows).encode("utf-8"), "text/csv; charset=utf-8"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'},
    )


@router.get("/devices")
async def report_devices(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    formato: Literal["csv", "pdf"] = "csv",
):
    result = await db.execute(
        select(Dispositivo).options(selectinload(Dispositivo.tipo)).order_by(Dispositivo.nombre_host)
    )
    rows = [
        [d.nombre_host, d.fqdn, d.tipo.categoria, d.tipo.fabricante, d.tipo.modelo, d.ip_gestion,
         d.mac_address, d.numero_serie, d.id_rack, d.ru_inicio, d.estado_operativo]
        for d in result.scalars()
    ]
    return deliver("inventario_activos", formato, "Inventario de activos de red", DEVICE_HEADERS, rows)


@router.get("/ipam")
async def report_ipam(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    formato: Literal["csv", "pdf"] = "csv",
):
    result = await db.execute(
        select(Subred, DireccionIP)
        .outerjoin(DireccionIP, DireccionIP.id_subred == Subred.id_vlan)
        .order_by(Subred.etiqueta_vlan, DireccionIP.direccion)
    )
    rows = [
        [s.etiqueta_vlan, s.nombre_segmento, s.cidr,
         ip.direccion if ip else None, ip.estado_asignacion if ip else None, ip.proposito if ip else None]
        for s, ip in result.all()
    ]
    return deliver("estado_ipam", formato, "Estado de IPAM (subredes y reservas)", IPAM_HEADERS, rows)


@router.get("/alerts")
async def report_alerts(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    formato: Literal["csv", "pdf"] = "csv",
):
    result = await db.execute(
        select(Alerta, Dispositivo.nombre_host)
        .join(Dispositivo, Dispositivo.id_dispositivo == Alerta.id_dispositivo)
        .order_by(Alerta.id_alerta.desc())
        .limit(5000)
    )
    rows = [
        [a.id_alerta, host, a.tipo, a.mensaje, a.estado, a.fecha_apertura, a.fecha_resolucion]
        for a, host in result.all()
    ]
    return deliver("historial_alertas", formato, "Historial de alertas", ALERT_HEADERS, rows)
