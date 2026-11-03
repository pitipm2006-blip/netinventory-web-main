from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Rol, Usuario
from ..schemas import UserCreate, UserResponse, UserUpdate
from .auth import require_roles

router = APIRouter(prefix="/api/v1", tags=["Usuarios y roles"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
admin_required = require_roles("Admin")


def serialize_user(user: Usuario) -> UserResponse:
    return UserResponse(
        id_usuario=str(user.id_usuario),
        nombre_usuario=user.nombre_usuario,
        correo=user.correo,
        id_rol=user.id_rol,
        rol=user.rol.nombre,
        activo=user.activo,
        ultimo_acceso=user.ultimo_acceso.isoformat() if user.ultimo_acceso else None,
    )


@router.get("/roles")
async def list_roles(
    _: Annotated[Usuario, Depends(admin_required)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Rol).order_by(Rol.id_rol))
    return [
        {"id_rol": role.id_rol, "nombre": role.nombre, "descripcion": role.descripcion}
        for role in result.scalars()
    ]


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _: Annotated[Usuario, Depends(admin_required)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Usuario).options(selectinload(Usuario.rol)).order_by(Usuario.nombre_usuario))
    return [serialize_user(user) for user in result.scalars()]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    _: Annotated[Usuario, Depends(admin_required)],
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Usuario.id_usuario).where(Usuario.correo == body.correo.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo")

    role = await db.get(Rol, body.id_rol)
    if role is None:
        raise HTTPException(status_code=422, detail="El rol seleccionado no existe")

    user = Usuario(
        id_usuario=uuid4(),
        id_rol=role.id_rol,
        nombre_usuario=body.nombre_usuario.strip(),
        correo=body.correo.lower(),
        hash_clave=pwd_context.hash(body.password),
        activo=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await db.refresh(user, attribute_names=["rol"])
    return serialize_user(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    _: Annotated[Usuario, Depends(admin_required)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.rol))
        .where(Usuario.id_usuario == user_id)
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    changes = body.model_dump(exclude_unset=True)
    was_admin = user.rol.nombre == "Admin"
    target_role = user.rol
    if "correo" in changes and changes["correo"] is not None:
        email = changes["correo"].lower()
        duplicate = await db.execute(
            select(Usuario.id_usuario).where(
                Usuario.correo == email,
                Usuario.id_usuario != user_id,
            )
        )
        if duplicate.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo")
        user.correo = email

    if "id_rol" in changes and changes["id_rol"] is not None:
        target_role = await db.get(Rol, changes["id_rol"])
        if target_role is None:
            raise HTTPException(status_code=422, detail="El rol seleccionado no existe")

    will_be_admin = target_role.nombre == "Admin"
    remains_active = changes.get("activo", user.activo)
    loses_admin_access = was_admin and (not will_be_admin or not remains_active)
    if loses_admin_access:
        active_admin_count = await db.scalar(
            select(func.count(Usuario.id_usuario))
            .join(Rol, Usuario.id_rol == Rol.id_rol)
            .where(Rol.nombre == "Admin", Usuario.activo.is_(True))
        )
        if (active_admin_count or 0) <= 1:
            raise HTTPException(
                status_code=409,
                detail="No se puede desactivar o quitar el rol al último administrador activo",
            )

    if "id_rol" in changes and changes["id_rol"] is not None:
        user.id_rol = target_role.id_rol
        user.rol = target_role
    if "nombre_usuario" in changes and changes["nombre_usuario"] is not None:
        user.nombre_usuario = changes["nombre_usuario"].strip()
    if "password" in changes and changes["password"] is not None:
        user.hash_clave = pwd_context.hash(changes["password"])
    if "activo" in changes and changes["activo"] is not None:
        user.activo = changes["activo"]

    await db.commit()
    await db.refresh(user)
    await db.refresh(user, attribute_names=["rol"])
    return serialize_user(user)
