"""
Fetcher de precios reales para activos financieros.
- Crypto: Binance (primary) → CoinGecko (fallback) → CoinMarketCap (last resort)
- yfinance eliminated — unreliable for crypto (returns garbage for delisted assets)
- Caché en memoria con TTL de 60 segundos
- Cross-validation: rejects prices deviating >50% from last known price
"""

import time
import logging
import os

logger = logging.getLogger("real_price_fetcher")

# API keys for premium sources
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY", "")

# CoinGecko rate limit tracking
_coingecko_last_429: float = 0
_COINGECKO_BACKOFF_SECONDS = 120  # wait 2 min after a 429

# --- Caché en memoria ---
_cache: dict = {}  # {asset: (price, timestamp)}
CACHE_TTL = 60  # segundos

# --- Mapas de símbolo a ID ---
CRYPTO_IDS = {
    # Top 20
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "SOL": "solana",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "TON": "the-open-network",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "SHIB": "shiba-inu",
    "DOT": "polkadot",
    "SUI": "sui",
    "LTC": "litecoin",
    "HBAR": "hedera-hashgraph",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "NEAR": "near",
    # Layer 2 & Infra
    "ARB": "arbitrum",
    "OP": "optimism",
    "MATIC": "matic-network",
    "ICP": "internet-computer",
    "FIL": "filecoin",
    "IMX": "immutable-x",
    "STX": "blockstack",
    "MNT": "mantle",
    # DeFi
    "AAVE": "aave",
    "MKR": "maker",
    "CRV": "curve-dao-token",
    "LDO": "lido-dao",
    "DYDX": "dydx",
    "SNX": "havven",
    "PENDLE": "pendle",
    "JUPITER": "jupiter-exchange-solana",
    # AI & Data
    "FET": "fetch-ai",
    "RENDER": "render-token",
    "INJ": "injective-protocol",
    "TAO": "bittensor",
    "ONDO": "ondo-finance",
    "AIOZ": "aioz-network",
    # Gaming & Metaverse
    "AXS": "axie-infinity",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "GALA": "gala",
    "ENJ": "enjincoin",
    # New L1s
    "APT": "aptos",
    "SEI": "sei-network",
    "TIA": "celestia",
    "KAS": "kaspa",
    "ALGO": "algorand",
    # Memecoins
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "FLOKI": "floki",
    "BONK": "bonk",
    # Exchange tokens
    "CRO": "crypto-com-chain",
    "OKB": "okb",
    "GT": "gate-token",
    # Otros
    "VET": "vechain",
    "THETA": "theta-token",
    "FTM": "fantom",
    "EOS": "eos",
    "RUNE": "thorchain",
    "GRT": "the-graph",
    # Meta
    "CRYPTO_MARKET": "bitcoin",
}

# Stablecoins — never generate predictions for these
STABLECOIN_BLACKLIST = {"USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP", "FRAX", "PYUSD"}

# No non-crypto assets — scope is crypto only
YAHOO_TICKERS = {}

# Assets not available on Binance spot USDT pair
_NO_BINANCE_SPOT = {"MNT", "AIOZ", "CRO", "OKB", "GT", "KAS"}

# Binance symbol overrides
_BINANCE_SYMBOL_MAP = {
    "JUPITER": "JUP",
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


def _fetch_crypto_price_binance(asset: str):
    """Obtiene precio de crypto desde Binance (primary source — most reliable)."""
    asset_upper = asset.upper()
    if asset_upper in _NO_BINANCE_SPOT:
        return None
    sym = _BINANCE_SYMBOL_MAP.get(asset_upper, asset_upper)
    try:
        import requests
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}USDT"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        price = float(data.get("price", 0))
        if price > 0:
            return price
    except Exception as e:
        logger.debug(f"Binance error para {asset}: {e}")
    return None


def _fetch_crypto_price_coingecko(asset: str):
    """Obtiene precio de crypto desde CoinGecko (fallback)."""
    global _coingecko_last_429
    if time.time() - _coingecko_last_429 < _COINGECKO_BACKOFF_SECONDS:
        return None

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
        if resp.status_code == 429:
            _coingecko_last_429 = time.time()
            logger.warning("CoinGecko rate limited (429) — backing off 2 min")
            return None
        resp.raise_for_status()
        data = resp.json()
        price = data.get(gecko_id, {}).get("usd")
        if price is not None:
            return float(price)
    except Exception as e:
        logger.debug(f"CoinGecko error para {asset}: {e}")
    return None


def _fetch_crypto_price_coinmarketcap(asset: str):
    """Obtiene precio de crypto desde CoinMarketCap (last resort)."""
    if not COINMARKETCAP_API_KEY:
        return None

    asset_upper = asset.upper()
    try:
        import requests
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {
            "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY,
            "Accept": "application/json",
        }
        params = {"symbol": asset_upper, "convert": "USD"}
        resp = requests.get(url, headers=headers, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if data.get("data") and asset_upper in data["data"]:
            price = data["data"][asset_upper].get("quote", {}).get("USD", {}).get("price")
            if price is not None:
                return float(price)
    except Exception as e:
        logger.debug(f"CoinMarketCap error para {asset}: {e}")
    return None


def _cross_validate_price(asset: str, price: float) -> bool:
    """Rejects prices that deviate >50% from last known cached price."""
    if asset not in _cache:
        return True
    old_price, _ = _cache[asset]
    if old_price <= 0:
        return True
    ratio = price / old_price
    if ratio > 2.0 or ratio < 0.5:
        logger.warning(
            f"⚠️  Cross-validation REJECTED price for {asset}: "
            f"${old_price:.6f} → ${price:.6f} (ratio: {ratio:.2f}x, threshold ±50%)"
        )
        return False
    return True


def _fetch_crypto_price(asset: str):
    """
    Obtiene precio de crypto con fallback múltiple.
    Orden: Binance (primary) → CoinGecko → CoinMarketCap
    yfinance eliminated — returns garbage for many assets.
    """
    price = _fetch_crypto_price_binance(asset)
    if price is not None:
        return price

    logger.debug(f"Binance not available for {asset}, trying CoinGecko...")
    price = _fetch_crypto_price_coingecko(asset)
    if price is not None:
        return price

    logger.debug(f"CoinGecko not available for {asset}, trying CoinMarketCap...")
    price = _fetch_crypto_price_coinmarketcap(asset)
    if price is not None:
        logger.info(f"Usando precio de CoinMarketCap para {asset}")
        return price

    logger.warning(f"No se pudo obtener precio para crypto {asset} en ninguna fuente")
    return None


def get_price(asset: str):
    """
    Devuelve el precio actual del activo, o None si no se puede obtener.
    Usa caché de 60 segundos para evitar llamadas excesivas a la API.
    Cross-validates against previous known price (rejects >50% deviation).
    """
    asset_upper = asset.upper()

    cached = _get_cached(asset_upper)
    if cached is not None:
        return cached

    price = None

    if asset_upper in CRYPTO_IDS:
        price = _fetch_crypto_price(asset_upper)

    if price is not None:
        if price <= 0:
            logger.warning(f"⚠️  Precio inválido recibido para {asset_upper}: ${price}")
            return None
        if not _cross_validate_price(asset_upper, price):
            return None
        _set_cached(asset_upper, price)
    return price


class RealPriceFetcher:
    """Clase wrapper para compatibilidad con el resto del sistema."""

    def get_price(self, asset: str):
        return get_price(asset)

    def get_price_context(self, asset: str) -> dict:
        """
        Devuelve contexto histórico de precio usando Binance klines (1d candles).
        Incluye precio actual, medias 7/30 días, cambio %, RSI(14) y tendencia.
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
            import requests

            asset_upper = asset.upper()
            if asset_upper not in CRYPTO_IDS:
                return default

            sym = _BINANCE_SYMBOL_MAP.get(asset_upper, asset_upper)
            if asset_upper in _NO_BINANCE_SPOT:
                return default

            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": f"{sym}USDT", "interval": "1d", "limit": 35},
                timeout=8,
            )
            if resp.status_code != 200:
                return default

            klines = resp.json()
            if len(klines) < 2:
                return default

            closes = [float(k[4]) for k in klines]

            current = closes[-1]
            avg_7d = sum(closes[-7:]) / min(7, len(closes))
            avg_30d = sum(closes[-30:]) / min(30, len(closes))

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

    def get_recent_change(self, asset: str, hours: int = 4) -> float | None:
        """
        Returns the price change % over the last N hours using Binance klines.
        Positive = price went up, Negative = price went down.
        Returns None if data unavailable.
        """
        asset_upper = asset.upper()
        if asset_upper not in CRYPTO_IDS:
            return None
        if asset_upper in _NO_BINANCE_SPOT:
            return None

        sym = _BINANCE_SYMBOL_MAP.get(asset_upper, asset_upper)
        pair = f"{sym}USDT"
        try:
            import requests
            # 1h candles, fetch enough for the requested window
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": pair, "interval": "1h", "limit": hours + 1},
                timeout=5,
            )
            if resp.status_code != 200:
                return None
            klines = resp.json()
            if len(klines) < 2:
                return None
            # First candle open vs last candle close
            open_price = float(klines[0][1])
            close_price = float(klines[-1][4])
            if open_price <= 0:
                return None
            return round((close_price - open_price) / open_price * 100, 2)
        except Exception as e:
            logger.debug(f"get_recent_change error for {asset}: {e}")
            return None

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
