"""
Modelos de base de datos para el sistema de suscripciones.
Usa SQLite via sqlite3 directamente (sin ORM para mantener consistencia con el proyecto).
"""
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

DB_PATH = os.getenv("APP_DB_PATH", "data/app.db")

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
    # Índices
    {"symbol": "SPX", "name": "S&P 500", "icon": "📈"},
    {"symbol": "NASDAQ", "name": "Nasdaq 100", "icon": "💻"},
    {"symbol": "DAX", "name": "DAX 40", "icon": "🇩🇪"},
    {"symbol": "IBEX35", "name": "IBEX 35", "icon": "🇪🇸"},
    {"symbol": "FTSE", "name": "FTSE 100", "icon": "🇬🇧"},
    # Commodities
    {"symbol": "WTI", "name": "WTI Oil", "icon": "🛢️"},
    {"symbol": "BRENT", "name": "Brent Oil", "icon": "⚫"},
    {"symbol": "GOLD", "name": "Oro", "icon": "🥇"},
    {"symbol": "SILVER", "name": "Plata", "icon": "🥈"},
    {"symbol": "NATURAL_GAS", "name": "Gas Natural", "icon": "🔥"},
    {"symbol": "COPPER", "name": "Cobre", "icon": "🟤"},
    {"symbol": "WHEAT", "name": "Trigo", "icon": "🌾"},
    {"symbol": "CORN", "name": "Maíz", "icon": "🌽"},
    # Crypto
    {"symbol": "BTC", "name": "Bitcoin", "icon": "🪙"},
    {"symbol": "ETH", "name": "Ethereum", "icon": "🔷"},
    {"symbol": "XRP", "name": "Ripple", "icon": "💧"},
    {"symbol": "SOL", "name": "Solana", "icon": "☀️"},
    {"symbol": "ADA", "name": "Cardano", "icon": "🔵"},
    {"symbol": "DOGE", "name": "Dogecoin", "icon": "🐶"},
    # ETFs
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "icon": "📊"},
    {"symbol": "QQQ", "name": "Invesco Nasdaq 100 ETF", "icon": "📊"},
    {"symbol": "GLD", "name": "SPDR Gold ETF", "icon": "📊"},
    {"symbol": "SLV", "name": "iShares Silver ETF", "icon": "📊"},
    {"symbol": "IWM", "name": "iShares Russell 2000 ETF", "icon": "📊"},
    {"symbol": "DIA", "name": "SPDR Dow Jones ETF", "icon": "📊"},
    # Acciones
    {"symbol": "NVDA", "name": "NVIDIA", "icon": "🖥️"},
    {"symbol": "AAPL", "name": "Apple", "icon": "🍎"},
    {"symbol": "MSFT", "name": "Microsoft", "icon": "🪟"},
    {"symbol": "TSLA", "name": "Tesla", "icon": "🚗"},
    {"symbol": "AMZN", "name": "Amazon", "icon": "📦"},
    {"symbol": "META", "name": "Meta", "icon": "🌐"},
    {"symbol": "GOOGL", "name": "Google", "icon": "🔍"},
    {"symbol": "JPM", "name": "JPMorgan", "icon": "🏦"},
    {"symbol": "XOM", "name": "ExxonMobil", "icon": "⛽"},
    # Bonos
    {"symbol": "US10Y", "name": "Bono Tesoro 10Y", "icon": "📊"},
]


def get_conn():
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            telegram_chat_id TEXT,
            language TEXT DEFAULT 'es',
            created_at TEXT DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            plan TEXT NOT NULL DEFAULT 'basic',
            billing_cycle TEXT NOT NULL DEFAULT 'monthly',
            status TEXT NOT NULL DEFAULT 'trial',
            trial_ends_at TEXT,
            current_period_end TEXT,
            stripe_subscription_id TEXT,
            stripe_customer_id TEXT,
            selected_assets TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            stripe_payment_method_id TEXT,
            card_last4 TEXT,
            card_brand TEXT,
            card_exp_month INTEGER,
            card_exp_year INTEGER,
            is_default INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            asset TEXT,
            direction TEXT,
            score INTEGER,
            sent_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


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
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (self.id,)
        )
        row = c.fetchone()
        conn.close()
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
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT id,email,password_hash,name,telegram_chat_id,language,created_at,is_active "
            "FROM users WHERE id=?",
            (user_id,)
        )
        row = c.fetchone()
        conn.close()
        return User(row) if row else None

    @staticmethod
    def get_by_email(email):
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT id,email,password_hash,name,telegram_chat_id,language,created_at,is_active "
            "FROM users WHERE email=?",
            (email,)
        )
        row = c.fetchone()
        conn.close()
        return User(row) if row else None

    @staticmethod
    def create(email, password, name, language='es', plan='basic'):
        if plan not in ('basic', 'premium', 'pro'):
            plan = 'basic'
        conn = get_conn()
        c = conn.cursor()
        pw_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (email,password_hash,name,language) VALUES (?,?,?,?)",
            (email, pw_hash, name, language)
        )
        user_id = c.lastrowid
        # Create trial subscription
        trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        c.execute(
            "INSERT INTO subscriptions (user_id,plan,status,trial_ends_at) VALUES (?,?,?,?)",
            (user_id, plan, "trial", trial_end)
        )
        conn.commit()
        conn.close()
        return User.get_by_id(user_id)
