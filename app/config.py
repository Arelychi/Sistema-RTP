import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _is_production() -> bool:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    return environment in {"production", "prod"} or os.getenv("RENDER", "").lower() == "true"


@dataclass(frozen=True)
class Settings:
    environment: str
    secret_key: str
    database_url: str | None
    pg_host: str
    pg_port: str
    pg_database: str | None
    pg_user: str | None
    pg_password: str | None

    @property
    def is_production(self) -> bool:
        return _is_production()


def load_settings() -> Settings:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    secret_key = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        if _is_production():
            raise RuntimeError("SECRET_KEY es obligatoria en producción.")
        secret_key = "clave-local-de-desarrollo"

    return Settings(
        environment=environment,
        secret_key=secret_key,
        database_url=os.getenv("DATABASE_URL"),
        pg_host=os.getenv("PGHOST", "localhost"),
        pg_port=os.getenv("PGPORT", "5432"),
        pg_database=os.getenv("PGDATABASE"),
        pg_user=os.getenv("PGUSER"),
        pg_password=os.getenv("PGPASSWORD"),
    )


settings = load_settings()