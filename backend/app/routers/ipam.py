import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import DireccionIP, Dispositivo, Subred, Usuario
from ..schemas import IPReservationCreate, SubnetCreate
from .auth import get_current_user, require_roles

router = APIRouter(prefix="/api/v1/ipam", tags=["Módulo IPAM"])
editor_required = require_roles("Admin", "Técnico")


def host_range(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> tuple[int, int]:
    first = int(network.network_address)
    count = network.num_addresses
    if network.version == 4 and network.prefixlen <= 30:
        return first + 1, count - 2
    if network.version == 6 and network.prefixlen <= 126:
        return first + 1, count - 1
    return first, count


def host_count(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> int:
    return host_range(network)[1]


async def get_subnet(db: AsyncSession, subnet_id: int) -> Subred:
    subnet = await db.get(Subred, subnet_id)
    if subnet is None:
        raise HTTPException(status_code=404, detail="Subred no encontrada")
    return subnet


@router.get("/subnets")
async def list_subnets(
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subred).order_by(Subred.etiqueta_vlan))
    return [
        {
            "id_vlan": subnet.id_vlan,
            "etiqueta_vlan": subnet.etiqueta_vlan,
            "cidr": subnet.cidr,
            "nombre_segmento": subnet.nombre_segmento,
            "descripcion": subnet.descripcion,
            "total_ips": host_count(ipaddress.ip_network(subnet.cidr)),
        }
        for subnet in result.scalars()
    ]


@router.post("/subnets", status_code=status.HTTP_201_CREATED)
async def create_subnet(
    body: SubnetCreate,
    _: Annotated[Usuario, Depends(editor_required)],
    db: AsyncSession = Depends(get_db),
):
    network = ipaddress.ip_network(body.cidr)
    result = await db.execute(select(Subred))
    for existing in result.scalars():
        existing_network = ipaddress.ip_network(existing.cidr)
        if network.version == existing_network.version and network.overlaps(existing_network):
            raise HTTPException(
                status_code=409,
                detail=f"El rango se traslapa con la subred {existing.cidr}",
            )

    subnet = Subred(**body.model_dump())
    db.add(subnet)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="La VLAN o el segmento CIDR ya están registrados",
        ) from exc
    await db.refresh(subnet)
    return {
        "id_vlan": subnet.id_vlan,
        "etiqueta_vlan": subnet.etiqueta_vlan,
        "cidr": subnet.cidr,
        "nombre_segmento": subnet.nombre_segmento,
        "descripcion": subnet.descripcion,
        "total_ips": host_count(network),
    }


@router.get("/subnets/{subnet_id}/addresses")
async def list_subnet_addresses(
    subnet_id: int,
    _: Annotated[Usuario, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=64, ge=1, le=256),
):
    subnet = await get_subnet(db, subnet_id)
    network = ipaddress.ip_network(subnet.cidr)
    first, total = host_range(network)
    addresses = [
        str(ipaddress.ip_address(first + index))
        for index in range(offset, min(offset + limit, total))
    ]
    reservations: dict[str, DireccionIP] = {}
    devices: dict[str, Dispositivo] = {}
    if addresses:
        reservation_result = await db.execute(
            select(DireccionIP).where(DireccionIP.direccion.in_(addresses))
        )
        reservations = {item.direccion: item for item in reservation_result.scalars()}
        device_result = await db.execute(
            select(Dispositivo).where(Dispositivo.ip_gestion.in_(addresses))
        )
        devices = {item.ip_gestion: item for item in device_result.scalars()}

    entries = []
    for address in addresses:
        device = devices.get(address)
        reservation = reservations.get(address)
        if device is not None:
            state, purpose = "ocupada", device.nombre_host
        elif reservation is not None and reservation.estado_asignacion == "reservada":
            state, purpose = "reservada", reservation.proposito
        else:
            state, purpose = "libre", None
        entries.append(
            {
                "id_ip": reservation.id_ip if reservation is not None else None,
                "direccion": address,
                "estado": state,
                "proposito": purpose,
            }
        )

    return {"subred_id": subnet_id, "total": total, "offset": offset, "limit": limit, "ips": entries}


@router.post("/subnets/{subnet_id}/reservations", status_code=status.HTTP_201_CREATED)
async def reserve_address(
    subnet_id: int,
    body: IPReservationCreate,
    _: Annotated[Usuario, Depends(editor_required)],
    db: AsyncSession = Depends(get_db),
):
    subnet = await get_subnet(db, subnet_id)
    network = ipaddress.ip_network(subnet.cidr)
    address = ipaddress.ip_address(body.direccion)
    first, total = host_range(network)
    index = int(address) - first
    if address.version != network.version or index < 0 or index >= total:
        raise HTTPException(status_code=422, detail="La IP no es una dirección utilizable de esta subred")

    device = await db.scalar(
        select(Dispositivo.id_dispositivo).where(Dispositivo.ip_gestion == body.direccion)
    )
    if device is not None:
        raise HTTPException(status_code=409, detail="La IP ya está asignada a un activo")

    existing = await db.scalar(
        select(DireccionIP).where(DireccionIP.direccion == body.direccion)
    )
    if existing is not None and existing.estado_asignacion == "reservada":
        raise HTTPException(status_code=409, detail="La IP ya está reservada")
    if existing is not None and existing.id_subred != subnet_id:
        raise HTTPException(status_code=409, detail="La IP ya está registrada en otra subred")

    if existing is None:
        existing = DireccionIP(
            id_subred=subnet_id,
            direccion=body.direccion,
            estado_asignacion="reservada",
            proposito=body.proposito,
        )
        db.add(existing)
    else:
        existing.estado_asignacion = "reservada"
        existing.proposito = body.proposito
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="La IP ya está registrada") from exc
    await db.refresh(existing)
    return {
        "id_ip": existing.id_ip,
        "direccion": existing.direccion,
        "estado": existing.estado_asignacion,
        "proposito": existing.proposito,
    }


@router.delete("/reservations/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def release_address(
    address_id: int,
    _: Annotated[Usuario, Depends(editor_required)],
    db: AsyncSession = Depends(get_db),
):
    reservation = await db.get(DireccionIP, address_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    await db.delete(reservation)
    await db.commit()
