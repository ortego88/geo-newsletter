"""
Configuración de mercados y ventanas de verificación por tipo de activo.

Define:
  - Listas de tickers por categoría (crypto, IBEX35, ETFs)
  - Ventanas de verificación por tipo de activo
  - Funciones para horario de mercado (IBEX35 y ETFs NYSE)
  - Cálculo del momento exacto de verificación de una predicción
"""
from datetime import datetime, timedelta

import pytz

# ── Zonas horarias ────────────────────────────────────────────────────────────
MADRID_TZ = pytz.timezone("Europe/Madrid")
NEW_YORK_TZ = pytz.timezone("America/New_York")

# ── Horarios de mercado ───────────────────────────────────────────────────────
IBEX35_OPEN_HOUR = 9       # 09:00 hora Madrid
IBEX35_CLOSE_HOUR = 17    # 17:30 hora Madrid
IBEX35_CLOSE_MINUTE = 30

NYSE_OPEN_HOUR = 9         # 09:30 hora Nueva York
NYSE_OPEN_MINUTE = 30
NYSE_CLOSE_HOUR = 16       # 16:00 hora Nueva York

# ── Ventanas de verificación (en horas) ───────────────────────────────────────
VERIFICATION_WINDOWS: dict[str, int] = {
    "crypto": 6,    # mercado 24/7, 6h captura movimiento real
    "ibex35": 4,    # 4 horas de mercado ABIERTO
    "etf": 6,       # mercado USA 13:30-22:00 UTC
    "default": 6,   # por defecto
}

# ── Clasificación de activos ──────────────────────────────────────────────────
CRYPTO_TICKERS = {
    "BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOGE", "DOT",
    "AVAX", "MATIC", "LINK", "UNI", "LTC", "ATOM", "XLM",
    "ALGO", "FIL", "NEAR", "ARB", "OP",
}

IBEX35_TICKERS = {
    "ACS", "ACX", "AENA", "ALM", "AMS", "ANA", "BBVA", "BKT",
    "CABK", "CLNX", "COL", "ELE", "ENG", "FDR", "FER", "GRF",
    "IAG", "IBE", "IDR", "ITX", "LOG", "MAP", "MEL", "MRL",
    "MTS", "NTGY", "PHM", "RED", "REP", "ROVI", "SAB", "SAN",
    "SGRE", "TEF", "IBEX", "IBEX35",
}

ETF_TICKERS = {
    "SPY", "QQQ", "GLD", "SLV", "IWM", "EWZ", "EEM", "VIX",
    "ARKK", "TLT", "XLF", "XLE",
}


# ── Funciones de consulta ─────────────────────────────────────────────────────

def get_verification_window(ticker: str) -> int:
    """Retorna las horas de verificación según el tipo de activo."""
    if ticker in CRYPTO_TICKERS:
        return VERIFICATION_WINDOWS["crypto"]
    if ticker in IBEX35_TICKERS:
        return VERIFICATION_WINDOWS["ibex35"]
    if ticker in ETF_TICKERS:
        return VERIFICATION_WINDOWS["etf"]
    return VERIFICATION_WINDOWS["default"]


def is_market_open(ticker: str, check_time: datetime | None = None) -> bool:
    """
    Comprueba si el mercado está abierto para un ticker dado.

    Returns:
        True si el mercado está abierto, False si está cerrado.
    """
    if check_time is None:
        check_time = datetime.utcnow().replace(tzinfo=pytz.utc)
    elif check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=pytz.utc)

    # Crypto: siempre abierto
    if ticker in CRYPTO_TICKERS:
        return True

    # IBEX 35: Lunes-Viernes 09:00-17:30 hora Madrid
    if ticker in IBEX35_TICKERS:
        madrid_time = check_time.astimezone(MADRID_TZ)
        if madrid_time.weekday() >= 5:  # sábado=5, domingo=6
            return False
        market_open = madrid_time.replace(hour=IBEX35_OPEN_HOUR, minute=0, second=0, microsecond=0)
        market_close = madrid_time.replace(hour=IBEX35_CLOSE_HOUR, minute=IBEX35_CLOSE_MINUTE, second=0, microsecond=0)
        return market_open <= madrid_time <= market_close

    # ETFs (NYSE): Lunes-Viernes 09:30-16:00 hora Nueva York
    if ticker in ETF_TICKERS:
        ny_time = check_time.astimezone(NEW_YORK_TZ)
        if ny_time.weekday() >= 5:
            return False
        market_open = ny_time.replace(hour=NYSE_OPEN_HOUR, minute=NYSE_OPEN_MINUTE, second=0, microsecond=0)
        market_close = ny_time.replace(hour=NYSE_CLOSE_HOUR, minute=0, second=0, microsecond=0)
        return market_open <= ny_time <= market_close

    # Por defecto: asumir abierto
    return True


def get_next_market_open(ticker: str, from_time: datetime | None = None) -> datetime:
    """
    Calcula cuándo abre el próximo mercado para un ticker.
    Útil para predicciones de IBEX/ETF hechas fuera de horario.

    Returns:
        datetime del próximo momento de apertura de mercado (en UTC).
    """
    if from_time is None:
        from_time = datetime.utcnow().replace(tzinfo=pytz.utc)
    elif from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=pytz.utc)

    if ticker in CRYPTO_TICKERS:
        return from_time  # siempre abierto

    if ticker in IBEX35_TICKERS:
        madrid_time = from_time.astimezone(MADRID_TZ)
        candidate = madrid_time.replace(hour=IBEX35_OPEN_HOUR, minute=0, second=0, microsecond=0)
        # Avanzar al siguiente día hábil si ya pasó la apertura o es fin de semana
        while candidate <= madrid_time or candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=IBEX35_OPEN_HOUR, minute=0, second=0, microsecond=0)
        return candidate.astimezone(pytz.utc)

    if ticker in ETF_TICKERS:
        ny_time = from_time.astimezone(NEW_YORK_TZ)
        candidate = ny_time.replace(hour=NYSE_OPEN_HOUR, minute=NYSE_OPEN_MINUTE, second=0, microsecond=0)
        while candidate <= ny_time or candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=NYSE_OPEN_HOUR, minute=NYSE_OPEN_MINUTE, second=0, microsecond=0)
        return candidate.astimezone(pytz.utc)

    return from_time


def calculate_verification_time(ticker: str, news_time: datetime) -> datetime:
    """
    Calcula el momento exacto en que se debe verificar una predicción.

    Para IBEX35/ETFs: respeta el horario de mercado.
    Para Crypto: simplemente news_time + N horas.

    Args:
        ticker: símbolo del activo.
        news_time: datetime cuando se creó la predicción (UTC).

    Returns:
        datetime cuando verificar (UTC, timezone-aware).
    """
    hours_needed = get_verification_window(ticker)

    # Asegurar timezone-aware
    if news_time.tzinfo is None:
        news_time_utc = news_time.replace(tzinfo=pytz.utc)
    else:
        news_time_utc = news_time.astimezone(pytz.utc)

    # Crypto: 24/7, calcular directamente
    if ticker in CRYPTO_TICKERS:
        return news_time_utc + timedelta(hours=hours_needed)

    # IBEX35 / ETFs: respetar horario de mercado
    if is_market_open(ticker, news_time_utc):
        # Mercado abierto en el momento de la noticia → añadir horas directamente
        verify_time = news_time_utc + timedelta(hours=hours_needed)
        # Si la verificación cae fuera de horario, mover al siguiente día hábil
        if not is_market_open(ticker, verify_time):
            next_open = get_next_market_open(ticker, verify_time)
            return next_open + timedelta(hours=1)  # 1h después de apertura
        return verify_time
    else:
        # Mercado cerrado → verificar N horas después de la próxima apertura
        next_open = get_next_market_open(ticker, news_time_utc)
        return next_open + timedelta(hours=hours_needed)
