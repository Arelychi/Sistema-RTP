from app.db import get_connection


def check_connection() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), version();")
            database, version = cursor.fetchone()

    print(f"Conexión correcta a: {database}")
    print(f"Servidor: {version}")


if __name__ == "__main__":
    try:
        check_connection()
    except Exception as error:
        print(f"No se pudo conectar a PostgreSQL: {error}")
        raise SystemExit(1) from error
