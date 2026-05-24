"""
Fuentes de señales rápidas (baja latencia) para el pipeline de análisis.

Binance Volume Anomaly Detector:
  - Usa la API pública de Binance (sin API key)
  - Detecta picos de volumen anómalos en las últimas velas (5m)
  - Un spike de volumen suele preceder un movimiento de precio significativo
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("fast_signals")

# Binance tickers to monitor (USDT pairs for our tracked assets)
_BINANCE_PAIRS = {
    "BTCUSDT": "BTC", "ETHUSDT": "ETH", "XRPUSDT": "XRP",
    "SOLUSDT": "SOL", "BNBUSDT": "BNB", "ADAUSDT": "ADA",
    "DOGEUSDT": "DOGE", "DOTUSDT": "DOT", "AVAXUSDT": "AVAX",
    "MATICUSDT": "MATIC", "LINKUSDT": "LINK", "UNIUSDT": "UNI",
    "LTCUSDT": "LTC", "ATOMUSDT": "ATOM", "NEARUSDT": "NEAR",
    "ARBUSDT": "ARB", "OPUSDT": "OP", "SUIUSDT": "SUI",
    "APTUSDT": "APT", "INJUSDT": "INJ", "FETUSDT": "FET",
    "PEPEUSDT": "PEPE", "SHIBUSDT": "SHIB", "TONUSDT": "TON",
    "AAVEUSDT": "AAVE", "RENDERUSDT": "RENDER",
}

# Volume spike threshold: current candle volume must be this many times
# the average of the previous N candles to be considered anomalous
_VOLUME_SPIKE_MULTIPLIER = 3.0
_LOOKBACK_CANDLES = 12  # 12 candles of 5min = 1 hour of history

# Cache to avoid re-alerting the same spike within a cooldown period
_spike_cache: dict[str, float] = {}  # {asset: last_spike_timestamp}
_SPIKE_COOLDOWN_SECONDS = 1800  # 30 min between spikes for same asset


def fetch_binance_volume_spikes() -> list[dict]:
    """
    Detects abnormal volume spikes on Binance using public klines API.
    Returns list of synthetic "articles" compatible with the pipeline format.
    No API key required — Binance public endpoints are free.
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not available for Binance volume detection")
        return []

    signals = []
    now = time.time()

    for pair, asset in _BINANCE_PAIRS.items():
        # Check cooldown
        last_spike = _spike_cache.get(asset, 0)
        if now - last_spike < _SPIKE_COOLDOWN_SECONDS:
            continue

        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": pair,
                    "interval": "5m",
                    "limit": _LOOKBACK_CANDLES + 1,
                },
                timeout=5,
            )
            if resp.status_code != 200:
                continue

            klines = resp.json()
            if len(klines) < _LOOKBACK_CANDLES + 1:
                continue

            # kline format: [open_time, open, high, low, close, volume, ...]
            volumes = [float(k[5]) for k in klines]
            current_volume = volumes[-1]
            avg_volume = sum(volumes[:-1]) / len(volumes[:-1])

            if avg_volume <= 0:
                continue

            ratio = current_volume / avg_volume

            if ratio >= _VOLUME_SPIKE_MULTIPLIER:
                # Determine direction from price action
                current_close = float(klines[-1][4])
                current_open = float(klines[-1][1])
                prev_close = float(klines[-2][4])

                price_change_pct = ((current_close - prev_close) / prev_close) * 100

                if abs(price_change_pct) < 0.3:
                    continue  # Volume spike without price movement — not actionable yet

                direction = "up" if price_change_pct > 0 else "down"
                direction_es = "alcista" if direction == "up" else "bajista"

                _spike_cache[asset] = now

                signals.append({
                    "title": f"Volume spike detected on {asset}: {ratio:.1f}x average ({direction_es} {price_change_pct:+.2f}%)",
                    "description": (
                        f"{asset}/USDT shows a {ratio:.1f}x volume anomaly in the last 5 minutes "
                        f"with {direction} price movement of {price_change_pct:+.2f}%. "
                        f"Current volume: {current_volume:,.0f} vs avg: {avg_volume:,.0f}. "
                        f"This may indicate institutional activity or a breaking event."
                    ),
                    "url": f"https://www.binance.com/en/trade/{asset}_USDT",
                    "source": "Binance Volume",
                    "sources": ["Binance Volume"],
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "_fast_signal": True,
                    "_volume_ratio": ratio,
                    "_price_change": price_change_pct,
                    "_direction_hint": direction,
                })

                logger.info(
                    f"⚡ Volume spike: {asset} {ratio:.1f}x avg, "
                    f"price {price_change_pct:+.2f}%"
                )

        except Exception as e:
            logger.debug(f"Error checking {pair}: {e}")
            continue

    if signals:
        logger.info(f"⚡ Binance: {len(signals)} volume spikes detected")

    return signals


def fetch_fast_signals() -> list[dict]:
    """
    Main entry point: fetches all fast signal sources and returns combined list.
    Currently: Binance volume anomaly detection (free, no API key).
    """
    signals = []
    signals.extend(fetch_binance_volume_spikes())
    return signals
