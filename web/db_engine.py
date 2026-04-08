"""
web/db_engine.py — Fábrica de engines SQLAlchemy.

Usa PostgreSQL exclusivamente (obligatorio en todos los entornos).
DATABASE_URL debe estar configurada — si no, la app no arranca.

# IMPORTANTE: En startup, usar SOLO meta.create_all() (idempotente).
# NUNCA meta.drop_all() — borraría todos los datos en producción.
# Para resetear datos usar el endpoint /admin/reset-predictions
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

_engines: dict[str, Engine] = {}


def _get_database_url() -> str:
    """
    Obtiene y valida la URL de conexión a PostgreSQL.
    Raises RuntimeError si DATABASE_URL no está definida.
    """
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "PostgreSQL is required in all environments. "
            "Set DATABASE_URL=postgresql://user:password@host:5432/dbname"
        )
    # Railway a veces da URLs con 'postgres://' (deprecated) — corregir a 'postgresql://'
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def get_engine(name: str = "app") -> Engine:
    """
    Obtiene (o crea) el engine SQLAlchemy para PostgreSQL.

    Args:
        name: 'app' o 'predictions' — ambas usan el mismo PostgreSQL.

    Returns:
        SQLAlchemy Engine listo para usar.
    """
    # Todas las BDs comparten el mismo PostgreSQL
    cache_key = "postgres"
    if cache_key not in _engines:
        url = _get_database_url()
        _engines[cache_key] = create_engine(
            url, pool_pre_ping=True, pool_size=5, max_overflow=10
        )
    return _engines[cache_key]


def is_postgres() -> bool:
    """Siempre True — PostgreSQL es obligatorio en todos los entornos."""
    return True
