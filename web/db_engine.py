"""
web/db_engine.py — Fábrica de engines SQLAlchemy.

Soporta SQLite (desarrollo local) y PostgreSQL (producción en Railway).
Detecta automáticamente el tipo de BD a través de DATABASE_URL.

# NEVER use db.drop_all() in production
# Usar siempre db.create_all() / CREATE TABLE IF NOT EXISTS (idempotente)
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

_engines: dict[str, Engine] = {}


def _build_engine(url: str) -> Engine:
    """Crea un engine SQLAlchemy para la URL dada."""
    if "sqlite" in url:
        return create_engine(url, connect_args={"check_same_thread": False})
    # PostgreSQL: habilitar pool con reconexión automática
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def _resolve_url(env_key: str, fallback_path: str) -> str:
    """
    Resuelve la URL de conexión a la BD:
    - Si DATABASE_URL está definida → usa PostgreSQL (Railway)
    - En caso contrario → SQLite local en la ruta indicada
    """
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        # Railway usa el prefijo legacy 'postgres://' — SQLAlchemy requiere 'postgresql://'
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # SQLite local
    db_path = os.getenv(env_key, fallback_path)
    abs_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    return f"sqlite:///{abs_path}"


def get_engine(name: str = "app") -> Engine:
    """
    Obtiene (o crea) el engine SQLAlchemy para la base de datos indicada.

    Args:
        name: 'app' para la BD de usuarios, 'predictions' para predicciones.

    Returns:
        SQLAlchemy Engine listo para usar.
    """
    # En producción (DATABASE_URL configurada), ambas BD comparten el mismo PostgreSQL
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        cache_key = "postgres"
    else:
        cache_key = name

    if cache_key not in _engines:
        if name == "app":
            url = _resolve_url("APP_DB_PATH", "data/app.db")
        elif name == "predictions":
            url = _resolve_url("PREDICTIONS_DB_PATH", "data/predictions.db")
        else:
            raise ValueError(f"Engine desconocido: {name!r}")
        _engines[cache_key] = _build_engine(url)

    return _engines[cache_key]


def is_postgres() -> bool:
    """Devuelve True si la BD configurada es PostgreSQL."""
    return bool(os.getenv("DATABASE_URL", "").strip())
