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

THRESHOLD_PCT = 2.5       # minimum move to generate any signal
ALERT_MAX_PCT = 5.0       # moves above this are sent silently (too late to act)
COOLDOWN_PRICE_MOVE_PCT = 5.0  # re-alert only when price moves 5% from last alert

# All tracked crypto assets — rotated in batches to avoid API rate limits
ALL_ASSETS = [
    # Tier 1: Top coins (checked every cycle)
    "BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    # Tier 2: Mid caps (rotated)
    "SHIB", "TON", "TRX", "LTC", "HBAR", "UNI", "ATOM", "XLM", "NEAR",
    "ARB", "OP", "MATIC", "SUI", "ICP", "FIL", "IMX", "STX", "MNT",
    # Tier 3: DeFi, AI, Gaming (rotated)
    "AAVE", "MKR", "CRV", "LDO", "DYDX", "SNX", "PENDLE", "JUPITER",
    "FET", "RENDER", "INJ", "TAO", "ONDO", "AIOZ",
    "AXS", "SAND", "MANA", "GALA", "ENJ",
    # Tier 4: Memecoins & others (rotated)
    "PEPE", "WIF", "FLOKI", "BONK",
    "CRO", "OKB", "GT", "VET", "THETA", "FTM", "EOS", "RUNE", "GRT", "KAS",
]

_cycle_index = 0

# Stores the price at which we last alerted for each asset
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


def _is_on_cooldown(asset: str, current_price: float = 0) -> bool:
    """Re-alert only if price moved >5% from last alert. No time-based blocking."""
    last_price = _last_alert_price.get(asset, 0)
    if last_price <= 0:
        return False  # Never alerted → go ahead
    if current_price <= 0:
        return True   # Can't verify → be conservative
    move_pct = abs((current_price - last_price) / last_price) * 100
    return move_pct < COOLDOWN_PRICE_MOVE_PCT


def _set_cooldown(asset: str, price: float = 0):
    if price > 0:
        _last_alert_price[asset] = price
    _save_cooldowns()


_batch_cache: dict[str, float] = {}   # asset → 24h change pct
_price_cache: dict[str, float] = {}   # asset → current price USD
_batch_cache_time: float = 0


def _refresh_batch_cache(assets: list[str]):
    """Fetch 24h changes for all assets. Uses Binance first (no rate limit), CoinGecko as fallback."""
    global _batch_cache, _price_cache, _batch_cache_time
    import time as _time
    if _time.time() - _batch_cache_time < 180:  # 3 min cache — Binance has no rate limit
        return

    import requests

    # --- Primary source: Binance (no rate limit, all USDT pairs) ---
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            timeout=15,
        )
        if resp.status_code == 200:
            _batch_cache = {}
            _price_cache = {}
            for t in resp.json():
                sym = t.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                asset = sym.replace("USDT", "")
                if asset in ALL_ASSETS:
                    chg = float(t.get("priceChangePercent", 0))
                    price = float(t.get("lastPrice", 0))
                    _batch_cache[asset] = chg
                    if price > 0:
                        _price_cache[asset] = price
            _batch_cache_time = _time.time()
            logger.info(f"📊 Price cache refreshed via Binance: {len(_batch_cache)} assets")
            return
    except Exception as e:
        logger.warning(f"Binance batch failed: {e}, falling back to CoinGecko")

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
        change = _get_24h_change(asset)
        if change is None:
            continue
        if abs(change) < THRESHOLD_PCT:
            continue

        # Get current price to check price-based cooldown
        current_price = _price_cache.get(asset.upper(), 0)
        if _is_on_cooldown(asset, current_price):
            continue

        if change <= -THRESHOLD_PCT:
            title = f"{asset} cae un {abs(change):.1f}% en las últimas 24 horas"
            description = (
                f"{asset} ha perdido un {abs(change):.1f}% en las últimas 24 horas. "
                f"Este movimiento puede indicar una corrección en curso o "
                f"una reacción a eventos de mercado aún no reflejados en noticias."
            )
        else:
            title = f"{asset} sube un {change:.1f}% en las últimas 24 horas"
            description = (
                f"{asset} ha ganado un {change:.1f}% en las últimas 24 horas. "
                f"Este movimiento puede indicar un rally en curso o "
                f"una reacción a catalizadores positivos."
            )

        score = min(85, 65 + int(abs(change)))
        # Early signal (2.5-5%): alertable — movement just started, user can still act
        # Late signal (>5%): silent — too late to enter, only for model calibration
        is_early = abs(change) <= ALERT_MAX_PCT
        signal_type = "early_move" if is_early else "late_move"

        event = {
            "title": title,
            "description": description,
            "source": f"price_signal_{signal_type}",
            "sources": ["Price Monitor"],
            "suggested_asset": asset,
            "matched_assets": [asset],
            "score": score,
            "category": "CRYPTO",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "_change_pct": change,
            "_silent": not is_early,  # only early moves are sent to users
        }
        signals.append(event)
        _set_cooldown(asset, current_price)
        logger.info(f"📊 Price signal [{signal_type}]: {asset} {change:+.1f}% @ ${current_price}")

    return signals
