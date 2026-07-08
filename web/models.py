"""
Modelos de base de datos para el sistema de suscripciones.
Usa SQLAlchemy con PostgreSQL (obligatorio en todos los entornos).
"""
import os
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from web.db_engine import get_engine

PLANS = {
    "basic": {
        "name": "Básico",
        "name_en": "Basic",
        "price_monthly": 19.99,
        "price_yearly": 119.99,
        "original_price": 39.99,
        "discount_pct": 50,
        "max_assets": 5,
        "max_daily_alerts": 10,
        "languages": ["es", "en"],
        "dashboard_access": False,
        "api_access": False,
        "history_days": 7,
        "email_support": False,
        "priority_access": False,
        "weekly_digest": False,
        "features_es": [
            "5 criptomonedas",
            "Alertas en Telegram",
            "Análisis con Claude Sonnet 4.6",
            "Hasta 10 alertas al día",
        ],
        "features_en": [
            "5 cryptocurrencies",
            "Telegram alerts",
            "Analysis with Claude Sonnet 4.6",
            "Up to 10 alerts per day",
        ],
    },
    "premium": {
        "name": "Premium",
        "name_en": "Premium",
        "price_monthly": 39.99,
        "price_yearly": 239.99,
        "original_price": 79.99,
        "discount_pct": 50,
        "max_assets": 20,
        "max_daily_alerts": -1,  # unlimited
        "languages": ["es", "en"],
        "dashboard_access": False,
        "api_access": False,
        "history_days": 14,
        "email_support": True,
        "priority_access": True,
        "weekly_digest": False,
        "features_es": [
            "20 criptomonedas",
            "Alertas en Telegram",
            "Análisis con Claude Sonnet 4.6",
            "Alertas ilimitadas diarias",
            "Soporte por email",
            "Acceso prioritario a la app",
        ],
        "features_en": [
            "20 cryptocurrencies",
            "Telegram alerts",
            "Analysis with Claude Sonnet 4.6",
            "Unlimited daily alerts",
            "Email support",
            "Priority app access",
        ],
    },
    "pro": {
        "name": "Profesional",
        "name_en": "Professional",
        "price_monthly": 79.99,
        "price_yearly": 479.99,
        "original_price": 159.99,
        "discount_pct": 50,
        "max_assets": -1,  # unlimited (65+)
        "max_daily_alerts": -1,  # unlimited
        "languages": ["es", "en"],
        "dashboard_access": True,
        "api_access": True,
        "history_days": 30,
        "email_support": True,
        "priority_access": True,
        "weekly_digest": True,
        "features_es": [
            "65+ criptomonedas",
            "Alertas en Telegram",
            "Análisis con Claude Sonnet 4.6",
            "Alertas ilimitadas diarias",
            "Soporte prioritario por email",
            "Resumen semanal",
            "Acceso prioritario a nuevas funcionalidades",
        ],
        "features_en": [
            "65+ cryptocurrencies",
            "Telegram alerts",
            "Analysis with Claude Sonnet 4.6",
            "Unlimited daily alerts",
            "Priority email support",
            "Weekly digest",
            "Priority access to new features",
        ],
    },
}

AVAILABLE_ASSETS = [
    # ── Top 20 por capitalización ─────────────────────────────────────────────
    {"symbol": "BTC", "name": "Bitcoin", "icon": ""},
    {"symbol": "ETH", "name": "Ethereum", "icon": ""},
    {"symbol": "XRP", "name": "Ripple", "icon": ""},
    {"symbol": "SOL", "name": "Solana", "icon": ""},
    {"symbol": "BNB", "name": "Binance Coin", "icon": ""},
    {"symbol": "ADA", "name": "Cardano", "icon": ""},
    {"symbol": "DOGE", "name": "Dogecoin", "icon": ""},
    {"symbol": "TRX", "name": "Tron", "icon": ""},
    {"symbol": "TON", "name": "Toncoin", "icon": ""},
    {"symbol": "LINK", "name": "Chainlink", "icon": ""},
    {"symbol": "AVAX", "name": "Avalanche", "icon": ""},
    {"symbol": "SHIB", "name": "Shiba Inu", "icon": ""},
    {"symbol": "DOT", "name": "Polkadot", "icon": ""},
    {"symbol": "SUI", "name": "Sui", "icon": ""},
    {"symbol": "LTC", "name": "Litecoin", "icon": ""},
    {"symbol": "HBAR", "name": "Hedera", "icon": ""},
    {"symbol": "UNI", "name": "Uniswap", "icon": ""},
    {"symbol": "XLM", "name": "Stellar", "icon": ""},
    {"symbol": "NEAR", "name": "NEAR Protocol", "icon": ""},
    # ── Layer 2 & Infra ───────────────────────────────────────────────────────
    {"symbol": "ARB", "name": "Arbitrum", "icon": ""},
    {"symbol": "OP", "name": "Optimism", "icon": ""},
    {"symbol": "MATIC", "name": "Polygon", "icon": ""},
    {"symbol": "ICP", "name": "Internet Computer", "icon": ""},
    {"symbol": "FIL", "name": "Filecoin", "icon": ""},
    {"symbol": "IMX", "name": "Immutable", "icon": ""},
    {"symbol": "STX", "name": "Stacks", "icon": ""},
    {"symbol": "MNT", "name": "Mantle", "icon": ""},
    # ── DeFi ──────────────────────────────────────────────────────────────────
    {"symbol": "AAVE", "name": "Aave", "icon": ""},
    {"symbol": "MKR", "name": "Maker", "icon": ""},
    {"symbol": "CRV", "name": "Curve", "icon": ""},
    {"symbol": "DYDX", "name": "dYdX", "icon": ""},
    {"symbol": "PENDLE", "name": "Pendle", "icon": ""},
    {"symbol": "JUPITER", "name": "Jupiter", "icon": ""},
    # ── AI & Data ─────────────────────────────────────────────────────────────
    {"symbol": "FET", "name": "Fetch.ai", "icon": ""},
    {"symbol": "RENDER", "name": "Render", "icon": ""},
    {"symbol": "INJ", "name": "Injective", "icon": ""},
    {"symbol": "TAO", "name": "Bittensor", "icon": ""},
    {"symbol": "ONDO", "name": "Ondo Finance", "icon": ""},
    {"symbol": "AIOZ", "name": "AIOZ Network", "icon": ""},
    # ── Gaming & Metaverse ────────────────────────────────────────────────────
    {"symbol": "AXS", "name": "Axie Infinity", "icon": ""},
    {"symbol": "SAND", "name": "The Sandbox", "icon": ""},
    {"symbol": "MANA", "name": "Decentraland", "icon": ""},
    {"symbol": "GALA", "name": "Gala", "icon": ""},
    {"symbol": "ENJ", "name": "Enjin Coin", "icon": ""},
    # ── New L1s ───────────────────────────────────────────────────────────────
    {"symbol": "KAS", "name": "Kaspa", "icon": ""},
    # ── Memecoins ─────────────────────────────────────────────────────────────
    {"symbol": "WIF", "name": "Dogwifhat", "icon": ""},
    {"symbol": "FLOKI", "name": "Floki", "icon": ""},
    {"symbol": "BONK", "name": "Bonk", "icon": ""},
    # ── Exchange tokens ───────────────────────────────────────────────────────
    {"symbol": "CRO", "name": "Cronos", "icon": ""},
    {"symbol": "OKB", "name": "OKB", "icon": ""},
    {"symbol": "GT", "name": "Gate Token", "icon": ""},
    # ── Otros relevantes ──────────────────────────────────────────────────────
    {"symbol": "VET", "name": "VeChain", "icon": ""},
    {"symbol": "THETA", "name": "Theta", "icon": ""},
    {"symbol": "FTM", "name": "Fantom", "icon": ""},
    {"symbol": "EOS", "name": "EOS", "icon": ""},
    {"symbol": "RUNE", "name": "THORChain", "icon": ""},
    {"symbol": "GRT", "name": "The Graph", "icon": ""},
]


def get_conn():
    """
    Devuelve una conexión DBAPI de SQLAlchemy para PostgreSQL.
    Uso: with get_conn() as conn: conn.execute(text(...))
    """
    return get_engine("app").connect()


def init_db():
    """
    Inicializa la base de datos creando tablas si no existen (idempotente).
    # NEVER use drop_all() in production — esto solo crea tablas nuevas, nunca borra datos.
    """
    from sqlalchemy import (
        MetaData, Table, Column, Integer, String, Text, BigInteger,
        ForeignKey,
    )

    engine = get_engine("app")
    meta = MetaData()

    Table("users", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("email", String(255), unique=True, nullable=False),
        Column("password_hash", Text, nullable=False),
        Column("name", Text, nullable=False),
        Column("telegram_chat_id", Text),
        Column("language", String(10), server_default="es"),
        Column("created_at", Text),
        Column("is_active", Integer, server_default="1"),
    )

    Table("subscriptions", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
        Column("plan", Text, nullable=False, server_default="basic"),
        Column("billing_cycle", Text, nullable=False, server_default="monthly"),
        Column("status", Text, nullable=False, server_default="trial"),
        Column("trial_ends_at", Text),
        Column("current_period_end", Text),
        Column("stripe_subscription_id", Text),
        Column("stripe_customer_id", Text),
        Column("selected_assets", Text, server_default=""),
        Column("last_asset_change_at", Text),
        Column("created_at", Text),
        Column("updated_at", Text),
    )

    Table("payment_methods", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
        Column("stripe_payment_method_id", Text),
        Column("card_last4", Text),
        Column("card_brand", Text),
        Column("card_exp_month", Integer),
        Column("card_exp_year", Integer),
        Column("is_default", Integer, server_default="1"),
        Column("created_at", Text),
    )

    Table("alert_log", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
        Column("asset", Text),
        Column("direction", Text),
        Column("score", Integer),
        Column("sent_at", Text),
    )

    Table("newsletter_subscribers", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("first_name", String(100), nullable=False),
        Column("last_name", String(100), nullable=False),
        Column("email", String(255), unique=True, nullable=False),
        Column("subscribed_at", Text, nullable=False),
    )

    from sqlalchemy import UniqueConstraint
    Table("user_fcm_tokens", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
        Column("token", Text, nullable=False),
        Column("updated_at", Text),
        UniqueConstraint("user_id", "token", name="uq_user_fcm_token"),
    )

    # CREATE TABLE IF NOT EXISTS — idempotente, nunca borra datos
    meta.create_all(engine, checkfirst=True)

    # Migration: Add last_asset_change_at column if it doesn't exist (PostgreSQL)
    try:
        with engine.connect() as conn:
            # Check if column exists in PostgreSQL
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='subscriptions' AND column_name='last_asset_change_at'
            """)).fetchone()

            if not result:
                conn.execute(text("ALTER TABLE subscriptions ADD COLUMN last_asset_change_at TEXT"))
                conn.commit()
    except Exception as e:
        # Column already exists or table doesn't exist yet
        pass


class User(UserMixin):
    def __init__(self, row):
        self.id = row[0]
        self.email = row[1]
        self.password_hash = row[2]
        self.name = row[3]
        self.telegram_chat_id = row[4]
        self.language = row[5] or 'es'
        self.created_at = row[6]
        self.is_active_flag = row[7]

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_subscription(self):
        with get_conn() as conn:
            row = conn.execute(
                text("SELECT * FROM subscriptions WHERE user_id=:uid ORDER BY created_at DESC LIMIT 1"),
                {"uid": self.id},
            ).fetchone()
        if row:
            return {
                "id": row[0], "user_id": row[1], "plan": row[2],
                "billing_cycle": row[3], "status": row[4],
                "trial_ends_at": row[5], "current_period_end": row[6],
                "stripe_subscription_id": row[7], "stripe_customer_id": row[8],
                "selected_assets": (row[9] or "").split(",") if row[9] else [],
            }
        return None

    def get_plan_config(self):
        sub = self.get_subscription()
        if not sub:
            return None

        # Verificar si el trial expiró
        if sub["status"] == "trial":
            trial_end = sub.get("trial_ends_at")
            if trial_end:
                try:
                    from datetime import datetime, timezone
                    trial_end_dt = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) > trial_end_dt:
                        # Trial expirado → bloquear acceso
                        return None
                except Exception:
                    pass

        if sub["status"] not in ("active", "trial", "cancelled_pending"):
            return None
        return PLANS.get(sub["plan"], PLANS["basic"])

    def can_access_dashboard(self):
        config = self.get_plan_config()
        return config and config.get("dashboard_access", False)

    @staticmethod
    def get_by_id(user_id):
        with get_conn() as conn:
            row = conn.execute(
                text("SELECT id,email,password_hash,name,telegram_chat_id,language,created_at,is_active "
                     "FROM users WHERE id=:uid"),
                {"uid": user_id},
            ).fetchone()
        return User(row) if row else None

    @staticmethod
    def get_by_email(email):
        with get_conn() as conn:
            row = conn.execute(
                text("SELECT id,email,password_hash,name,telegram_chat_id,language,created_at,is_active "
                     "FROM users WHERE email=:email"),
                {"email": email},
            ).fetchone()
        return User(row) if row else None

    @staticmethod
    def create(email, password, name, language='es', plan='basic'):
        if plan not in ('basic', 'premium', 'pro'):
            plan = 'basic'
        pw_hash = generate_password_hash(password)
        now = datetime.now(timezone.utc).isoformat()
        trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        with get_conn() as conn:
            result = conn.execute(
                text("INSERT INTO users (email,password_hash,name,language,created_at) VALUES (:email,:pw,:name,:lang,:created_at) RETURNING id"),
                {"email": email, "pw": pw_hash, "name": name, "lang": language, "created_at": now},
            )
            user_id = result.fetchone()[0]
            conn.execute(
                text("INSERT INTO subscriptions (user_id,plan,status,trial_ends_at,created_at,updated_at) VALUES (:uid,:plan,:status,:trial,:now,:now)"),
                {"uid": user_id, "plan": plan, "status": "trial", "trial": trial_end, "now": now},
            )
            conn.commit()
        return User.get_by_id(user_id)
