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

THRESHOLD_PCT = 2.5
COOLDOWN_SECONDS = 8 * 3600  # 8h cooldown per asset — prevents same asset spamming twice a day

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

_cooldowns: dict[str, float] = {}
_COOLDOWN_FILE = "/tmp/price_signal_cooldowns.json"


def _load_cooldowns():
    global _cooldowns
    try:
        import json
        with open(_COOLDOWN_FILE) as f:
            raw = json.load(f)
        now = time.time()
        _cooldowns = {k: v for k, v in raw.items() if now - v < COOLDOWN_SECONDS}
    except (FileNotFoundError, Exception):
        _cooldowns = {}


def _save_cooldowns():
    import json
    now = time.time()
    active = {k: v for k, v in _cooldowns.items() if now - v < COOLDOWN_SECONDS}
    try:
        with open(_COOLDOWN_FILE, "w") as f:
            json.dump(active, f)
    except Exception:
        pass


_load_cooldowns()


def _is_on_cooldown(asset: str) -> bool:
    last = _cooldowns.get(asset, 0)
    return (time.time() - last) < COOLDOWN_SECONDS


def _set_cooldown(asset: str):
    _cooldowns[asset] = time.time()
    _save_cooldowns()


_batch_cache: dict[str, float] = {}
_batch_cache_time: float = 0


def _refresh_batch_cache(assets: list[str]):
    """Fetch 24h changes for all assets in one CoinGecko API call."""
    global _batch_cache, _batch_cache_time
    import time as _time
    if _time.time() - _batch_cache_time < 300:
        return

    try:
        from src.services.real_price_fetcher import CRYPTO_IDS
        import requests

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
        for cid, values in data.items():
            asset = id_to_asset.get(cid)
            if asset and "usd_24h_change" in values:
                _batch_cache[asset] = values["usd_24h_change"]

        _batch_cache_time = _time.time()
        logger.info(f"📊 Price cache refreshed: {len(_batch_cache)} assets")
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
        if _is_on_cooldown(asset):
            continue

        change = _get_24h_change(asset)
        if change is None:
            continue

        if abs(change) < THRESHOLD_PCT:
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

        event = {
            "title": title,
            "description": description,
            "source": "price_signal",
            "sources": ["Price Monitor"],
            "suggested_asset": asset,
            "matched_assets": [asset],
            "score": score,
            "category": "CRYPTO",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "_change_pct": change,
        }
        signals.append(event)
        _set_cooldown(asset)
        logger.info(f"📊 Price signal: {asset} {change:+.1f}% (score={score})")

    return signals
