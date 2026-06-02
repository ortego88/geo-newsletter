"""
price_signals.py — Genera alertas automáticas cuando el precio de un activo
cae o sube un porcentaje significativo en las últimas horas.

Complementa al pipeline de noticias: detecta movimientos de mercado grandes
que pueden no tener una noticia asociada inmediatamente.

Se ejecuta cada ciclo (10 min). Cooldown de 4 horas por activo para no spammear.
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("price_signals")

THRESHOLD_PCT = 2.0
COOLDOWN_SECONDS = 4 * 3600
TOP_ASSETS = ["BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "DOGE", "AVAX", "DOT", "LINK"]

_cooldowns: dict[str, float] = {}


def _is_on_cooldown(asset: str) -> bool:
    last = _cooldowns.get(asset, 0)
    return (time.time() - last) < COOLDOWN_SECONDS


def _set_cooldown(asset: str):
    _cooldowns[asset] = time.time()


def _get_24h_change(asset: str) -> float | None:
    """Gets 24h % change for a crypto asset via CoinGecko."""
    try:
        from src.services.real_price_fetcher import CRYPTO_IDS
        import requests

        coin_id = CRYPTO_IDS.get(asset.upper())
        if not coin_id:
            return None

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json().get(coin_id, {})
        return data.get("usd_24h_change")
    except Exception as e:
        logger.debug(f"Error fetching 24h change for {asset}: {e}")
        return None


def check_price_signals() -> list[dict]:
    """
    Checks top assets for significant price movements (>= THRESHOLD_PCT).
    Returns a list of synthetic events that can be fed into the alert pipeline.
    """
    signals = []

    for asset in TOP_ASSETS:
        if _is_on_cooldown(asset):
            continue

        change = _get_24h_change(asset)
        if change is None:
            continue

        if abs(change) < THRESHOLD_PCT:
            continue

        from src.services.real_price_fetcher import get_price
        current_price = get_price(asset)

        if change <= -THRESHOLD_PCT:
            direction = "down"
            title = f"{asset} cae un {abs(change):.1f}% en 24h — señal de corrección activa"
            reasoning = f"{asset} pierde {abs(change):.1f}% en las últimas 24h con momentum bajista"
        else:
            direction = "up"
            title = f"{asset} sube un {change:.1f}% en 24h — rally en curso"
            reasoning = f"{asset} gana {change:.1f}% en las últimas 24h con momentum alcista"

        confidence = min(85, 70 + int(abs(change) - THRESHOLD_PCT) * 3)
        score = min(90, 70 + int(abs(change)))

        event = {
            "title": title,
            "score": score,
            "source": "price_signal",
            "analysis": {
                "direction": direction,
                "confidence": confidence,
                "most_affected_assets": [asset],
                "timeframe": "hours",
                "reasoning": reasoning,
                "signal_strength": "high" if abs(change) >= 4.0 else "medium",
                "verification_window_hours": 4,
            },
        }
        signals.append(event)
        _set_cooldown(asset)
        logger.info(f"📊 Price signal: {asset} {change:+.1f}% → {direction} (conf={confidence})")

    return signals
