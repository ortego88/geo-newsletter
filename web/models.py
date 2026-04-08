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
        "name": "Básica",
        "name_en": "Basic",
        "price_monthly": 14.99,
        "price_yearly": 149.99,
        "original_price": 24.99,
        "discount_pct": 40,
        "max_assets": 1,
        "max_daily_alerts": 5,
        "languages": ["es", "en"],
        "dashboard_access": False,
        "api_access": False,
        "history_days": 1,
    },
    "premium": {
        "name": "Premium",
        "name_en": "Premium",
        "price_monthly": 29.99,
        "price_yearly": 299.99,
        "original_price": 59.99,
        "discount_pct": 50,
        "max_assets": 3,
        "max_daily_alerts": 10,
        "languages": ["es", "en"],
        "dashboard_access": False,
        "api_access": False,
        "history_days": 7,
    },
    "pro": {
        "name": "Profesional",
        "name_en": "Professional",
        "price_monthly": 59.99,
        "price_yearly": 599.99,
        "original_price": 99.99,
        "discount_pct": 40,
        "max_assets": -1,  # unlimited
        "max_daily_alerts": -1,  # unlimited
        "languages": ["es", "en"],
        "dashboard_access": True,
        "api_access": True,
        "history_days": 30,
    },
}

AVAILABLE_ASSETS = [
    # ── IBEX 35 — índice general ─────────────────────────────────────────────
    {"symbol": "IBEX35", "name": "IBEX 35", "icon": "🇪🇸"},
    # ── IBEX 35 — empresas ───────────────────────────────────────────────────
    {"symbol": "ACS", "name": "ACS Actividades", "icon": "🏗️"},
    {"symbol": "ACX", "name": "Acerinox", "icon": "🔩"},
    {"symbol": "AENA", "name": "AENA", "icon": "✈️"},
    {"symbol": "ALM", "name": "Almirall", "icon": "💊"},
    {"symbol": "AMS", "name": "Amadeus IT", "icon": "💻"},
    {"symbol": "ANA", "name": "Acciona", "icon": "🌱"},
    {"symbol": "BBVA", "name": "BBVA", "icon": "🏦"},
    {"symbol": "BKT", "name": "Bankinter", "icon": "🏦"},
    {"symbol": "CABK", "name": "CaixaBank", "icon": "🏦"},
    {"symbol": "CLNX", "name": "Cellnex", "icon": "📡"},
    {"symbol": "COL", "name": "Inmobiliaria Colonial", "icon": "🏢"},
    {"symbol": "ELE", "name": "Endesa", "icon": "⚡"},
    {"symbol": "ENG", "name": "Enagás", "icon": "🔵"},
    {"symbol": "FDR", "name": "Fluidra", "icon": "💧"},
    {"symbol": "FER", "name": "Ferrovial", "icon": "🌉"},
    {"symbol": "GRF", "name": "Grifols", "icon": "🩸"},
    {"symbol": "IAG", "name": "IAG (Iberia / British Airways)", "icon": "✈️"},
    {"symbol": "IBE", "name": "Iberdrola", "icon": "⚡"},
    {"symbol": "IDR", "name": "Indra Sistemas", "icon": "💻"},
    {"symbol": "ITX", "name": "Inditex", "icon": "👗"},
    {"symbol": "LOG", "name": "Logista", "icon": "📦"},
    {"symbol": "MAP", "name": "Mapfre", "icon": "🛡️"},
    {"symbol": "MEL", "name": "Meliá Hotels", "icon": "🏨"},
    {"symbol": "MRL", "name": "Merlin Properties", "icon": "🏢"},
    {"symbol": "MTS", "name": "ArcelorMittal", "icon": "⚙️"},
    {"symbol": "NTGY", "name": "Naturgy", "icon": "🔥"},
    {"symbol": "PHM", "name": "Puig", "icon": "🧴"},
    {"symbol": "RED", "name": "Red Eléctrica (REE)", "icon": "⚡"},
    {"symbol": "REP", "name": "Repsol", "icon": "⛽"},
    {"symbol": "ROVI", "name": "Laboratorios Rovi", "icon": "💉"},
    {"symbol": "SAB", "name": "Banco Sabadell", "icon": "🏦"},
    {"symbol": "SAN", "name": "Banco Santander", "icon": "🏦"},
    {"symbol": "SGRE", "name": "Siemens Gamesa", "icon": "🌬️"},
    {"symbol": "TEF", "name": "Telefónica", "icon": "📱"},
    # ── ETFs ─────────────────────────────────────────────────────────────────
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "icon": "📊"},
    {"symbol": "QQQ", "name": "Invesco Nasdaq 100 ETF", "icon": "📊"},
    {"symbol": "GLD", "name": "SPDR Gold ETF", "icon": "📊"},
    {"symbol": "SLV", "name": "iShares Silver ETF", "icon": "📊"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "icon": "📊"},
    {"symbol": "EEM", "name": "iShares Emerging Markets ETF", "icon": "📊"},
    {"symbol": "EWZ", "name": "iShares MSCI Brazil ETF", "icon": "📊"},
    {"symbol": "VIX", "name": "CBOE VIX (Volatilidad)", "icon": "⚡"},
    {"symbol": "ARKK", "name": "ARK Innovation ETF", "icon": "🚀"},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury ETF", "icon": "📊"},
    {"symbol": "XLF", "name": "Financial Select Sector ETF", "icon": "🏦"},
    {"symbol": "XLE", "name": "Energy Select Sector ETF", "icon": "⚡"},
    # ── Criptodivisas ─────────────────────────────────────────────────────────
    {"symbol": "BTC", "name": "Bitcoin", "icon": "🪙"},
    {"symbol": "ETH", "name": "Ethereum", "icon": "🔷"},
    {"symbol": "XRP", "name": "Ripple", "icon": "💧"},
    {"symbol": "SOL", "name": "Solana", "icon": "☀️"},
    {"symbol": "BNB", "name": "Binance Coin", "icon": "🟡"},
    {"symbol": "ADA", "name": "Cardano", "icon": "🔵"},
    {"symbol": "DOGE", "name": "Dogecoin", "icon": "🐶"},
    {"symbol": "DOT", "name": "Polkadot", "icon": "⚫"},
    {"symbol": "AVAX", "name": "Avalanche", "icon": "🔺"},
    {"symbol": "MATIC", "name": "Polygon", "icon": "🟣"},
    {"symbol": "LINK", "name": "Chainlink", "icon": "🔗"},
    {"symbol": "UNI", "name": "Uniswap", "icon": "🦄"},
    {"symbol": "LTC", "name": "Litecoin", "icon": "🥈"},
    {"symbol": "ATOM", "name": "Cosmos", "icon": "⚛️"},
    {"symbol": "XLM", "name": "Stellar", "icon": "⭐"},
    {"symbol": "ALGO", "name": "Algorand", "icon": "🔷"},
    {"symbol": "FIL", "name": "Filecoin", "icon": "📁"},
    {"symbol": "NEAR", "name": "NEAR Protocol", "icon": "🌐"},
    {"symbol": "ARB", "name": "Arbitrum", "icon": "🔵"},
    {"symbol": "OP", "name": "Optimism", "icon": "🔴"},
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

    # CREATE TABLE IF NOT EXISTS — idempotente, nunca borra datos
    meta.create_all(engine, checkfirst=True)


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
        if not sub or sub["status"] not in ("active", "trial"):
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
                text("INSERT INTO users (email,password_hash,name,language,created_at) VALUES (:email,:pw,:name,:lang,:created_at)"),
                {"email": email, "pw": pw_hash, "name": name, "lang": language, "created_at": now},
            )
            user_id = result.lastrowid
            conn.execute(
                text("INSERT INTO subscriptions (user_id,plan,status,trial_ends_at,created_at,updated_at) VALUES (:uid,:plan,:status,:trial,:now,:now)"),
                {"uid": user_id, "plan": plan, "status": "trial", "trial": trial_end, "now": now},
            )
            conn.commit()
        return User.get_by_id(user_id)
