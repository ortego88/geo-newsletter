"""
Fetcher de precios reales para activos financieros.
- Crypto: CoinGecko free API
- Acciones/Índices/Commodities: yfinance (incluye futuros de materias primas)
- Caché en memoria con TTL de 60 segundos
"""

import time
import logging

logger = logging.getLogger("real_price_fetcher")

# --- Caché en memoria ---
_cache: dict = {}  # {asset: (price, timestamp)}
CACHE_TTL = 60  # segundos

# --- Mapas de símbolo a ID ---
CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "SOL": "solana",
    "ADA": "cardano",
    "BNB": "binancecoin",
    "DOGE": "dogecoin",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ALGO": "algorand",
    "FIL": "filecoin",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
}

# Todos los activos accesibles via yfinance (acciones, índices y futuros de commodities)
YAHOO_TICKERS = {
    # Índices globales
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "S&P500": "^GSPC",
    "INDU": "^DJI",
    "DJI": "^DJI",
    "CCMP": "^IXIC",
    "NASDAQ": "^IXIC",
    "FTSE": "^FTSE",
    "DAX": "^GDAXI",
    "CAC": "^FCHI",
    "IBEX35": "^IBEX",
    "IBEX": "^IBEX",
    "N225": "^N225",
    "NIKKEI": "^N225",
    "HSI": "^HSI",
    # Volatilidad
    "VIX": "^VIX",
    # Commodities via futuros
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    # Bonos del Tesoro USA
    "US10Y": "^TNX",
    "US2Y": "^IRX",
    "BONDS": "^TNX",
    # ETFs
    "GLD": "GLD",
    "SLV": "SLV",
    "SPY": "SPY",
    "QQQ": "QQQ",
    "IWM": "IWM",
    "DIA": "DIA",
    "EEM": "EEM",
    "EWZ": "EWZ",
    "VTI": "VTI",
    "ARKK": "ARKK",
    "TLT": "TLT",
    "XLF": "XLF",
    "XLE": "XLE",
    # ── IBEX 35 — empresas (Bolsa de Madrid, sufijo .MC) ───────────────────
    "ACS": "ACS.MC",
    "ACX": "ACX.MC",
    "AENA": "AENA.MC",
    "ALM": "ALM.MC",
    "AMS": "AMS.MC",
    "ANA": "ANA.MC",
    "BBVA": "BBVA.MC",
    "BKT": "BKT.MC",
    "CABK": "CABK.MC",
    "CLNX": "CLNX.MC",
    "COL": "COL.MC",
    "ELE": "ELE.MC",
    "ENG": "ENG.MC",
    "FDR": "FDR.MC",
    "FER": "FER.MC",
    "GRF": "GRF.MC",
    "IAG": "IAG.MC",
    "IBE": "IBE.MC",
    "IDR": "IDR.MC",
    "ITX": "ITX.MC",
    "LOG": "LOG.MC",
    "MAP": "MAP.MC",
    "MEL": "MEL.MC",
    "MRL": "MRL.MC",
    "MTS": "MTS.MC",
    "NTGY": "NTGY.MC",
    "PHM": "PHM.MC",
    "RED": "RED.MC",
    "REP": "REP.MC",
    "ROVI": "ROVI.MC",
    "SAB": "SAB.MC",
    "SAN": "SAN.MC",
    "SGRE": "SGRE.MC",
    "TEF": "TEF.MC",
}


def _get_cached(asset: str):
    entry = _cache.get(asset)
    if entry:
        price, ts = entry
        if time.time() - ts < CACHE_TTL:
            return price
    return None


def _set_cached(asset: str, price: float):
    _cache[asset] = (price, time.time())


def _fetch_crypto_price(asset: str):
    """Obtiene precio de crypto desde CoinGecko."""
    gecko_id = CRYPTO_IDS.get(asset.upper())
    if not gecko_id:
        return None
    try:
        import requests
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={gecko_id}&vs_currencies=usd"
        )
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        price = data.get(gecko_id, {}).get("usd")
        if price is not None:
            return float(price)
    except Exception as e:
        logger.warning(f"CoinGecko error para {asset}: {e}")
    return None


def _fetch_stock_price(asset: str):
    """Obtiene precio de acción/índice/futuro de commodity desde yfinance."""
    ticker_symbol = YAHOO_TICKERS.get(asset.upper())
    if not ticker_symbol:
        return None
    try:
        import yfinance as yf
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        if price is not None:
            return float(price)
    except Exception as e:
        logger.warning(f"yfinance error para {asset} ({ticker_symbol}): {e}")
    return None


def get_price(asset: str):
    """
    Devuelve el precio actual del activo, o None si no se puede obtener.
    Usa caché de 60 segundos para evitar llamadas excesivas a la API.
    Orden de búsqueda: CRYPTO_IDS → YAHOO_TICKERS → None.
    """
    asset_upper = asset.upper()

    cached = _get_cached(asset_upper)
    if cached is not None:
        return cached

    price = None

    if asset_upper in CRYPTO_IDS:
        price = _fetch_crypto_price(asset_upper)
    elif asset_upper in YAHOO_TICKERS:
        price = _fetch_stock_price(asset_upper)

    if price is not None:
        _set_cached(asset_upper, price)
    return price


class RealPriceFetcher:
    """Clase wrapper para compatibilidad con el resto del sistema."""

    def get_price(self, asset: str):
        return get_price(asset)

    def get_price_context(self, asset: str) -> dict:
        """
        Devuelve contexto histórico de precio para el activo dado.
        Incluye precio actual, medias 7/30 días, cambio %, RSI(14) y tendencia.
        Si falla, devuelve un dict con valores por defecto (sin lanzar excepción).
        """
        default = {
            "current": 0.0,
            "avg_7d": 0.0,
            "avg_30d": 0.0,
            "change_7d_pct": 0.0,
            "change_30d_pct": 0.0,
            "rsi_14": 50.0,
            "trend": "neutral",
        }
        try:
            import yfinance as yf

            asset_upper = asset.upper()
            ticker_symbol = YAHOO_TICKERS.get(asset_upper)
            if not ticker_symbol and asset_upper in CRYPTO_IDS:
                # Use yfinance for crypto with -USD suffix
                ticker_symbol = f"{asset_upper}-USD"
            if not ticker_symbol:
                return default

            hist = yf.Ticker(ticker_symbol).history(period="35d")
            if hist.empty or len(hist) < 2:
                return default

            closes = hist["Close"].dropna().tolist()
            if not closes:
                return default

            current = float(closes[-1])
            avg_7d = float(sum(closes[-7:]) / min(7, len(closes)))
            avg_30d = float(sum(closes[-30:]) / min(30, len(closes)))

            change_7d_pct = round((current - avg_7d) / avg_7d * 100, 2) if avg_7d else 0.0
            change_30d_pct = round((current - avg_30d) / avg_30d * 100, 2) if avg_30d else 0.0

            rsi_14 = self._calc_rsi(closes, period=14)

            if rsi_14 > 55 and change_7d_pct > 0:
                trend = "bullish"
            elif rsi_14 < 45 and change_7d_pct < 0:
                trend = "bearish"
            else:
                trend = "neutral"

            return {
                "current": round(current, 4),
                "avg_7d": round(avg_7d, 4),
                "avg_30d": round(avg_30d, 4),
                "change_7d_pct": change_7d_pct,
                "change_30d_pct": change_30d_pct,
                "rsi_14": rsi_14,
                "trend": trend,
            }
        except Exception as e:
            logger.warning(f"get_price_context error para {asset}: {e}")
            return default

    @staticmethod
    def _calc_rsi(closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d for d in deltas[-period:] if d > 0]
        losses = [-d for d in deltas[-period:] if d < 0]
        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 1)
