from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import BastidorRack, DireccionIP, Dispositivo, TipoDispositivo, Usuario
from ..schemas import DeviceCreate, DeviceResponse, DeviceTypeResponse, DeviceUpdate
from .auth import get_current_user, require_roles

router = APIRouter(prefix="/api/v1", tags=["Activos de red"])
editor_required = require_roles("Admin", "Técnico")
admin_required = require_roles("Admin")


def serialize_device(device: Dispositivo) -> DeviceResponse:
    return DeviceResponse(
        id_dispositivo=device.id_dispositivo,
        id_tipo=device.id_tipo,
        categoria=device.tipo.categoria,
        fabricante=device.tipo.fabricante,
        modelo=device.tipo.modelo,
        id_rack=device.id_rack,
        nombre_host=device.nombre_host,
        fqdn=device.fqdn,
        numero_serie=device.numero_serie,
        ip_gestion=device.ip_gestion,
        mac_address=device.mac_address,
        ru_inicio=device.ru_inicio,
        estado_operativo=device.estado_operativo,
    )


async def ensure_references(
    db: AsyncSession,
    id_tipo: int | None,
    id_rack: int | None,
) -> None:
    if id_tipo is not None and await db.get(TipoDispositivo, id_tipo) is None:
        raise HTTPException(status_code=422, detail="El tipo de dispositivo no existe")
    if id_rack is not None and await db.get(BastidorRack, id_rack) is None:
        raise HTTPException(status_code=422, detail="El rack seleccionado no existe")


@router.get("/device-types", response_model=list[DeviceTypeResponse])
async def list_device_types(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TipoDispositivo).order_by(TipoDispositivo.categoria, TipoDispositivo.fabricante)
    )
    return result.scalars().all()


@router.get("/racks")
async def list_racks(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BastidorRack).order_by(BastidorRack.identificador)
    )
    return [
        {"id_rack": rack.id_rack, "identificador": rack.identificador}
        for rack in result.scalars()
    ]


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(default=None, max_length=120),
):
    query = select(Dispositivo).options(selectinload(Dispositivo.tipo)).order_by(Dispositivo.nombre_host)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            Dispositivo.nombre_host.ilike(term)
            | Dispositivo.ip_gestion.ilike(term)
            | Dispositivo.numero_serie.ilike(term)
        )
    result = await db.execute(query)
    return [serialize_device(device) for device in result.scalars()]


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate,
    _: Annotated[Usuario, Depends(editor_required)],
    db: AsyncSession = Depends(get_db),
):
    await ensure_references(db, body.id_tipo, body.id_rack)
    if body.ip_gestion:
        reserved = await db.scalar(
            select(DireccionIP.id_ip).where(
                DireccionIP.direccion == body.ip_gestion,
                DireccionIP.estado_asignacion == "reservada",
            )
        )
        if reserved is not None:
            raise HTTPException(status_code=409, detail="La IP ya está reservada en IPAM")
    device = Dispositivo(**body.model_dump())
    db.add(device)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="El nombre de host, FQDN, número de serie, IP o MAC ya está registrado",
        ) from exc

    result = await db.execute(
        select(Dispositivo)
        .options(selectinload(Dispositivo.tipo))
        .where(Dispositivo.id_dispositivo == device.id_dispositivo)
    )
    return serialize_device(result.scalar_one())


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: int,
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dispositivo)
        .options(selectinload(Dispositivo.tipo))
        .where(Dispositivo.id_dispositivo == device_id)
    )
    device = result.scalars().first()
    if device is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    return serialize_device(device)


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: int,
    body: DeviceUpdate,
    _: Annotated[Usuario, Depends(editor_required)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Dispositivo)
        .options(selectinload(Dispositivo.tipo))
        .where(Dispositivo.id_dispositivo == device_id)
    )
    device = result.scalars().first()
    if device is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

    changes = body.model_dump(exclude_unset=True)
    for required in ("id_tipo", "nombre_host", "estado_operativo"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"El campo {required} no puede ser nulo")
    await ensure_references(
        db,
        changes.get("id_tipo", device.id_tipo),
        changes.get("id_rack", device.id_rack),
    )
    ip_gestion = changes.get("ip_gestion", device.ip_gestion)
    if ip_gestion:
        reserved = await db.scalar(
            select(DireccionIP.id_ip).where(
                DireccionIP.direccion == ip_gestion,
                DireccionIP.estado_asignacion == "reservada",
            )
        )
        if reserved is not None:
            raise HTTPException(status_code=409, detail="La IP ya está reservada en IPAM")
    for field, value in changes.items():
        setattr(device, field, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="El nombre de host, FQDN, número de serie, IP o MAC ya está registrado",
        ) from exc

    result = await db.execute(
        select(Dispositivo)
        .options(selectinload(Dispositivo.tipo))
        .where(Dispositivo.id_dispositivo == device_id)
    )
    return serialize_device(result.scalar_one())


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    _: Annotated[Usuario, Depends(admin_required)],
    db: AsyncSession = Depends(get_db),
):
    device = await db.get(Dispositivo, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    await db.delete(device)
    await db.commit()
