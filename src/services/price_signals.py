"""
price_signals.py — Genera eventos sintéticos cuando el precio de un activo
se mueve significativamente en las últimas 24h.

Estos eventos se pasan por Claude para análisis (como cualquier otra noticia),
NO generan predicciones directamente. Complementan las fuentes RSS detectando
movimientos grandes que pueden no tener noticia asociada.

Se ejecuta cada ciclo (10 min). Cooldown de 4 horas por activo para no spammear.
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("price_signals")

THRESHOLD_PCT = 3.0       # minimum move to generate any signal (increased from 2.5% to reduce noise)
ALERT_MAX_PCT = 5.0       # moves above this are sent silently (too late to act)
COOLDOWN_PRICE_MOVE_PCT = 5.0  # re-alert only when price moves 5% from last alert

# Temporarily excluded assets with 0% accuracy (as of June 15, 2026)
# Re-evaluate after prompt improvements — Jun 22, 2026
EXCLUDED_LOW_ACCURACY = {"PEPE", "XRP", "ATOM", "LDO", "SNX"}

# All tracked crypto assets — rotated in batches to avoid API rate limits
ALL_ASSETS = [
    # Tier 1: Top coins (checked every cycle) — keeping BTC/ETH despite low accuracy for learning
    "BTC", "ETH", "SOL", "BNB", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    # Tier 2: Mid caps (rotated) — XRP, ATOM excluded temporarily
    "SHIB", "TON", "TRX", "LTC", "HBAR", "UNI", "XLM", "NEAR",
    "ARB", "OP", "MATIC", "SUI", "ICP", "FIL", "IMX", "STX", "MNT",
    # Tier 3: DeFi, AI, Gaming (rotated) — LDO, SNX excluded temporarily
    "AAVE", "MKR", "CRV", "DYDX", "PENDLE", "JUPITER",
    "FET", "RENDER", "INJ", "TAO", "ONDO", "AIOZ",
    "AXS", "SAND", "MANA", "GALA", "ENJ",
    # Tier 4: Memecoins & others (rotated) — PEPE excluded temporarily
    "WIF", "FLOKI", "BONK",
    "CRO", "OKB", "GT", "VET", "THETA", "FTM", "EOS", "RUNE", "GRT", "KAS",
]

_cycle_index = 0

# Stores last alert price per asset+direction: key = "ASSET_up" or "ASSET_down"
# UP alert does NOT block a DOWN alert on the same asset — they are independent
_last_alert_price: dict[str, float] = {}
_COOLDOWN_FILE = "/tmp/price_signal_cooldowns.json"


def _load_cooldowns():
    global _last_alert_price
    try:
        import json
        with open(_COOLDOWN_FILE) as f:
            _last_alert_price = json.load(f)
    except (FileNotFoundError, Exception):
        _last_alert_price = {}


def _save_cooldowns():
    import json
    try:
        with open(_COOLDOWN_FILE, "w") as f:
            json.dump(_last_alert_price, f)
    except Exception:
        pass


_load_cooldowns()


def _cooldown_key(asset: str, direction: str) -> str:
    return f"{asset.upper()}_{direction}"


def _is_on_cooldown(asset: str, current_price: float = 0, direction: str = "") -> bool:
    """Per-direction cooldown: UP alert doesn't block a DOWN alert on same asset."""
    key = _cooldown_key(asset, direction) if direction else asset.upper()
    last_price = _last_alert_price.get(key, 0)
    if last_price <= 0:
        return False
    if current_price <= 0:
        return True
    move_pct = abs((current_price - last_price) / last_price) * 100
    return move_pct < COOLDOWN_PRICE_MOVE_PCT


def _set_cooldown(asset: str, price: float = 0, direction: str = ""):
    key = _cooldown_key(asset, direction) if direction else asset.upper()
    if price > 0:
        _last_alert_price[key] = price
    _save_cooldowns()


# Binance symbol overrides: assets with different Binance tickers
_BINANCE_SYMBOL_MAP = {
    "JUPITER": "JUP",
}

# Assets not available on Binance spot USDT — excluded from price signals
_NO_BINANCE_SPOT = {"MNT", "AIOZ", "CRO", "OKB", "GT", "KAS"}

def _binance_sym(asset: str) -> str:
    """Returns the correct Binance base symbol for an asset."""
    return _BINANCE_SYMBOL_MAP.get(asset.upper(), asset.upper())

_batch_cache: dict[str, float] = {}    # asset → 4h change pct
_change_24h_cache: dict[str, float] = {}  # asset → 24h change pct (for context/learning)
_price_cache: dict[str, float] = {}    # asset → current price USD
_batch_cache_time: float = 0

# Use 4h window: detects early momentum, avoids alerting on moves that already happened
_KLINE_INTERVAL = "6h"  # Changed from 4h to reduce noise and improve signal quality
_KLINE_LIMIT = 2  # previous candle + current candle = 4h change


def _refresh_batch_cache(assets: list[str]):
    """Fetch 4h price changes for all assets using Binance klines. No rate limit."""
    global _batch_cache, _price_cache, _batch_cache_time
    import time as _time
    if _time.time() - _batch_cache_time < 180:
        return

    import requests, json as _json

    # Fetch current price AND 24h change from ticker (single call, used for context)
    # Use _binance_sym to handle assets with different Binance tickers (e.g. JUPITER→JUP)
    global _change_24h_cache
    _sym_to_asset = {_binance_sym(a) + "USDT": a for a in ALL_ASSETS}
    valid_syms = [s for s in _sym_to_asset.keys()]
    try:
        price_resp = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbols": _json.dumps(valid_syms)},
            timeout=10,
        )
        if price_resp.status_code == 200:
            for t in price_resp.json():
                sym = t["symbol"]
                a = _sym_to_asset.get(sym, sym.replace("USDT", ""))
                p = float(t.get("lastPrice", 0))
                c24 = float(t.get("priceChangePercent", 0))
                if p > 0.000001:
                    _price_cache[a] = p
                _change_24h_cache[a] = c24
    except Exception as e:
        logger.warning(f"Price/24h fetch failed: {e}")

    # Fetch 6h klines for each asset to get recent momentum
    _batch_cache = {}
    success = 0
    for asset in ALL_ASSETS:
        if asset.upper() in _NO_BINANCE_SPOT:
            continue  # no Binance spot pair — skip to avoid fallback data errors
        try:
            binance_sym = _binance_sym(asset) + "USDT"
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": binance_sym, "interval": _KLINE_INTERVAL, "limit": _KLINE_LIMIT},
                timeout=5,
            )
            if r.status_code != 200:
                continue
            candles = r.json()
            if len(candles) < 2:
                continue
            open_price = float(candles[0][1])   # open of previous candle
            close_price = float(candles[-1][4])  # close of current candle
            if open_price > 0:
                chg = (close_price - open_price) / open_price * 100
                _batch_cache[asset] = chg
                success += 1
        except Exception:
            continue

    _batch_cache_time = _time.time()
    logger.info(f"📊 Price cache refreshed (6h klines): {success}/{len(ALL_ASSETS)} assets")

    # --- Fallback: CoinGecko ---
    try:
        from src.services.real_price_fetcher import CRYPTO_IDS

        coin_ids = []
        id_to_asset = {}
        for a in assets:
            cid = CRYPTO_IDS.get(a.upper())
            if cid:
                coin_ids.append(cid)
                id_to_asset[cid] = a.upper()

        ids_str = ",".join(coin_ids)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=usd&include_24hr_change=true"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"CoinGecko batch failed: {resp.status_code}")
            return

        data = resp.json()
        _batch_cache = {}
        _price_cache = {}
        for cid, values in data.items():
            asset = id_to_asset.get(cid)
            if asset:
                if "usd_24h_change" in values:
                    _batch_cache[asset] = values["usd_24h_change"]
                if "usd" in values and values["usd"]:
                    _price_cache[asset] = float(values["usd"])

        _batch_cache_time = _time.time()
        logger.info(f"📊 Price cache refreshed via CoinGecko: {len(_batch_cache)} assets")
    except Exception as e:
        logger.warning(f"Error refreshing price batch: {e}")


def _get_24h_change(asset: str) -> float | None:
    """Gets 24h % change from the batch cache."""
    return _batch_cache.get(asset.upper())


def _get_current_batch() -> list[str]:
    """Returns the current batch of assets to check this cycle.
    Tier 1 (top 10) is checked every cycle. Others rotate in batches of 15."""
    global _cycle_index
    tier1 = ALL_ASSETS[:10]
    rest = ALL_ASSETS[10:]
    batch_size = 15
    start = (_cycle_index * batch_size) % max(len(rest), 1)
    batch = rest[start:start + batch_size]
    _cycle_index += 1
    return tier1 + batch


def check_price_signals() -> list[dict]:
    """
    Checks assets for significant price movements (>= THRESHOLD_PCT).
    All assets fetched in one batch API call, then filtered.
    Returns synthetic events for Claude analysis.
    """
    signals = []
    _refresh_batch_cache(ALL_ASSETS)
    assets_to_check = _get_current_batch()
    logger.info(f"📊 Price signals: checking {len(assets_to_check)} assets ({len(_batch_cache)} in cache)")

    for asset in assets_to_check:
        if asset.upper() in _NO_BINANCE_SPOT:
            continue  # excluded — no reliable Binance data
        if asset.upper() in EXCLUDED_LOW_ACCURACY:
            continue  # temporarily excluded — 0% accuracy as of Jun 15, 2026
        change = _get_24h_change(asset)
        if change is None:
            continue
        if abs(change) < THRESHOLD_PCT:
            continue

        # Get current price to check price-based cooldown
        current_price = _price_cache.get(asset.upper(), 0)
        direction = "down" if change < 0 else "up"
        if _is_on_cooldown(asset, current_price, direction):
            continue

        if change <= -THRESHOLD_PCT:
            title = f"{asset} cae un {abs(change):.1f}% en las últimas 6 horas"
            description = (
                f"{asset} ha perdido un {abs(change):.1f}% en las últimas 6 horas. "
                f"Momentum bajista reciente — movimiento en curso, no histórico."
            )
        else:
            title = f"{asset} sube un {change:.1f}% en las últimas 6 horas"
            description = (
                f"{asset} ha ganado un {change:.1f}% en las últimas 6 horas. "
                f"Momentum alcista reciente — movimiento en curso, no histórico."
            )

        # 24h context for learning — does trend alignment improve accuracy?
        change_24h = _change_24h_cache.get(asset.upper(), 0)
        trend_aligned = (change < 0 and change_24h < 0) or (change > 0 and change_24h > 0)

        score = min(85, 65 + int(abs(change)))
        is_down = change < 0
        is_early = abs(change) <= ALERT_MAX_PCT
        # Fixed: alert both UP and DOWN early moves (2.5-5%), not just DOWN
        is_alertable = is_early
        signal_type = "early_move" if is_early else "late_move"

        event = {
            "title": title,
            "description": (
                f"{description} "
                f"Tendencia 24h: {change_24h:+.1f}% "
                f"({'alineada' if trend_aligned else 'contraria'} al movimiento actual)."
            ),
            "source": f"Price Monitor ({'alerta temprana' if is_alertable else 'calibración silenciosa'})",
            "sources": ["Price Monitor"],
            "suggested_asset": asset,
            "matched_assets": [asset],
            "score": score,
            "category": "CRYPTO",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "_change_pct": change,
            "_change_24h": change_24h,
            "_trend_aligned": trend_aligned,
            "_silent": not is_alertable,
        }
        signals.append(event)
        _set_cooldown(asset, current_price, direction)
        logger.info(
            f"📊 Price signal [{signal_type}]: {asset} {change:+.1f}% (6h) "
            f"/ {change_24h:+.1f}% (24h) {'✓aligned' if trend_aligned else '✗contra'}"
        )

    return signals
