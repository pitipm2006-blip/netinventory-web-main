import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Usuario
from ..security import LoginLimiter

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación"])

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if len(SECRET_KEY.encode("utf-8")) < 32:
    raise RuntimeError("JWT_SECRET_KEY debe configurarse con al menos 32 bytes aleatorios")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)
login_limiter = LoginLimiter(max_failures=5, window_seconds=300)


class LoginRequest(BaseModel):
    correo: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    limiter_key = f"{request.client.host if request.client else '?'}|{credentials.correo.lower()}"
    if login_limiter.is_blocked(limiter_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Espera 5 minutos e inténtalo de nuevo",
        )
    result = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.rol))
        .where(Usuario.correo == credentials.correo.lower())
    )
    user = result.scalars().first()

    try:
        password_matches = bool(user and pwd_context.verify(credentials.password, user.hash_clave))
    except (UnknownHashError, ValueError):
        password_matches = False

    if not user or not user.activo or not password_matches:
        login_limiter.register_failure(limiter_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    login_limiter.reset(limiter_key)
    user.ultimo_acceso = datetime.now(timezone.utc)
    await db.commit()

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)
    access_token = jwt.encode(
        {
            "sub": str(user.id_usuario),
            "role": user.rol.nombre,
            "exp": expires_at,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"access_token": access_token, "token_type": "bearer"}


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        parsed_user_id = UUID(user_id) if user_id else None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin usuario válido",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not parsed_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin usuario asociado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(Usuario)
        .options(selectinload(Usuario.rol))
        .where(Usuario.id_usuario == parsed_user_id)
    )
    user = result.scalars().first()
    if not user or not user.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La cuenta no existe o está desactivada",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed_roles: str) -> Callable:
    async def role_dependency(
        current_user: Annotated[Usuario, Depends(get_current_user)],
    ) -> Usuario:
        if current_user.rol.nombre not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu rol no tiene permiso para realizar esta operación",
            )
        return current_user

    return role_dependency


@router.get("/me")
async def get_me(current_user: Annotated[Usuario, Depends(get_current_user)]):
    return {
        "id_usuario": str(current_user.id_usuario),
        "nombre_usuario": current_user.nombre_usuario,
        "correo": current_user.correo,
        "id_rol": current_user.id_rol,
        "rol": current_user.rol.nombre,
        "activo": current_user.activo,
    }
