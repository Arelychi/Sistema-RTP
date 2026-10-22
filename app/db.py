import json
from threading import Lock
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from werkzeug.security import check_password_hash, generate_password_hash

from app.config import settings

MAX_MODULES = 20
FIXED_MODULE_COUNT = 7


_schema_initialized = False
_schema_lock = Lock()


def normalize_display_text(value: str | None) -> str:
    """Normalize user-facing text to title case before storing it."""
    return " ".join(str(value or "").split()).title()


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """Open a PostgreSQL connection and close it after use."""
    if settings.database_url:
        connection = psycopg.connect(settings.database_url)
    else:
        connection = psycopg.connect(
            host=settings.pg_host,
            port=settings.pg_port,
            dbname=settings.pg_database,
            user=settings.pg_user,
            password=settings.pg_password,
        )
    try:
        yield connection
    finally:
        connection.close()


def initialize_schema() -> None:
    """Create the security, catalog and schedule tables."""
    global _schema_initialized
    if _schema_initialized:
        return
    with _schema_lock:
        if _schema_initialized:
            return
        _initialize_schema()
        refresh_analysis_tables()
        _schema_initialized = True


def _initialize_schema() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS seguridad")
            cursor.execute("CREATE SCHEMA IF NOT EXISTS catalogos")
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_namespace WHERE nspname = 'progrmacion'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM pg_namespace WHERE nspname = 'programacion'
                    ) THEN
                        ALTER SCHEMA progrmacion RENAME TO programacion;
                    ELSIF EXISTS (
                        SELECT 1 FROM pg_namespace WHERE nspname = 'progrmacion'
                    ) AND EXISTS (
                        SELECT 1 FROM pg_namespace WHERE nspname = 'programacion'
                    ) AND to_regclass('progrmacion.registros') IS NOT NULL
                      AND to_regclass('programacion.registros') IS NULL THEN
                        ALTER TABLE progrmacion.registros SET SCHEMA programacion;
                    END IF;
                END
                $$
                """
            )
            cursor.execute("CREATE SCHEMA IF NOT EXISTS programacion")
            cursor.execute("CREATE SCHEMA IF NOT EXISTS analisis")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.modulos (
                    id SMALLINT PRIMARY KEY CHECK (id BETWEEN 1 AND 20),
                    nombre VARCHAR(80) NOT NULL UNIQUE,
                    direccion VARCHAR(180),
                    latitud NUMERIC(10, 7),
                    longitud NUMERIC(10, 7)
                )
                """
            )
            cursor.execute("ALTER TABLE catalogos.modulos ADD COLUMN IF NOT EXISTS direccion VARCHAR(180)")
            cursor.execute("ALTER TABLE catalogos.modulos ADD COLUMN IF NOT EXISTS latitud NUMERIC(10, 7)")
            cursor.execute("ALTER TABLE catalogos.modulos ADD COLUMN IF NOT EXISTS longitud NUMERIC(10, 7)")
            cursor.execute("ALTER TABLE catalogos.modulos DROP CONSTRAINT IF EXISTS modulos_id_check")
            cursor.execute(
                "ALTER TABLE catalogos.modulos ADD CONSTRAINT modulos_id_check CHECK (id BETWEEN 1 AND 20)"
            )
            for module_number in range(1, FIXED_MODULE_COUNT + 1):
                cursor.execute(
                    """
                    INSERT INTO catalogos.modulos (id, nombre)
                    VALUES (%s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (module_number, f"Módulo {module_number}"),
                )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seguridad.usuarios (
                    id BIGSERIAL PRIMARY KEY,
                    username VARCHAR(80) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    module_number SMALLINT,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    tipo_usuario VARCHAR(20) NOT NULL DEFAULT 'usuario',
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    CONSTRAINT usuarios_access_target_ck CHECK (
                        (is_admin AND module_number IS NULL)
                        OR (NOT is_admin AND module_number BETWEEN 1 AND 20)
                        OR (NOT is_admin AND module_number IS NULL)
                    )
                )
                """
            )
            cursor.execute("ALTER TABLE seguridad.usuarios ADD COLUMN IF NOT EXISTS correo VARCHAR(160)")
            cursor.execute("ALTER TABLE seguridad.usuarios ADD COLUMN IF NOT EXISTS telefono VARCHAR(40)")
            cursor.execute("ALTER TABLE seguridad.usuarios ADD COLUMN IF NOT EXISTS tipo_usuario VARCHAR(20)")
            cursor.execute(
                "UPDATE seguridad.usuarios SET tipo_usuario = CASE WHEN is_admin THEN 'admin' ELSE 'usuario' END "
                "WHERE tipo_usuario IS NULL "
                "OR tipo_usuario NOT IN ('usuario', 'admin', 'consultor') "
                "OR (tipo_usuario IN ('usuario', 'admin') AND tipo_usuario <> CASE WHEN is_admin THEN 'admin' ELSE 'usuario' END)"
            )
            cursor.execute("ALTER TABLE seguridad.usuarios ALTER COLUMN tipo_usuario SET DEFAULT 'usuario'")
            cursor.execute("ALTER TABLE seguridad.usuarios ALTER COLUMN tipo_usuario SET NOT NULL")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seguridad.password_reset_tokens (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES seguridad.usuarios(id) ON DELETE CASCADE,
                    token_hash CHAR(64) NOT NULL UNIQUE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS password_reset_tokens_user_idx
                ON seguridad.password_reset_tokens (user_id, expires_at)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seguridad.historial_rol_mensual (
                    id BIGSERIAL PRIMARY KEY,
                    usuario VARCHAR(80) NOT NULL,
                    modulo SMALLINT,
                    modificacion VARCHAR(240) NOT NULL,
                    descripcion VARCHAR(500) NOT NULL DEFAULT '',
                    accion VARCHAR(30) NOT NULL DEFAULT 'registro',
                    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                "ALTER TABLE seguridad.historial_rol_mensual ADD COLUMN IF NOT EXISTS descripcion VARCHAR(500)"
            )
            cursor.execute(
                "UPDATE seguridad.historial_rol_mensual SET descripcion = modificacion WHERE descripcion IS NULL OR descripcion = ''"
            )
            cursor.execute(
                "ALTER TABLE seguridad.historial_rol_mensual ALTER COLUMN descripcion SET DEFAULT ''"
            )
            cursor.execute(
                "ALTER TABLE seguridad.historial_rol_mensual ALTER COLUMN descripcion SET NOT NULL"
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS historial_rol_mensual_fecha_idx
                ON seguridad.historial_rol_mensual (fecha_hora DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.controladores (
                    id BIGSERIAL PRIMARY KEY,
                    nombre VARCHAR(160) NOT NULL,
                    credencial VARCHAR(80) NOT NULL UNIQUE,
                    sexo VARCHAR(20) NOT NULL,
                    mod1 SMALLINT NOT NULL CHECK (mod1 BETWEEN 1 AND 20),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                "ALTER TABLE catalogos.controladores ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.turnos (
                    id BIGSERIAL PRIMARY KEY,
                    numero INTEGER NOT NULL UNIQUE,
                    hora_inicio TIME NOT NULL,
                    hora_fin TIME NOT NULL,
                    activo BOOLEAN NOT NULL DEFAULT TRUE,
                    alcance VARCHAR(20) NOT NULL DEFAULT 'especifico'
                )
                """
            )
            cursor.execute(
                "ALTER TABLE catalogos.turnos ADD COLUMN IF NOT EXISTS alcance VARCHAR(20) NOT NULL DEFAULT 'especifico'"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.turno_modulo (
                    turno_id BIGINT NOT NULL REFERENCES catalogos.turnos(id) ON DELETE CASCADE,
                    modulo_id SMALLINT NOT NULL REFERENCES catalogos.modulos(id) ON DELETE CASCADE,
                    activo BOOLEAN NOT NULL DEFAULT TRUE,
                    PRIMARY KEY (turno_id, modulo_id)
                )
                """
            )
            cursor.execute(
                "ALTER TABLE catalogos.turno_modulo ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE"
            )
            cursor.execute(
                """
                UPDATE catalogos.turnos AS t
                SET alcance = 'general'
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM catalogos.turno_modulo AS tm
                    WHERE tm.turno_id = t.id
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO catalogos.turno_modulo (turno_id, modulo_id, activo)
                SELECT t.id, m.id, TRUE
                FROM catalogos.turnos AS t
                CROSS JOIN catalogos.modulos AS m
                WHERE t.alcance = 'general'
                ON CONFLICT (turno_id, modulo_id) DO NOTHING
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.rol_mensual_periodos (
                    modulo_id SMALLINT NOT NULL REFERENCES catalogos.modulos(id) ON DELETE CASCADE,
                    mes SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
                    anio INTEGER NOT NULL CHECK (anio > 0),
                    activo BOOLEAN NOT NULL DEFAULT TRUE,
                    PRIMARY KEY (modulo_id, mes, anio)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.estados_especiales (
                    id BIGSERIAL PRIMARY KEY,
                    codigo VARCHAR(40) NOT NULL UNIQUE,
                    descripcion VARCHAR(160) NOT NULL,
                    categoria VARCHAR(20) NOT NULL DEFAULT 'falta'
                        CHECK (categoria IN ('descanso', 'falta', 'vacaciones', 'incapacidad')),
                    activo BOOLEAN NOT NULL DEFAULT TRUE
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE catalogos.estados_especiales
                ADD COLUMN IF NOT EXISTS categoria VARCHAR(20) NOT NULL DEFAULT 'falta'
                    CHECK (categoria IN ('descanso', 'falta', 'vacaciones', 'incapacidad'))
                """
            )
            cursor.execute(
                """
                ALTER TABLE catalogos.estados_especiales
                DROP CONSTRAINT IF EXISTS estados_especiales_categoria_check
                """
            )
            cursor.execute(
                """
                ALTER TABLE catalogos.estados_especiales
                ADD CONSTRAINT estados_especiales_categoria_check
                CHECK (categoria IN ('descanso', 'falta', 'vacaciones', 'incapacidad'))
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.tipos_rutas (
                    id SERIAL PRIMARY KEY,
                    descripcion VARCHAR(160) NOT NULL UNIQUE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.servicio (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(160) NOT NULL UNIQUE
                )
                """
            )
            cursor.execute(
                "ALTER TABLE catalogos.tipos_rutas ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE"
            )
            cursor.execute(
                "ALTER TABLE catalogos.servicio ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE"
            )
            for descripcion in (
                "Ruta Oficial RTP",
                "Ruta Provisional RTP",
                "Ruta Provisional Concesionado",
                "Servicio Especial de Frecuencia Intensiva",
                "Sendero Seguro",
                "Servicio Especial",
            ):
                cursor.execute(
                    """
                    INSERT INTO catalogos.tipos_rutas (descripcion)
                    VALUES (%s)
                    ON CONFLICT (descripcion) DO NOTHING
                    """,
                    (descripcion,),
                )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.rutas (
                    id BIGSERIAL PRIMARY KEY,
                    nomenclatura VARCHAR(40) NOT NULL,
                    ruta VARCHAR(80) NOT NULL,
                    origen VARCHAR(120) NOT NULL,
                    destino VARCHAR(120) NOT NULL,
                    servicio VARCHAR(120) NOT NULL,
                    estado VARCHAR(20) NOT NULL DEFAULT 'Activo',
                    mod1 SMALLINT NOT NULL CHECK (mod1 BETWEEN 1 AND 20),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE catalogos.rutas
                ADD COLUMN IF NOT EXISTS tipos INTEGER REFERENCES catalogos.tipos_rutas(id) ON DELETE SET NULL
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogos.modulo_ruta (
                    id BIGSERIAL PRIMARY KEY,
                    modulo_id SMALLINT NOT NULL CHECK (modulo_id BETWEEN 1 AND 20),
                    ruta_id BIGINT NOT NULL REFERENCES catalogos.rutas(id) ON DELETE CASCADE,
                    estado VARCHAR(20) NOT NULL DEFAULT 'Activo',
                    nomenclatura VARCHAR(40),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (modulo_id, ruta_id)
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE catalogos.modulo_ruta
                ADD COLUMN IF NOT EXISTS nomenclatura VARCHAR(40)
                """
            )
            cursor.execute("ALTER TABLE seguridad.usuarios DROP CONSTRAINT IF EXISTS usuarios_access_target_ck")
            cursor.execute(
                """
                ALTER TABLE seguridad.usuarios
                ADD CONSTRAINT usuarios_access_target_ck CHECK (
                    (tipo_usuario = 'admin' AND is_admin AND module_number IS NULL)
                    OR (tipo_usuario = 'usuario' AND NOT is_admin AND module_number BETWEEN 1 AND 20)
                    OR (tipo_usuario = 'consultor' AND NOT is_admin AND module_number IS NULL)
                )
                """
            )
            cursor.execute("ALTER TABLE catalogos.controladores DROP CONSTRAINT IF EXISTS controladores_mod1_check")
            cursor.execute("ALTER TABLE catalogos.controladores ADD CONSTRAINT controladores_mod1_check CHECK (mod1 BETWEEN 1 AND 20)")
            cursor.execute("ALTER TABLE catalogos.rutas DROP CONSTRAINT IF EXISTS rutas_mod1_check")
            cursor.execute("ALTER TABLE catalogos.rutas ADD CONSTRAINT rutas_mod1_check CHECK (mod1 BETWEEN 1 AND 20)")
            cursor.execute("ALTER TABLE catalogos.modulo_ruta DROP CONSTRAINT IF EXISTS modulo_ruta_modulo_id_check")
            cursor.execute("ALTER TABLE catalogos.modulo_ruta ADD CONSTRAINT modulo_ruta_modulo_id_check CHECK (modulo_id BETWEEN 1 AND 20)")
            for module_number in range(1, MAX_MODULES + 1):
                cursor.execute(
                    "SELECT id FROM catalogos.rutas WHERE mod1 = %s ORDER BY created_at, id",
                    (module_number,),
                )
                local_route_ids = [row[0] for row in cursor.fetchall()]
                for index, route_id in enumerate(local_route_ids):
                    cursor.execute(
                        "UPDATE catalogos.rutas SET nomenclatura = %s WHERE id = %s",
                        (route_nomenclature(index), route_id),
                    )
                cursor.execute(
                    """
                    SELECT mr.id FROM catalogos.modulo_ruta AS mr
                    JOIN catalogos.rutas AS r ON r.id = mr.ruta_id
                    WHERE mr.modulo_id = %s AND r.mod1 <> %s
                    ORDER BY mr.created_at, mr.id
                    """,
                    (module_number, module_number),
                )
                for index, association_id in enumerate([row[0] for row in cursor.fetchall()], len(local_route_ids)):
                    cursor.execute(
                        "UPDATE catalogos.modulo_ruta SET nomenclatura = %s WHERE id = %s",
                        (route_nomenclature(index), association_id),
                    )
            default_users = [
                (f"user{number}", f"user{number}", number, False)
                for number in range(1, 8)
            ] + [("administrador", "administrador", None, True)]
            for username, password, module_number, is_admin in default_users:
                cursor.execute(
                    """
                    INSERT INTO seguridad.usuarios (username, password_hash, module_number, is_admin, tipo_usuario)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (username) DO NOTHING
                    """,
                    (username, generate_password_hash(password), module_number, is_admin, "admin" if is_admin else "usuario"),
                )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_records (
                    id BIGSERIAL PRIMARY KEY,
                    name VARCHAR(160) NOT NULL,
                    credential VARCHAR(80) NOT NULL,
                    shift VARCHAR(40) NOT NULL,
                    route VARCHAR(80) NOT NULL,
                    nomenclature VARCHAR(20) NOT NULL,
                    month INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    work_days JSONB NOT NULL DEFAULT '[]'::jsonb,
                    rest_days JSONB NOT NULL DEFAULT '[]'::jsonb,
                    daily_assignments JSONB NOT NULL DEFAULT '{}'::jsonb,
                    daily_details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS programacion.registros (
                    id BIGSERIAL PRIMARY KEY,
                    module_number SMALLINT NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    credential VARCHAR(80) NOT NULL,
                    shift VARCHAR(40) NOT NULL,
                    route VARCHAR(80) NOT NULL,
                    nomenclature VARCHAR(20) NOT NULL,
                    month INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    work_days JSONB NOT NULL DEFAULT '[]'::jsonb,
                    rest_days JSONB NOT NULL DEFAULT '[]'::jsonb,
                    vacation_days JSONB NOT NULL DEFAULT '[]'::jsonb,
                    daily_assignments JSONB NOT NULL DEFAULT '{}'::jsonb,
                    daily_details JSONB NOT NULL DEFAULT '{}'::jsonb,
                    saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (module_number, credential, month, year)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analisis.trabajador_dia (
                    id BIGSERIAL PRIMARY KEY,
                    source_record_id BIGINT NOT NULL,
                    work_date DATE NOT NULL,
                    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                    year INTEGER NOT NULL CHECK (year > 0),
                    module_number SMALLINT NOT NULL,
                    credential VARCHAR(80) NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    status_code VARCHAR(40) NOT NULL,
                    status VARCHAR(40) NOT NULL,
                    shift VARCHAR(40),
                    route VARCHAR(80),
                    nomenclature VARCHAR(20),
                    daily_code VARCHAR(40),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (source_record_id, work_date)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS trabajador_dia_period_idx
                ON analisis.trabajador_dia (year, month, module_number, credential)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analisis.ruta_dia (
                    id BIGSERIAL PRIMARY KEY,
                    source_record_id BIGINT NOT NULL,
                    work_date DATE NOT NULL,
                    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                    year INTEGER NOT NULL CHECK (year > 0),
                    route_id BIGINT,
                    route VARCHAR(80) NOT NULL,
                    nomenclature VARCHAR(40),
                    origin VARCHAR(120),
                    destination VARCHAR(120),
                    route_type_id INTEGER,
                    route_type VARCHAR(160),
                    service VARCHAR(120),
                    route_status VARCHAR(20),
                    module_number SMALLINT NOT NULL,
                    credential VARCHAR(80) NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    shift VARCHAR(40),
                    assignment_status VARCHAR(40) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (source_record_id, work_date)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS ruta_dia_period_idx
                ON analisis.ruta_dia (year, month, module_number, route_id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analisis.analisis_trabajadores (
                    id BIGSERIAL PRIMARY KEY,
                    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                    year INTEGER NOT NULL CHECK (year > 0),
                    module_number SMALLINT NOT NULL,
                    credential VARCHAR(80) NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    sexo VARCHAR(20),
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    work_days_count INTEGER NOT NULL DEFAULT 0,
                    rest_days_count INTEGER NOT NULL DEFAULT 0,
                    absence_days_count INTEGER NOT NULL DEFAULT 0,
                    holiday_days_count INTEGER NOT NULL DEFAULT 0,
                    vacation_days_count INTEGER NOT NULL DEFAULT 0,
                    incapacity_days_count INTEGER NOT NULL DEFAULT 0,
                    permission_days_count INTEGER NOT NULL DEFAULT 0,
                    special_status_days_count INTEGER NOT NULL DEFAULT 0,
                    most_used_shift VARCHAR(40),
                    most_used_shift_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (month, year, module_number, credential)
                )
                """
            )
            cursor.execute(
                "ALTER TABLE analisis.analisis_trabajadores ADD COLUMN IF NOT EXISTS sexo VARCHAR(20)"
            )
            cursor.execute(
                "ALTER TABLE analisis.analisis_trabajadores ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analisis.analisis_rutas (
                    id BIGSERIAL PRIMARY KEY,
                    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                    year INTEGER NOT NULL CHECK (year > 0),
                    route_id BIGINT,
                    route VARCHAR(80) NOT NULL,
                    nomenclature VARCHAR(40),
                    origin VARCHAR(120),
                    destination VARCHAR(120),
                    route_type_id INTEGER,
                    route_type VARCHAR(160),
                    service VARCHAR(120),
                    route_status VARCHAR(20),
                    module_number SMALLINT NOT NULL,
                    assignment_count INTEGER NOT NULL DEFAULT 0,
                    work_day_count INTEGER NOT NULL DEFAULT 0,
                    controller_count INTEGER NOT NULL DEFAULT 0,
                    shared_module_count INTEGER NOT NULL DEFAULT 0,
                    is_shared BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (month, year, route_id, route, module_number)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS analisis_rutas_period_idx
                ON analisis.analisis_rutas (year, month, module_number, route_id)
                """
            )
            cursor.execute(
                """
                DELETE FROM schedule_records a
                USING schedule_records b
                WHERE a.id < b.id
                  AND a.credential = b.credential
                  AND a.month = b.month
                  AND a.year = b.year
                  AND a.module_number = b.module_number
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS schedule_records_unique_record_idx
                ON schedule_records (credential, month, year, module_number)
                """
            )
            cursor.execute(
                """
                ALTER TABLE schedule_records
                ADD COLUMN IF NOT EXISTS daily_assignments JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
            cursor.execute(
                """
                ALTER TABLE schedule_records
                ADD COLUMN IF NOT EXISTS daily_details JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
            cursor.execute(
                """
                ALTER TABLE schedule_records ADD COLUMN IF NOT EXISTS module_number SMALLINT NOT NULL DEFAULT 1
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS schedule_records_user_month_idx
                ON schedule_records (credential, month, year)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS schedule_records_module_month_idx
                ON schedule_records (module_number, month, year)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS modulo_ruta_module_idx
                ON catalogos.modulo_ruta (modulo_id, ruta_id)
                """
            )
        connection.commit()


def authenticate_user(username: str, password: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT username, password_hash, module_number, is_admin, tipo_usuario FROM seguridad.usuarios WHERE username = %s AND active",
                (username,),
            )
            user = cursor.fetchone()
    if not user or not check_password_hash(user[1], password):
        return None
    return {"username": user[0], "module_number": user[2], "is_admin": user[3] or user[4] == "admin", "tipo_usuario": user[4]}


def create_password_reset_token(identifier: str, token_hash: str, expires_at) -> dict | None:
    identifier = identifier.strip()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, correo
                FROM seguridad.usuarios
                WHERE active AND (
                    LOWER(TRIM(COALESCE(correo, ''))) = LOWER(%s)
                    OR TRIM(COALESCE(telefono, '')) = %s
                )
                ORDER BY id
                LIMIT 1
                """,
                (identifier, identifier),
            )
            user = cursor.fetchone()
            if user is None or not str(user[1] or '').strip():
                return None
            cursor.execute(
                """
                INSERT INTO seguridad.password_reset_tokens (user_id, token_hash, expires_at)
                VALUES (%s, %s, %s)
                """,
                (user[0], token_hash, expires_at),
            )
        connection.commit()
    return {"id": user[0], "correo": user[1]}


def fetch_password_reset_token(token_hash: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT token.id, token.user_id, users.correo, users.username, users.module_number
                FROM seguridad.password_reset_tokens AS token
                JOIN seguridad.usuarios AS users ON users.id = token.user_id
                WHERE token.token_hash = %s
                  AND token.used_at IS NULL
                  AND token.expires_at > NOW()
                  AND users.active
                """,
                (token_hash,),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return {
        "token_id": row[0],
        "user_id": row[1],
        "correo": row[2],
        "username": row[3],
        "module_number": row[4],
    }


def complete_password_reset(token_hash: str, user_id: int, password_hash: str) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE seguridad.usuarios
                SET password_hash = %s
                WHERE id = %s AND active
                """,
                (password_hash, user_id),
            )
            if cursor.rowcount != 1:
                return False
            cursor.execute(
                """
                UPDATE seguridad.password_reset_tokens
                SET used_at = NOW()
                WHERE user_id = %s AND used_at IS NULL
                """,
                (user_id,),
            )
        connection.commit()
    return True


def create_history_entry(
    username: str,
    module_number: int | None,
    description: str,
    action: str = "registro",
    detail: str | None = None,
) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO seguridad.historial_rol_mensual (usuario, modulo, modificacion, descripcion, accion)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (username, module_number, description[:240], (detail or description)[:500], action[:30]),
            )
        connection.commit()


def fetch_history_entries(limit: int = 500) -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT usuario, modulo, modificacion, descripcion, accion, fecha_hora
                FROM seguridad.historial_rol_mensual
                ORDER BY fecha_hora DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            columns = tuple(column.name for column in cursor.description)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_controllers(module_number: int | None = None, active_only: bool = False) -> list[dict]:
    active_filter = " AND active = TRUE" if active_only else ""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id, nombre, credencial, sexo, mod1, active FROM catalogos.controladores WHERE (%s::smallint IS NULL OR mod1 = %s){active_filter} ORDER BY nombre",
                (module_number, module_number),
            )
            return [dict(zip(("id", "nombre", "credencial", "sexo", "mod1", "active"), row)) for row in cursor.fetchall()]


def fetch_controller_by_credential(credential: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, nombre, credencial, sexo, mod1, active FROM catalogos.controladores WHERE credencial = %s",
                (credential,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(zip(("id", "nombre", "credencial", "sexo", "mod1", "active"), row))


def create_controller(controller: dict) -> dict:
    controller = {
        **controller,
        "nombre": normalize_display_text(controller.get("nombre")),
        "sexo": normalize_display_text(controller.get("sexo")),
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogos.controladores (nombre, credencial, sexo, mod1, active)
                VALUES (%(nombre)s, %(credencial)s, %(sexo)s, %(mod1)s, %(active)s)
                RETURNING id, nombre, credencial, sexo, mod1, active
                """,
                controller,
            )
            row = cursor.fetchone()
        connection.commit()
    return dict(zip(("id", "nombre", "credencial", "sexo", "mod1", "active"), row))


def update_controller(controller_id: int, payload: dict) -> dict | None:
    nombre = normalize_display_text(payload.get("nombre"))
    sexo = normalize_display_text(payload.get("sexo"))
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE catalogos.controladores
                SET nombre = %s, credencial = %s, sexo = %s, mod1 = %s, active = %s
                WHERE id = %s
                RETURNING id, nombre, credencial, sexo, mod1, active
                """,
                (nombre, payload["credencial"], sexo, payload.get("mod1", 1), payload.get("active", True), controller_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(column.name for column in cursor.description)
        connection.commit()
    return dict(zip(columns, row))


def save_month_records(records: list[dict], module_number: int, month: int, year: int) -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM programacion.registros WHERE module_number = %s AND month = %s AND year = %s",
                (module_number, month, year),
            )
            for record in records:
                name = normalize_display_text(record.get("name"))
                route = normalize_display_text(record.get("route"))
                daily_details = {
                    str(day): {
                        **detail,
                        "route": normalize_display_text(detail.get("route")),
                    }
                    if isinstance(detail, dict) else detail
                    for day, detail in (record.get("daily_details") or {}).items()
                }
                vacation_days = record.get("vacation_days")
                if vacation_days is None:
                    vacation_days = [
                        int(day)
                        for day, value in (record.get("daily_assignments") or {}).items()
                        if str(value).strip().upper() == "V"
                    ]
                cursor.execute(
                    """
                    INSERT INTO programacion.registros
                        (module_number, name, credential, shift, route, nomenclature,
                         month, year, work_days, rest_days, vacation_days,
                         daily_assignments, daily_details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                    """,
                    (
                        module_number,
                        name,
                        record["credential"],
                        record.get("shift", ""),
                        route,
                        record.get("nomenclature", ""),
                        month,
                        year,
                        json.dumps(record.get("work_days") or []),
                        json.dumps(record.get("rest_days") or []),
                        json.dumps(vacation_days),
                        json.dumps(record.get("daily_assignments") or {}),
                        json.dumps(daily_details),
                    ),
                )
        connection.commit()
    refresh_analysis_tables()
    return len(records)


def refresh_analysis_tables() -> None:
    """Rebuild clean daily and monthly datasets for Power BI."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE analisis.trabajador_dia, analisis.ruta_dia, analisis.analisis_trabajadores, analisis.analisis_rutas")
            cursor.execute(
                """
                INSERT INTO analisis.trabajador_dia (
                    source_record_id, work_date, month, year, module_number,
                    credential, name, status_code, status, shift, route,
                    nomenclature, daily_code
                )
                SELECT sr.id,
                       calendar.work_date,
                       sr.month,
                       sr.year,
                       sr.module_number,
                       sr.credential,
                       sr.name,
                       COALESCE(day_data.assignment, day_detail->>'code', '') AS status_code,
                       CASE
                           WHEN upper(COALESCE(day_data.assignment, day_detail->>'code', '')) IN ('V', 'VAC', 'VACACIONES')
                               THEN 'VACACIONES'
                           WHEN special_state.categoria = 'vacaciones'
                               THEN 'VACACIONES'
                           WHEN special_state.categoria = 'descanso'
                               THEN 'DESCANSO'
                           WHEN special_state.categoria = 'falta'
                               THEN 'FALTA'
                           WHEN special_state.categoria = 'incapacidad'
                               THEN 'INCAPACIDAD'
                           WHEN sr.rest_days @> to_jsonb(EXTRACT(DAY FROM calendar.work_date)::integer)
                               THEN 'DESCANSO'
                           WHEN upper(COALESCE(day_data.assignment, day_detail->>'code', '')) IN ('INC', 'INCAPACIDAD')
                               THEN 'INCAPACIDAD'
                           WHEN upper(COALESCE(day_data.assignment, day_detail->>'code', '')) IN ('PER', 'PERMISO')
                               THEN 'PERMISO'
                           WHEN upper(COALESCE(day_data.assignment, day_detail->>'code', '')) IN ('F', 'FALTA')
                               THEN 'FALTA'
                           WHEN upper(COALESCE(day_data.assignment, day_detail->>'code', '')) IN ('DF', 'FESTIVO')
                               THEN 'FESTIVO'
                           WHEN upper(COALESCE(day_data.assignment, day_detail->>'code', '')) = 'D'
                               THEN 'DESCANSO'
                           WHEN COALESCE(day_data.assignment, day_detail->>'code', '') <> ''
                               THEN 'TRABAJADO'
                           ELSE 'NO_PROGRAMADO'
                       END AS status,
                       COALESCE(day_detail->>'shift', sr.shift),
                       COALESCE(day_detail->>'route', sr.route),
                       COALESCE(day_detail->>'nomenclature', sr.nomenclature),
                       COALESCE(day_data.assignment, day_detail->>'code', '')
                FROM schedule_records AS sr
                CROSS JOIN LATERAL generate_series(
                    make_date(sr.year, sr.month, 1),
                    (make_date(sr.year, sr.month, 1) + INTERVAL '1 month - 1 day')::date,
                    INTERVAL '1 day'
                ) AS calendar(work_date)
                LEFT JOIN LATERAL (
                    SELECT sr.daily_assignments ->> EXTRACT(DAY FROM calendar.work_date)::integer::text AS assignment
                ) AS day_data ON TRUE
                LEFT JOIN LATERAL (
                    SELECT sr.daily_details -> (EXTRACT(DAY FROM calendar.work_date)::integer::text) AS day_detail
                ) AS detail_data ON TRUE
                LEFT JOIN catalogos.estados_especiales AS special_state
                    ON upper(special_state.codigo) = upper(
                        COALESCE(day_data.assignment, day_detail->>'code', '')
                    )
                WHERE sr.year > 0 AND sr.month BETWEEN 1 AND 12
                """
            )
            cursor.execute(
                """
                INSERT INTO analisis.ruta_dia (
                    source_record_id, work_date, month, year, route_id, route,
                    nomenclature, origin, destination, route_type_id, route_type,
                    service, route_status, module_number, credential, name, shift,
                    assignment_status
                )
                SELECT td.source_record_id,
                       td.work_date,
                       td.month,
                       td.year,
                       route_data.id,
                       td.route,
                       COALESCE(route_data.nomenclatura, td.nomenclature),
                       route_data.origen,
                       route_data.destino,
                       route_data.tipos,
                       route_data.route_type,
                       route_data.servicio,
                       route_data.estado,
                       td.module_number,
                       td.credential,
                       td.name,
                       td.shift,
                       td.status
                FROM analisis.trabajador_dia AS td
                LEFT JOIN LATERAL (
                    SELECT r.id, r.nomenclatura, r.origen, r.destino, r.tipos,
                           r.servicio, r.estado, tr.descripcion AS route_type
                    FROM catalogos.rutas AS r
                    LEFT JOIN catalogos.tipos_rutas AS tr ON tr.id = r.tipos
                    WHERE lower(r.ruta) = lower(td.route)
                       OR lower(r.nomenclatura) = lower(td.nomenclature)
                    ORDER BY CASE WHEN lower(r.ruta) = lower(td.route) THEN 0 ELSE 1 END,
                             r.id
                    LIMIT 1
                ) AS route_data ON TRUE
                WHERE NULLIF(TRIM(td.route), '') IS NOT NULL
                  AND td.status = 'TRABAJADO'
                """
            )
            cursor.execute(
                """
                INSERT INTO analisis.analisis_trabajadores (
                    month, year, module_number, credential, name, sexo, active,
                    work_days_count, rest_days_count, absence_days_count,
                    holiday_days_count, vacation_days_count, incapacity_days_count,
                    permission_days_count, special_status_days_count,
                    most_used_shift, most_used_shift_count
                )
                SELECT td.month,
                       td.year,
                       td.module_number,
                       td.credential,
                       MAX(td.name),
                       MAX(controller.sexo),
                       COALESCE(BOOL_AND(controller.active), TRUE),
                       COUNT(*) FILTER (WHERE td.status = 'TRABAJADO'),
                       COUNT(*) FILTER (WHERE td.status = 'DESCANSO'),
                       COUNT(*) FILTER (WHERE td.status = 'FALTA'),
                       COUNT(*) FILTER (WHERE td.status = 'FESTIVO'),
                       COUNT(*) FILTER (WHERE td.status = 'VACACIONES'),
                       COUNT(*) FILTER (WHERE td.status = 'INCAPACIDAD'),
                       COUNT(*) FILTER (WHERE td.status = 'PERMISO'),
                       COUNT(*) FILTER (WHERE td.status IN ('FALTA', 'FESTIVO', 'VACACIONES', 'INCAPACIDAD', 'PERMISO')),
                       shift_usage.shift,
                       COALESCE(shift_usage.usage_count, 0)
                FROM analisis.trabajador_dia AS td
                LEFT JOIN catalogos.controladores AS controller
                    ON controller.credencial = td.credential
                LEFT JOIN LATERAL (
                    SELECT td2.shift, COUNT(*) AS usage_count
                    FROM analisis.trabajador_dia AS td2
                    WHERE td2.month = td.month
                      AND td2.year = td.year
                      AND td2.module_number = td.module_number
                      AND td2.credential = td.credential
                      AND td2.status = 'TRABAJADO'
                      AND NULLIF(TRIM(td2.shift), '') IS NOT NULL
                    GROUP BY td2.shift
                    ORDER BY COUNT(*) DESC, td2.shift
                    LIMIT 1
                ) AS shift_usage ON TRUE
                GROUP BY td.month, td.year, td.module_number, td.credential,
                         shift_usage.shift, shift_usage.usage_count
                """
            )
            cursor.execute(
                """
                INSERT INTO analisis.analisis_rutas (
                    month, year, route_id, route, nomenclature, origin, destination,
                    route_type_id, route_type, service, route_status, module_number,
                    assignment_count, work_day_count, controller_count,
                    shared_module_count, is_shared
                )
                WITH periods AS (
                    SELECT DISTINCT month, year
                    FROM schedule_records
                ),
                route_modules AS (
                    SELECT r.id AS route_id, r.mod1 AS module_number
                    FROM catalogos.rutas AS r
                    UNION
                    SELECT mr.ruta_id, mr.modulo_id
                    FROM catalogos.modulo_ruta AS mr
                ),
                route_usage AS (
                    SELECT route_id, month, year, module_number,
                           COUNT(*) AS assignment_count,
                           COUNT(DISTINCT work_date) AS work_day_count,
                           COUNT(DISTINCT credential) AS controller_count
                    FROM analisis.ruta_dia
                    GROUP BY route_id, month, year, module_number
                )
                SELECT periods.month,
                       periods.year,
                       r.id,
                       r.ruta,
                       r.nomenclatura,
                       r.origen,
                       r.destino,
                       r.tipos,
                       tr.descripcion,
                       r.servicio,
                       r.estado,
                       route_modules.module_number,
                       COALESCE(route_usage.assignment_count, 0),
                       COALESCE(route_usage.work_day_count, 0),
                       COALESCE(route_usage.controller_count, 0),
                       shared.module_count,
                       shared.module_count > 1
                FROM periods
                CROSS JOIN route_modules
                JOIN catalogos.rutas AS r ON r.id = route_modules.route_id
                LEFT JOIN catalogos.tipos_rutas AS tr ON tr.id = r.tipos
                LEFT JOIN route_usage
                    ON route_usage.route_id = r.id
                   AND route_usage.month = periods.month
                   AND route_usage.year = periods.year
                   AND route_usage.module_number = route_modules.module_number
                LEFT JOIN LATERAL (
                    SELECT COUNT(*)::integer AS module_count
                    FROM route_modules AS shared_modules
                    WHERE shared_modules.route_id = r.id
                ) AS shared ON TRUE
                """
            )
        connection.commit()


def update_controller_status(controller_id: int, active: bool) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogos.controladores SET active = %s WHERE id = %s RETURNING id, active",
                (active, controller_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
        connection.commit()
    return {"id": row[0], "active": row[1]}


def update_shift_status(shift_id: int, active: bool) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogos.turnos SET activo = %s WHERE id = %s RETURNING id, activo",
                (active, shift_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
        connection.commit()
    return {"id": row[0], "activo": row[1]}


def get_monthly_role_activation(module_number: int, month: int, year: int) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT activo FROM catalogos.rol_mensual_periodos WHERE modulo_id = %s AND mes = %s AND anio = %s",
                (module_number, month, year),
            )
            row = cursor.fetchone()
            return bool(row and row[0])


def set_monthly_role_activation(module_number: int, month: int, year: int, active: bool) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogos.rol_mensual_periodos (modulo_id, mes, anio, activo)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (modulo_id, mes, anio)
                DO UPDATE SET activo = EXCLUDED.activo
                RETURNING activo
                """,
                (module_number, month, year, active),
            )
            result = bool(cursor.fetchone()[0])
        connection.commit()
    return result


def delete_controller(controller_id: int) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM catalogos.controladores WHERE id = %s", (controller_id,))
            deleted = cursor.rowcount > 0
        connection.commit()
    return deleted


def fetch_users(module_number: int | None = None) -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, correo, telefono, module_number, is_admin, tipo_usuario, active
                FROM seguridad.usuarios
                WHERE (%s::integer IS NULL OR module_number = %s::integer)
                ORDER BY username
                """,
                (module_number, module_number),
            )
            columns = tuple(column.name for column in cursor.description)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_modules() -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, nombre, direccion, latitud, longitud
                FROM catalogos.modulos
                WHERE id <= %s OR direccion IS NOT NULL
                ORDER BY id
                """,
                (FIXED_MODULE_COUNT,),
            )
            return [dict(zip(("id", "nombre", "direccion", "latitud", "longitud"), row)) for row in cursor.fetchall()]


def create_module(nombre: str, direccion: str, latitud: str, longitud: str) -> dict | None:
    nombre = normalize_display_text(nombre)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, nombre, direccion
                FROM catalogos.modulos
                WHERE id BETWEEN %s AND %s
                ORDER BY id
                """,
                (FIXED_MODULE_COUNT + 1, MAX_MODULES),
            )
            existing_modules = {
                row[0]: {"nombre": row[1], "direccion": row[2]}
                for row in cursor.fetchall()
            }
            next_id = next(
                (
                    module_id
                    for module_id in range(FIXED_MODULE_COUNT + 1, MAX_MODULES + 1)
                    if module_id not in existing_modules
                    or (
                        existing_modules[module_id]["nombre"] == f"Módulo {module_id}"
                        and existing_modules[module_id]["direccion"] is None
                    )
                ),
                None,
            )
            if next_id is None:
                return None
            if next_id in existing_modules:
                cursor.execute(
                    """
                    UPDATE catalogos.modulos
                    SET nombre = %s, direccion = %s, latitud = %s, longitud = %s
                    WHERE id = %s
                    RETURNING id, nombre, direccion, latitud, longitud
                    """,
                    (nombre, direccion.strip(), latitud, longitud, next_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO catalogos.modulos (id, nombre, direccion, latitud, longitud)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, nombre, direccion, latitud, longitud
                    """,
                    (next_id, nombre, direccion.strip(), latitud, longitud),
                )
            row = cursor.fetchone()
        connection.commit()
    return dict(zip(("id", "nombre", "direccion", "latitud", "longitud"), row))


def update_module(module_id: int, nombre: str, direccion: str, latitud: str, longitud: str) -> dict | None:
    nombre = normalize_display_text(nombre)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogos.modulos SET nombre = %s, direccion = %s, latitud = %s, longitud = %s WHERE id = %s RETURNING id, nombre, direccion, latitud, longitud",
                (nombre, direccion.strip(), latitud, longitud, module_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
        connection.commit()
    return dict(zip(("id", "nombre", "direccion", "latitud", "longitud"), row))


def delete_module(module_id: int) -> str:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (SELECT 1 FROM seguridad.usuarios WHERE module_number = %s)
                    OR EXISTS (SELECT 1 FROM catalogos.controladores WHERE mod1 = %s)
                    OR EXISTS (SELECT 1 FROM catalogos.rutas WHERE mod1 = %s)
                    OR EXISTS (SELECT 1 FROM catalogos.modulo_ruta WHERE modulo_id = %s)
                """,
                (module_id, module_id, module_id, module_id),
            )
            if cursor.fetchone()[0]:
                return "in_use"
            cursor.execute("DELETE FROM catalogos.modulos WHERE id = %s", (module_id,))
            deleted = cursor.rowcount > 0
        connection.commit()
    return "deleted" if deleted else "missing"


def fetch_admin_users() -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, correo, telefono, module_number, is_admin, tipo_usuario, active
                FROM seguridad.usuarios
                WHERE is_admin = TRUE OR tipo_usuario = 'admin'
                ORDER BY username
                """
            )
            columns = tuple(column.name for column in cursor.description)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_consultant_users() -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, password_hash, correo, telefono, module_number, is_admin, tipo_usuario, active
                FROM seguridad.usuarios
                WHERE tipo_usuario = 'consultor'
                ORDER BY username
                """
            )
            columns = tuple(column.name for column in cursor.description)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def create_user(user: dict) -> dict:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO seguridad.usuarios (username, password_hash, correo, telefono, module_number, is_admin, tipo_usuario, active)
                VALUES (%(username)s, %(password_hash)s, %(correo)s, %(telefono)s, %(module_number)s, %(is_admin)s, %(tipo_usuario)s, TRUE)
                RETURNING id, username, correo, telefono, module_number, is_admin, tipo_usuario, active
                """,
                user,
            )
            row = cursor.fetchone()
            columns = tuple(column.name for column in cursor.description)
        connection.commit()
    return dict(zip(columns, row))


def update_user(user_id: int, payload: dict) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            if payload.get("password_hash"):
                cursor.execute(
                    """
                    UPDATE seguridad.usuarios
                    SET username = %s, password_hash = %s, correo = %s, telefono = %s, module_number = %s, is_admin = %s, tipo_usuario = %s, active = %s
                    WHERE id = %s
                    RETURNING id, username, correo, telefono, module_number, is_admin, tipo_usuario, active
                    """,
                    (payload["username"], payload["password_hash"], payload.get("correo"), payload.get("telefono"), payload.get("module_number"), payload["is_admin"], payload["tipo_usuario"], payload.get("active", True), user_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE seguridad.usuarios
                    SET username = %s, correo = %s, telefono = %s, module_number = %s, is_admin = %s, tipo_usuario = %s, active = %s
                    WHERE id = %s
                    RETURNING id, username, correo, telefono, module_number, is_admin, tipo_usuario, active
                    """,
                    (payload["username"], payload.get("correo"), payload.get("telefono"), payload.get("module_number"), payload["is_admin"], payload["tipo_usuario"], payload.get("active", True), user_id),
                )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(column.name for column in cursor.description)
        connection.commit()
    return dict(zip(columns, row))


def update_user_status(user_id: int, active: bool) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE seguridad.usuarios SET active = %s WHERE id = %s "
                "RETURNING id, username, active",
                (active, user_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
        connection.commit()
    return {"id": row[0], "username": row[1], "active": row[2]}


def delete_user(user_id: int) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM seguridad.usuarios WHERE id = %s RETURNING id",
                (user_id,),
            )
            deleted = cursor.fetchone() is not None
        connection.commit()
    return deleted


ROUTE_COLUMNS = ("id", "nomenclatura", "ruta", "origen", "destino", "servicio", "estado", "mod1")


def route_nomenclature(index: int) -> str:
    value = ""
    position = index
    while True:
        value = chr(65 + position % 26) + value
        position = position // 26 - 1
        if position < 0:
            return value


def next_route_nomenclature(connection, module_number: int, route_id: int | None = None) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT nomenclatura FROM catalogos.rutas
            WHERE mod1 = %s AND (%s::bigint IS NULL OR id <> %s)
            UNION ALL
                        SELECT mr.nomenclatura FROM catalogos.modulo_ruta AS mr
                        JOIN catalogos.rutas AS r ON r.id = mr.ruta_id
                        WHERE mr.modulo_id = %s AND r.mod1 <> %s
                            AND (%s::bigint IS NULL OR mr.ruta_id <> %s)
            """,
                        (module_number, route_id, route_id, module_number, module_number, route_id, route_id),
        )
        used = {str(row[0]).strip().upper() for row in cursor.fetchall() if row[0]}
    index = 0
    while True:
        value = ""
        position = index
        while True:
            value = chr(65 + position % 26) + value
            position = position // 26 - 1
            if position < 0:
                break
        if value not in used:
            return value
        index += 1


def fetch_routes(module_number: int) -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                  SELECT r.id, r.nomenclatura, r.ruta, r.origen, r.destino, r.servicio,
                      r.estado, r.mod1, r.tipos, tr.descripcion AS tipos_descripcion, FALSE AS is_external,
                      COALESCE((
                          SELECT json_agg(json_build_object('id', m.id, 'nombre', m.nombre) ORDER BY m.id)
                          FROM catalogos.modulos AS m
                          WHERE m.id = r.mod1
                             OR EXISTS (
                                 SELECT 1
                                 FROM catalogos.modulo_ruta AS shared
                                 WHERE shared.ruta_id = r.id AND shared.modulo_id = m.id
                             )
                      ), '[]'::json) AS shared_modules
                  FROM catalogos.rutas AS r
                  LEFT JOIN catalogos.tipos_rutas AS tr ON tr.id = r.tipos
                  WHERE r.mod1 = %s
                  UNION ALL
                  SELECT r.id, COALESCE(mr.nomenclatura, r.nomenclatura), r.ruta,
                      r.origen, r.destino, r.servicio, mr.estado, r.mod1, r.tipos, tr.descripcion AS tipos_descripcion,
                      TRUE AS is_external,
                      COALESCE((
                          SELECT json_agg(json_build_object('id', m.id, 'nombre', m.nombre) ORDER BY m.id)
                          FROM catalogos.modulos AS m
                          WHERE m.id = r.mod1
                             OR EXISTS (
                                 SELECT 1
                                 FROM catalogos.modulo_ruta AS shared
                                 WHERE shared.ruta_id = r.id AND shared.modulo_id = m.id
                             )
                      ), '[]'::json) AS shared_modules
                  FROM catalogos.rutas AS r
                  JOIN catalogos.modulo_ruta AS mr ON mr.ruta_id = r.id
                  LEFT JOIN catalogos.tipos_rutas AS tr ON tr.id = r.tipos
                  WHERE mr.modulo_id = %s AND r.mod1 <> %s
                ORDER BY nomenclatura, ruta, origen
                """,
                  (module_number, module_number, module_number),
            )
            columns = tuple(column.name for column in cursor.description)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_analysis_metrics() -> dict:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FILTER (WHERE NOT is_admin) AS users,
                       COUNT(*) FILTER (WHERE is_admin OR tipo_usuario = 'admin') AS admins
                FROM seguridad.usuarios
                WHERE active = TRUE
                """
            )
            users, admins = cursor.fetchone()

            cursor.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE active) AS active
                FROM catalogos.controladores
                """
            )
            controllers, active_controllers = cursor.fetchone()

            cursor.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(sexo), ''), 'Sin especificar') AS sexo, COUNT(*) AS total
                FROM catalogos.controladores
                WHERE active = TRUE
                GROUP BY 1
                ORDER BY total DESC, sexo
                """
            )
            gender_distribution = [
                {"sexo": row[0], "total": row[1]} for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT sr.route,
                       COUNT(*) AS assignments,
                       COUNT(DISTINCT sr.credential) AS controllers,
                       COUNT(DISTINCT sr.module_number) AS modules
                FROM programacion.registros AS sr
                WHERE NULLIF(TRIM(sr.route), '') IS NOT NULL
                GROUP BY sr.route
                ORDER BY assignments DESC, controllers DESC, sr.route
                LIMIT 12
                """
            )
            route_usage = [
                {
                    "ruta": row[0],
                    "asignaciones": row[1],
                    "controladores": row[2],
                    "modulos": row[3],
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                  SELECT sr.route,
                      COUNT(DISTINCT sr.credential) AS controllers,
                      COUNT(DISTINCT sr.module_number) AS modules
                  FROM programacion.registros AS sr
                  WHERE NULLIF(TRIM(sr.route), '') IS NOT NULL
                  GROUP BY sr.route
                  ORDER BY controllers DESC, modules DESC, sr.route
                LIMIT 1
                """
            )
            most_controllers = cursor.fetchone()

            cursor.execute("SELECT COUNT(*) FROM catalogos.rutas")
            routes = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*) FILTER (WHERE estado = 'Activo'),
                       COUNT(*) FILTER (WHERE estado <> 'Activo')
                FROM catalogos.rutas
                """
            )
            active_routes, inactive_routes = cursor.fetchone()

            cursor.execute(
                """
                SELECT r.ruta, COUNT(*) AS shared_count,
                       COUNT(DISTINCT mr.modulo_id) AS modules
                FROM catalogos.modulo_ruta AS mr
                JOIN catalogos.rutas AS r ON r.id = mr.ruta_id
                GROUP BY r.ruta
                ORDER BY shared_count DESC, modules DESC, r.ruta
                LIMIT 10
                """
            )
            shared_routes = [
                {"ruta": row[0], "compartida": row[1], "modulos": row[2]}
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT sr.credential, sr.name,
                       SUM(jsonb_array_length(sr.work_days)) AS dias_trabajados,
                       SUM(jsonb_array_length(sr.rest_days)) AS dias_descanso,
                       SUM(jsonb_array_length(sr.vacation_days)) AS dias_vacaciones
                FROM programacion.registros AS sr
                GROUP BY sr.credential, sr.name
                ORDER BY sr.name, sr.credential
                LIMIT 100
                """
            )
            controller_days = [
                {
                    "credencial": row[0],
                    "nombre": row[1],
                    "trabajados": row[2] or 0,
                    "descanso": row[3] or 0,
                    "vacaciones": row[4] or 0,
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT NULLIF(TRIM(shift), '') AS turno, COUNT(*) AS usos
                FROM programacion.registros
                WHERE NULLIF(TRIM(shift), '') IS NOT NULL
                GROUP BY 1
                ORDER BY usos DESC, turno
                """
            )
            shift_usage = [{"turno": row[0], "usos": row[1]} for row in cursor.fetchall()]

    return {
        "users": users or 0,
        "admins": admins or 0,
        "controllers": controllers or 0,
        "active_controllers": active_controllers or 0,
        "routes": routes or 0,
        "active_routes": active_routes or 0,
        "inactive_routes": inactive_routes or 0,
        "gender_distribution": gender_distribution,
        "route_usage": route_usage,
        "shared_routes": shared_routes,
        "controller_days": controller_days,
        "shift_usage": shift_usage,
        "most_controllers": (
            {
                "ruta": most_controllers[0],
                "controladores": most_controllers[1],
                "modulos": most_controllers[2],
            }
            if most_controllers
            else None
        ),
    }


def create_route(route: dict, module_number: int) -> dict:
    route = {
        **route,
        "ruta": normalize_display_text(route.get("ruta")),
        "origen": normalize_display_text(route.get("origen")),
        "destino": normalize_display_text(route.get("destino")),
        "servicio": normalize_display_text(route.get("servicio")),
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            nomenclatura = next_route_nomenclature(connection, module_number)
            cursor.execute(
                """
                INSERT INTO catalogos.rutas
                    (nomenclatura, ruta, origen, destino, servicio, estado, mod1, tipos)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, nomenclatura, ruta, origen, destino, servicio, estado, mod1, tipos
                """,
                (nomenclatura, route["ruta"], route["origen"], route["destino"], route["servicio"], route.get("estado", "Activo"), module_number, route.get("tipos")),
            )
            row = cursor.fetchone()
            columns = tuple(column.name for column in cursor.description)
        connection.commit()
    result = dict(zip(columns, row))
    result["is_external"] = False
    return result


def update_route(route_id: int, route: dict) -> dict | None:
    route = {
        **route,
        "ruta": normalize_display_text(route.get("ruta")),
        "origen": normalize_display_text(route.get("origen")),
        "destino": normalize_display_text(route.get("destino")),
        "servicio": normalize_display_text(route.get("servicio")),
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE catalogos.rutas
                SET ruta = %s, origen = %s, destino = %s,
                    servicio = %s, estado = %s, tipos = %s
                WHERE id = %s
                RETURNING id, nomenclatura, ruta, origen, destino, servicio, estado, mod1, tipos
                """,
                (route["ruta"], route["origen"], route["destino"], route["servicio"], route.get("estado", "Activo"), route.get("tipos"), route_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(column.name for column in cursor.description)
        connection.commit()
    result = dict(zip(columns, row))
    result["is_external"] = False
    return result


def update_admin_route(route_id: int, route: dict) -> dict | None:
    route = {
        **route,
        "ruta": normalize_display_text(route.get("ruta")),
        "origen": normalize_display_text(route.get("origen")),
        "destino": normalize_display_text(route.get("destino")),
        "servicio": normalize_display_text(route.get("servicio")),
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE catalogos.rutas
                SET ruta = %s, origen = %s, destino = %s,
                    servicio = %s, estado = %s, mod1 = %s, tipos = %s
                WHERE id = %s
                RETURNING id, nomenclatura, ruta, origen, destino, servicio, estado, mod1, tipos
                """,
                (route["ruta"], route["origen"], route["destino"], route["servicio"], route.get("estado", "Activo"), route["mod1"], route.get("tipos"), route_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(column.name for column in cursor.description)
        connection.commit()
    result = dict(zip(columns, row))
    result["is_external"] = False
    return result


def delete_route(route_id: int) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM catalogos.rutas WHERE id = %s", (route_id,))
            deleted = cursor.rowcount > 0
        connection.commit()
    return deleted


def update_route_status(route_id: int, estado: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE catalogos.rutas SET estado = %s WHERE id = %s RETURNING id, estado", (estado, route_id))
            row = cursor.fetchone()
        connection.commit()
    return dict(zip(("id", "estado"), row)) if row else None


def fetch_external_routes(module_number: int, query: str = "", origin_module: int | None = None) -> list[dict]:
    filters = ["r.mod1 <> %s", "NOT EXISTS (SELECT 1 FROM catalogos.modulo_ruta mr WHERE mr.ruta_id = r.id AND mr.modulo_id = %s)"]
    values: list = [module_number, module_number]
    if query:
        filters.append("(r.ruta ILIKE %s OR r.origen ILIKE %s OR r.destino ILIKE %s OR r.servicio ILIKE %s)")
        values.extend([f"%{query}%"] * 4)
    if origin_module:
        filters.append("r.mod1 = %s")
        values.append(origin_module)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.id, r.nomenclatura, r.ruta, r.origen, r.destino, r.servicio,
                       r.estado, r.mod1, FALSE AS is_external
                FROM catalogos.rutas AS r
                WHERE """ + " AND ".join(filters) + " ORDER BY r.ruta, r.origen",
                values,
            )
            columns = tuple(column.name for column in cursor.description)
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_shared_modules(route_id: int) -> list[int]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT modulo_id FROM catalogos.modulo_ruta WHERE ruta_id = %s ORDER BY modulo_id",
                (route_id,),
            )
            return [row[0] for row in cursor.fetchall()]


def fetch_shared_module_statuses(route_id: int) -> dict[int, str]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT modulo_id, estado FROM catalogos.modulo_ruta WHERE ruta_id = %s ORDER BY modulo_id",
                (route_id,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}


def link_route_to_module(route_id: int, module_number: int, estado: str | None = None) -> dict:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, mod1, estado FROM catalogos.rutas WHERE id = %s",
                (route_id,),
            )
            route_row = cursor.fetchone()
            if route_row is None or route_row[1] == module_number:
                raise ValueError("La ruta no existe o pertenece al módulo actual")

            module_status = estado or route_row[2]
            nomenclatura = next_route_nomenclature(connection, module_number)
            cursor.execute(
                """
                INSERT INTO catalogos.modulo_ruta (modulo_id, ruta_id, estado, nomenclatura)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (modulo_id, ruta_id) DO UPDATE
                    SET estado = EXCLUDED.estado,
                        nomenclatura = EXCLUDED.nomenclatura
                RETURNING id, modulo_id, ruta_id, estado, nomenclatura
                """,
                (module_number, route_id, module_status, nomenclatura),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("La ruta no existe o pertenece al módulo actual")
        connection.commit()
    return dict(zip(("id", "modulo_id", "ruta_id", "estado", "nomenclatura"), row))


def update_module_route_status(route_id: int, module_number: int, estado: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogos.modulo_ruta SET estado = %s WHERE ruta_id = %s AND modulo_id = %s RETURNING ruta_id, estado",
                (estado, route_id, module_number),
            )
            row = cursor.fetchone()
        connection.commit()
    return dict(zip(("ruta_id", "estado"), row)) if row else None


def unlink_route_from_module(route_id: int, module_number: int) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM catalogos.modulo_ruta WHERE ruta_id = %s AND modulo_id = %s", (route_id, module_number))
            deleted = cursor.rowcount > 0
        connection.commit()
    return deleted


def _catalog_item(columns: tuple[str, ...], row: tuple) -> dict:
    item = dict(zip(columns, row))
    for key, value in item.items():
        if hasattr(value, "isoformat"):
            item[key] = value.isoformat(timespec="minutes")
    return item


def fetch_catalog_items(table: str, module_number: int | None = None) -> list[dict]:
    queries = {
        "turnos": "SELECT id, numero, hora_inicio, hora_fin, activo, alcance FROM catalogos.turnos ORDER BY hora_inicio, id",
        "estados_especiales": "SELECT id, codigo, descripcion, categoria, activo FROM catalogos.estados_especiales ORDER BY codigo",
        "tipos_rutas": "SELECT id, descripcion, activo FROM catalogos.tipos_rutas ORDER BY descripcion",
        "servicio": "SELECT id, nombre, activo FROM catalogos.servicio ORDER BY nombre",
    }
    if table not in queries:
        raise ValueError("Catálogo no válido")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            if table == "turnos" and module_number is not None:
                queries[table] = """
                    SELECT t.id, t.numero, t.hora_inicio, t.hora_fin, t.activo, t.alcance
                    FROM catalogos.turnos AS t
                    JOIN catalogos.turno_modulo AS tm ON tm.turno_id = t.id
                    WHERE tm.modulo_id = %s AND tm.activo
                    ORDER BY t.hora_inicio, t.id
                """
                cursor.execute(queries[table], (module_number,))
            else:
                cursor.execute(queries[table])
            columns = tuple(column.name for column in cursor.description)
            return [_catalog_item(columns, row) for row in cursor.fetchall()]


def fetch_turno_modules(turno_id: int) -> list[int]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT modulo_id FROM catalogos.turno_modulo WHERE turno_id = %s ORDER BY modulo_id",
                (turno_id,),
            )
            return [row[0] for row in cursor.fetchall()]


def turno_start_exists(hora_inicio: str, exclude_id: int | None = None) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            query = "SELECT 1 FROM catalogos.turnos WHERE hora_inicio = %s"
            values: list[object] = [hora_inicio]
            if exclude_id is not None:
                query += " AND id <> %s"
                values.append(exclude_id)
            query += " LIMIT 1"
            cursor.execute(query, tuple(values))
            return cursor.fetchone() is not None


def get_next_turno_number() -> int:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(numero), 0) + 1 FROM catalogos.turnos")
            return int(cursor.fetchone()[0])


def renumber_turnos_by_start() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM catalogos.turnos ORDER BY hora_inicio, id")
            turno_ids = [row[0] for row in cursor.fetchall()]
            if not turno_ids:
                return
            cursor.execute(
                "UPDATE catalogos.turnos SET numero = -1000000000 - id WHERE id = ANY(%s)",
                (turno_ids,),
            )
            for number, turno_id in enumerate(turno_ids, start=1):
                cursor.execute(
                    "UPDATE catalogos.turnos SET numero = %s WHERE id = %s",
                    (number, turno_id),
                )
        connection.commit()


def fetch_turno_modules_map(turno_ids: list[int]) -> dict[int, list[int]]:
    if not turno_ids:
        return {}
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT turno_id, modulo_id FROM catalogos.turno_modulo WHERE turno_id = ANY(%s) ORDER BY turno_id, modulo_id",
                (turno_ids,),
            )
            modules_by_shift: dict[int, list[int]] = {}
            for turno_id, module_id in cursor.fetchall():
                modules_by_shift.setdefault(turno_id, []).append(module_id)
            return modules_by_shift


def fetch_turno_module_status_map(turno_id: int) -> dict[int, bool]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT modulo_id, activo FROM catalogos.turno_modulo WHERE turno_id = %s ORDER BY modulo_id",
                (turno_id,),
            )
            return {module_id: active for module_id, active in cursor.fetchall()}


def fetch_turno_module_statuses_map(turno_ids: list[int]) -> dict[int, dict[int, bool]]:
    if not turno_ids:
        return {}
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT turno_id, modulo_id, activo FROM catalogos.turno_modulo WHERE turno_id = ANY(%s) ORDER BY turno_id, modulo_id",
                (turno_ids,),
            )
            statuses: dict[int, dict[int, bool]] = {}
            for turno_id, module_id, active in cursor.fetchall():
                statuses.setdefault(turno_id, {})[module_id] = active
            return statuses


def update_turno_module_status(turno_id: int, module_id: int, active: bool) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE catalogos.turno_modulo
                SET activo = %s
                WHERE turno_id = %s AND modulo_id = %s
                """,
                (active, turno_id, module_id),
            )
            updated = cursor.rowcount == 1
        connection.commit()
    return updated


def set_turno_modules(
    turno_id: int,
    module_numbers: list[int],
    module_statuses: dict[int, bool] | None = None,
) -> None:
    module_statuses = module_statuses or {}
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM catalogos.turno_modulo WHERE turno_id = %s", (turno_id,))
            for module_number in module_numbers:
                cursor.execute(
                    "INSERT INTO catalogos.turno_modulo (turno_id, modulo_id, activo) VALUES (%s, %s, %s)",
                    (turno_id, module_number, module_statuses.get(module_number, True)),
                )
        connection.commit()


def create_catalog_item(table: str, payload: dict) -> dict:
    if table == "turnos":
        statement = "INSERT INTO catalogos.turnos (numero, hora_inicio, hora_fin, activo, alcance) VALUES (%s, %s, %s, %s, %s) RETURNING id, numero, hora_inicio, hora_fin, activo, alcance"
        values = (payload["numero"], payload["hora_inicio"], payload["hora_fin"], payload.get("activo", True), payload.get("alcance", "especifico"))
    elif table == "tipos_rutas":
        statement = "INSERT INTO catalogos.tipos_rutas (descripcion, activo) VALUES (%s, %s) RETURNING id, descripcion, activo"
        values = (normalize_display_text(payload["descripcion"]), payload.get("activo", True))
    elif table == "estados_especiales":
        statement = "INSERT INTO catalogos.estados_especiales (codigo, descripcion, categoria, activo) VALUES (%s, %s, %s, %s) RETURNING id, codigo, descripcion, categoria, activo"
        values = (str(payload["codigo"]).strip().upper(), normalize_display_text(payload["descripcion"]), payload["categoria"], payload.get("activo", True))
    elif table == "servicio":
        statement = "INSERT INTO catalogos.servicio (nombre, activo) VALUES (%s, %s) RETURNING id, nombre, activo"
        values = (normalize_display_text(payload["nombre"]), payload.get("activo", True))
    else:
        raise ValueError("Catálogo no válido")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(statement, values)
            columns = tuple(column.name for column in cursor.description)
            result = _catalog_item(columns, cursor.fetchone())
        connection.commit()
    return result


def update_catalog_item(table: str, item_id: int, payload: dict) -> dict:
    if table == "turnos":
        statement = "UPDATE catalogos.turnos SET numero = %s, hora_inicio = %s, hora_fin = %s, activo = %s, alcance = %s WHERE id = %s RETURNING id, numero, hora_inicio, hora_fin, activo, alcance"
        values = (payload["numero"], payload["hora_inicio"], payload["hora_fin"], payload.get("activo", True), payload.get("alcance", "especifico"), item_id)
    elif table == "tipos_rutas":
        statement = "UPDATE catalogos.tipos_rutas SET descripcion = %s, activo = %s WHERE id = %s RETURNING id, descripcion, activo"
        values = (normalize_display_text(payload["descripcion"]), payload.get("activo", True), item_id)
    elif table == "estados_especiales":
        statement = "UPDATE catalogos.estados_especiales SET codigo = %s, descripcion = %s, categoria = %s, activo = %s WHERE id = %s RETURNING id, codigo, descripcion, categoria, activo"
        values = (str(payload["codigo"]).strip().upper(), normalize_display_text(payload["descripcion"]), payload["categoria"], payload.get("activo", True), item_id)
    elif table == "servicio":
        statement = "UPDATE catalogos.servicio SET nombre = %s, activo = %s WHERE id = %s RETURNING id, nombre, activo"
        values = (normalize_display_text(payload["nombre"]), payload.get("activo", True), item_id)
    else:
        raise ValueError("Catálogo no válido")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(statement, values)
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(column.name for column in cursor.description)
            result = _catalog_item(columns, row)
        connection.commit()
    return result


def update_catalog_status(table: str, item_id: int, active: bool) -> dict | None:
    statements = {
        "tipos_rutas": (
            "UPDATE catalogos.tipos_rutas SET activo = %s WHERE id = %s "
            "RETURNING id, descripcion, activo"
        ),
        "servicio": (
            "UPDATE catalogos.servicio SET activo = %s WHERE id = %s "
            "RETURNING id, nombre, activo"
        ),
    }
    if table not in statements:
        raise ValueError("Catálogo no válido para cambiar estado")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(statements[table], (active, item_id))
            row = cursor.fetchone()
            if row is None:
                return None
            columns = tuple(column.name for column in cursor.description)
            result = _catalog_item(columns, row)
        connection.commit()
    return result


def delete_catalog_item(table: str, item_id: int) -> bool:
    tables = {
        "turnos": "catalogos.turnos",
        "tipos_rutas": "catalogos.tipos_rutas",
        "estados_especiales": "catalogos.estados_especiales",
        "servicio": "catalogos.servicio",
    }
    if table not in tables:
        raise ValueError("Catálogo no válido")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {tables[table]} WHERE id = %s", (item_id,))
            deleted = cursor.rowcount > 0
        connection.commit()
    return deleted


def fetch_records(month: int, year: int, module_number: int) -> list[dict]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                  SELECT sr.id,
                         COALESCE(c.nombre, sr.name) AS name,
                         COALESCE(c.credencial, sr.credential) AS credential,
                         sr.shift, sr.route, sr.nomenclature,
                         sr.month, sr.year, sr.work_days, sr.rest_days,
                         sr.daily_assignments, sr.daily_details,
                         sr.module_number, sr.created_at
                  FROM schedule_records AS sr
                  LEFT JOIN catalogos.controladores AS c
                    ON c.credencial = sr.credential
                  WHERE sr.month = %s AND sr.year = %s AND sr.module_number = %s
                  ORDER BY sr.created_at DESC, sr.id DESC
                """,
                (month, year, module_number),
            )
            columns = [column.name for column in cursor.description]
            rows = []
            seen = set()
            for row in cursor.fetchall():
                item = dict(zip(columns, row))
                key = (item.get("credential"), item.get("month"), item.get("year"), item.get("module_number"))
                if key in seen:
                    continue
                seen.add(key)
                item["work_days"] = item.get("work_days") or []
                item["rest_days"] = item.get("rest_days") or []
                item["daily_assignments"] = item.get("daily_assignments") or {}
                item["daily_details"] = item.get("daily_details") or {}
                rows.append(item)
            return rows


def upsert_record(record: dict) -> dict:
    record = {
        **record,
        "name": normalize_display_text(record.get("name")),
        "route": normalize_display_text(record.get("route")),
    }
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, work_days, rest_days, daily_assignments, daily_details
                FROM schedule_records
                WHERE credential = %(credential)s
                                    AND month = %(month)s AND year = %(year)s
                                    AND module_number = %(module_number)s
                FOR UPDATE
                """,
                record,
            )
            existing = cursor.fetchone()
            new_work_days = set(json.loads(record["work_days"]))
            new_rest_days = set(json.loads(record["rest_days"]))
            incoming_assignments = json.loads(record.get("daily_assignments") or "{}") if record.get("daily_assignments") else {}
            incoming_details = json.loads(record.get("daily_details") or "{}") if record.get("daily_details") else {}
            deleted_days = {int(day) for day in record.get("deleted_days", [])}
            normalized_assignments = {
                str(day): str(value).strip().upper()
                for day, value in incoming_assignments.items()
                if int(day) not in deleted_days
            }
            for day in deleted_days:
                normalized_assignments.pop(str(day), None)
            for day in sorted(day for day in new_work_days if day not in deleted_days):
                normalized_assignments.setdefault(str(day), f"{record['nomenclature']}{record['shift']}")
            for day in sorted({int(day) for day, value in normalized_assignments.items() if str(value).upper() == "V"}):
                normalized_assignments[str(day)] = "V"
            vacation_mask = {str(day) for day, value in normalized_assignments.items() if str(value).upper() == "V"}
            work_days = sorted(day for day in new_work_days if day not in deleted_days and str(day) not in vacation_mask)
            rest_days = sorted(day for day in new_rest_days if day not in deleted_days and str(day) not in vacation_mask)
            normalized_details = {
                str(day): {
                    **value,
                    "route": normalize_display_text(value.get("route")),
                }
                if isinstance(value, dict) else value
                for day, value in incoming_details.items()
                if int(day) not in deleted_days
            }

            if existing:
                cursor.execute(
                    """
                    UPDATE schedule_records
                    SET name = %(name)s, shift = %(shift)s, route = %(route)s,
                        nomenclature = %(nomenclature)s, work_days = %(work_days)s::jsonb,
                        rest_days = %(rest_days)s::jsonb,
                            daily_assignments = %(daily_assignments)s::jsonb,
                            daily_details = %(daily_details)s::jsonb
                    WHERE id = %(id)s
                    RETURNING id, name, credential, shift, route, nomenclature,
                              month, year, work_days, rest_days, daily_assignments,
                              module_number
                    """,
                    {
                        **record,
                        "id": existing[0],
                        "work_days": json.dumps(work_days),
                        "rest_days": json.dumps(rest_days),
                        "daily_assignments": json.dumps(normalized_assignments),
                        "daily_details": json.dumps(normalized_details),
                    },
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO schedule_records
                        (name, credential, shift, route, nomenclature, month, year,
                         work_days, rest_days, daily_assignments, daily_details, module_number)
                    VALUES (%(name)s, %(credential)s, %(shift)s, %(route)s,
                        %(nomenclature)s, %(month)s, %(year)s, %(work_days)s::jsonb,
                            %(rest_days)s::jsonb, %(daily_assignments)s::jsonb,
                            %(daily_details)s::jsonb,
                            %(module_number)s)
                    RETURNING id, name, credential, shift, route, nomenclature,
                              month, year, work_days, rest_days, daily_assignments,
                              daily_details,
                              module_number
                    """,
                    {
                        **record,
                        "work_days": json.dumps(work_days),
                        "rest_days": json.dumps(rest_days),
                        "daily_assignments": json.dumps(normalized_assignments),
                        "daily_details": json.dumps(normalized_details),
                    },
                )
            columns = [column.name for column in cursor.description]
            saved = dict(zip(columns, cursor.fetchone()))
            saved["work_days"] = saved.get("work_days") or []
            saved["rest_days"] = saved.get("rest_days") or []
            saved["daily_assignments"] = saved.get("daily_assignments") or {}
            saved["daily_details"] = saved.get("daily_details") or {}
        connection.commit()
    return saved
