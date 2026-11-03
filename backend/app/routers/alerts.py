from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Alerta, Dispositivo, Usuario
from .auth import get_current_user

router = APIRouter(prefix="/api/v1", tags=["Alertas"])


@router.get("/alerts")
async def list_alerts(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    estado: Literal["abierta", "resuelta"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    query = (
        select(Alerta, Dispositivo.nombre_host)
        .join(Dispositivo, Dispositivo.id_dispositivo == Alerta.id_dispositivo)
        .order_by(Alerta.id_alerta.desc())
        .limit(limit)
    )
    if estado:
        query = query.where(Alerta.estado == estado)
    result = await db.execute(query)
    return [
        {
            "id_alerta": alert.id_alerta,
            "id_dispositivo": alert.id_dispositivo,
            "nombre_host": host,
            "tipo": alert.tipo,
            "mensaje": alert.mensaje,
            "estado": alert.estado,
            "fecha_apertura": alert.fecha_apertura,
            "fecha_resolucion": alert.fecha_resolucion,
        }
        for alert, host in result.all()
    ]
