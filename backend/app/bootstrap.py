from sqlalchemy import select, text

from .database import AsyncSessionLocal, Base, engine
from .models import Rol, TipoDispositivo

INITIAL_ROLES = (
    (1, "Admin", "Administra usuarios, roles y todos los activos"),
    (2, "Técnico", "Consulta, registra y actualiza activos de red"),
    (3, "Auditor", "Consulta información sin modificarla"),
)

INITIAL_DEVICE_TYPES = (
    ("Servidor", "Genérico", "Servidor"),
    ("Switch", "Genérico", "Switch"),
    ("Router", "Genérico", "Router"),
    ("PC", "Genérico", "PC"),
    ("Impresora", "Genérico", "Impresora"),
)


async def initialize_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text("ALTER TABLE dispositivos ADD COLUMN IF NOT EXISTS mac_address VARCHAR(17)")
        )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_dispositivos_mac_address "
                "ON dispositivos (mac_address)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_sondeo_estado_actual "
                "ON resultados_sondeo (id_dispositivo, origen, tipo, id_resultado)"
            )
        )
        await connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_sondeo_fecha ON resultados_sondeo (fecha_sondeo)")
        )

    async with AsyncSessionLocal() as session:
        for role_id, name, description in INITIAL_ROLES:
            role = await session.get(Rol, role_id)
            if role is None:
                role = Rol(id_rol=role_id, nombre=name, descripcion=description)
                session.add(role)
            else:
                role.nombre = name
                role.descripcion = description

        for category, manufacturer, model in INITIAL_DEVICE_TYPES:
            result = await session.execute(
                select(TipoDispositivo).where(
                    TipoDispositivo.categoria == category,
                    TipoDispositivo.fabricante == manufacturer,
                    TipoDispositivo.modelo == model,
                )
            )
            if result.scalar_one_or_none() is None:
                session.add(
                    TipoDispositivo(
                        categoria=category,
                        fabricante=manufacturer,
                        modelo=model,
                    )
                )
        await session.commit()
