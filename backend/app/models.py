from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .database import Base


class Rol(Base):
    __tablename__ = "roles"

    id_rol = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False, unique=True)
    descripcion = Column(String)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    usuarios = relationship("Usuario", back_populates="rol")


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(UUID(as_uuid=True), primary_key=True)
    id_rol = Column(Integer, ForeignKey("roles.id_rol", ondelete="RESTRICT"), nullable=False)
    nombre_usuario = Column(String(100), nullable=False)
    correo = Column(String(150), nullable=False, unique=True, index=True)
    hash_clave = Column(String(255), nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    ultimo_acceso = Column(DateTime(timezone=True))
    rol = relationship("Rol", back_populates="usuarios")


class TipoDispositivo(Base):
    __tablename__ = "tipos_dispositivo"
    __table_args__ = (
        UniqueConstraint("categoria", "fabricante", "modelo", name="uq_tipo_dispositivo_catalogo"),
    )

    id_tipo = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(40), nullable=False)
    fabricante = Column(String(100), nullable=False)
    modelo = Column(String(100), nullable=False)
    altura_ru = Column(Integer)
    dispositivos = relationship("Dispositivo", back_populates="tipo")


class Ubicacion(Base):
    __tablename__ = "ubicaciones"

    id_ubicacion = Column(Integer, primary_key=True, index=True)
    nombre_centro_datos = Column(String(120), nullable=False)
    codigo_sala = Column(String(80), nullable=False)
    direccion = Column(String(250))
    clasificacion_tier = Column(String(30))
    racks = relationship("BastidorRack", back_populates="ubicacion")


class BastidorRack(Base):
    __tablename__ = "bastidores_racks"

    id_rack = Column(Integer, primary_key=True, index=True)
    id_ubicacion = Column(
        Integer,
        ForeignKey("ubicaciones.id_ubicacion", ondelete="RESTRICT"),
        nullable=False,
    )
    identificador = Column(String(80), nullable=False)
    unidades_ru = Column(Integer)
    potencia_max_watt = Column(Integer)
    numero_fila = Column(String(40))
    ubicacion = relationship("Ubicacion", back_populates="racks")
    dispositivos = relationship("Dispositivo", back_populates="rack")


class Dispositivo(Base):
    __tablename__ = "dispositivos"
    __table_args__ = (Index("uq_dispositivos_mac_address", "mac_address", unique=True),)

    id_dispositivo = Column(Integer, primary_key=True, index=True)
    id_tipo = Column(
        Integer,
        ForeignKey("tipos_dispositivo.id_tipo", ondelete="RESTRICT"),
        nullable=False,
    )
    id_rack = Column(
        Integer,
        ForeignKey("bastidores_racks.id_rack", ondelete="SET NULL"),
    )
    nombre_host = Column(String(120), nullable=False, unique=True, index=True)
    fqdn = Column(String(253), unique=True)
    numero_serie = Column(String(120), unique=True)
    ip_gestion = Column(String(45), unique=True)
    mac_address = Column(String(17))
    ru_inicio = Column(Integer)
    estado_operativo = Column(String(30), nullable=False, default="activo")
    tipo = relationship("TipoDispositivo", back_populates="dispositivos")
    rack = relationship("BastidorRack", back_populates="dispositivos")


class Subred(Base):
    __tablename__ = "subredes"
    __table_args__ = (
        UniqueConstraint("etiqueta_vlan", name="uq_subredes_vlan"),
        UniqueConstraint("cidr", name="uq_subredes_cidr"),
    )

    id_vlan = Column(Integer, primary_key=True, index=True)
    etiqueta_vlan = Column(Integer, nullable=False)
    cidr = Column(String(50), nullable=False)
    nombre_segmento = Column(String(100), nullable=False)
    descripcion = Column(String)


class DireccionIP(Base):
    __tablename__ = "direcciones_ip"
    __table_args__ = (UniqueConstraint("direccion", name="uq_direcciones_ip_direccion"),)

    id_ip = Column(Integer, primary_key=True, index=True)
    id_subred = Column(
        Integer,
        ForeignKey("subredes.id_vlan", ondelete="CASCADE"),
        nullable=False,
    )
    direccion = Column(String(45), nullable=False)
    estado_asignacion = Column(String(30), nullable=False, default="reservada")
    proposito = Column(String(100))


class ResultadoSondeo(Base):
    __tablename__ = "resultados_sondeo"
    __table_args__ = (
        Index("ix_sondeo_estado_actual", "id_dispositivo", "origen", "tipo", "id_resultado"),
        Index("ix_sondeo_fecha", "fecha_sondeo"),
    )

    id_resultado = Column(Integer, primary_key=True, index=True)
    id_dispositivo = Column(
        Integer,
        ForeignKey("dispositivos.id_dispositivo", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    origen = Column(String(20), nullable=False)
    tipo = Column(String(20), nullable=False)
    estado = Column(String(30), nullable=False)
    latencia_ms = Column(Integer)
    detalle = Column(JSON, nullable=False, default=dict)
    fecha_sondeo = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Alerta(Base):
    __tablename__ = "alertas"
    __table_args__ = (Index("ix_alertas_dispositivo_estado", "id_dispositivo", "estado"),)

    id_alerta = Column(Integer, primary_key=True, index=True)
    id_dispositivo = Column(
        Integer,
        ForeignKey("dispositivos.id_dispositivo", ondelete="CASCADE"),
        nullable=False,
    )
    tipo = Column(String(30), nullable=False)  # caida | latencia_alta
    mensaje = Column(String(300), nullable=False)
    estado = Column(String(20), nullable=False, default="abierta")  # abierta | resuelta
    fecha_apertura = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_resolucion = Column(DateTime(timezone=True))
