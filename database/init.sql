CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS roles (
    id_rol SERIAL PRIMARY KEY,
    nombre VARCHAR(50) NOT NULL UNIQUE,
    descripcion TEXT,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO roles (id_rol, nombre, descripcion) VALUES
    (1, 'Admin', 'Administra usuarios, roles y todos los activos'),
    (2, 'Técnico', 'Consulta, registra y actualiza activos de red'),
    (3, 'Auditor', 'Consulta información sin modificarla')
ON CONFLICT (id_rol) DO UPDATE
SET nombre = EXCLUDED.nombre, descripcion = EXCLUDED.descripcion;

SELECT setval(
    pg_get_serial_sequence('roles', 'id_rol'),
    GREATEST((SELECT COALESCE(MAX(id_rol), 1) FROM roles), 1)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_rol INT NOT NULL REFERENCES roles(id_rol) ON DELETE RESTRICT,
    nombre_usuario VARCHAR(100) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE,
    hash_clave VARCHAR(255) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    ultimo_acceso TIMESTAMPTZ
);

INSERT INTO usuarios (id_usuario, id_rol, nombre_usuario, correo, hash_clave, activo)
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    1,
    'Admin',
    'admin@netinventory.com',
    '$2b$12$OI.7R4zF66lY.FtBmAKv/Ojy4D1syfIRf6Ujj49D8mvJfLF0Ot6X.',
    TRUE
)
ON CONFLICT (correo) DO NOTHING;

CREATE TABLE IF NOT EXISTS tipos_dispositivo (
    id_tipo SERIAL PRIMARY KEY,
    categoria VARCHAR(40) NOT NULL,
    fabricante VARCHAR(100) NOT NULL,
    modelo VARCHAR(100) NOT NULL,
    altura_ru INT,
    CONSTRAINT uq_tipo_dispositivo_catalogo UNIQUE (categoria, fabricante, modelo)
);

INSERT INTO tipos_dispositivo (categoria, fabricante, modelo) VALUES
    ('Servidor', 'Genérico', 'Servidor'),
    ('Switch', 'Genérico', 'Switch'),
    ('Router', 'Genérico', 'Router'),
    ('PC', 'Genérico', 'PC'),
    ('Impresora', 'Genérico', 'Impresora')
ON CONFLICT (categoria, fabricante, modelo) DO NOTHING;

CREATE TABLE IF NOT EXISTS ubicaciones (
    id_ubicacion SERIAL PRIMARY KEY,
    nombre_centro_datos VARCHAR(120) NOT NULL,
    codigo_sala VARCHAR(80) NOT NULL,
    direccion VARCHAR(250),
    clasificacion_tier VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS bastidores_racks (
    id_rack SERIAL PRIMARY KEY,
    id_ubicacion INT NOT NULL REFERENCES ubicaciones(id_ubicacion) ON DELETE RESTRICT,
    identificador VARCHAR(80) NOT NULL,
    unidades_ru INT,
    potencia_max_watt INT,
    numero_fila VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS dispositivos (
    id_dispositivo SERIAL PRIMARY KEY,
    id_tipo INT NOT NULL REFERENCES tipos_dispositivo(id_tipo) ON DELETE RESTRICT,
    id_rack INT REFERENCES bastidores_racks(id_rack) ON DELETE SET NULL,
    nombre_host VARCHAR(120) NOT NULL UNIQUE,
    fqdn VARCHAR(253) UNIQUE,
    numero_serie VARCHAR(120) UNIQUE,
    ip_gestion VARCHAR(45) UNIQUE,
    mac_address VARCHAR(17),
    ru_inicio INT,
    estado_operativo VARCHAR(30) NOT NULL DEFAULT 'activo',
    CONSTRAINT uq_dispositivos_mac_address UNIQUE (mac_address)
);

CREATE TABLE IF NOT EXISTS subredes (
    id_vlan SERIAL PRIMARY KEY,
    etiqueta_vlan INT NOT NULL UNIQUE CHECK (etiqueta_vlan BETWEEN 1 AND 4094),
    cidr VARCHAR(50) NOT NULL UNIQUE,
    nombre_segmento VARCHAR(100) NOT NULL,
    descripcion VARCHAR(1000)
);

CREATE TABLE IF NOT EXISTS direcciones_ip (
    id_ip SERIAL PRIMARY KEY,
    id_subred INT NOT NULL REFERENCES subredes(id_vlan) ON DELETE CASCADE,
    direccion VARCHAR(45) NOT NULL UNIQUE,
    estado_asignacion VARCHAR(30) NOT NULL DEFAULT 'reservada',
    proposito VARCHAR(100)
);
