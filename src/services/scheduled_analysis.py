"""
scheduled_analysis.py — Análisis programado de activos principales.

Cada 8h analiza obligatoriamente BTC, ETH, SOL, BNB y top assets con Claude,
usando datos de precio/volumen/tendencia/funding actuales. Garantiza al menos
1 alerta diaria por activo principal independientemente de noticias.
"""

import logging
import time
import json
import requests
from datetime import datetime, timezone

logger = logging.getLogger("scheduled_analysis")

# Assets that MUST get at least 1 analysis per cycle
PRIORITY_ASSETS = ["BTC", "ETH", "SOL", "BNB"]
SECONDARY_ASSETS = ["ADA", "DOGE", "AVAX", "XRP", "LINK", "DOT", "SUI", "NEAR", "ARB", "OP"]

_BINANCE_SYMBOL_MAP = {"JUPITER": "JUP"}
_NO_BINANCE_SPOT = {"MNT", "AIOZ", "CRO", "OKB", "GT", "KAS"}

SCHEDULED_SYSTEM_PROMPT = """Eres un analista crypto de élite. Se te proporcionan datos técnicos actuales de un activo. Tu trabajo es predecir la dirección del precio en las próximas 24 horas.

CONTEXTO: Este es un análisis programado (no basado en noticias). Debes basarte EXCLUSIVAMENTE en los datos técnicos proporcionados: tendencia, momentum, volumen, RSI, funding rate.

REGLAS:
1. El sistema es binario: si dices UP, el precio DEBE subir ≥2% en algún momento de las próximas 24h
2. Si dices DOWN, DEBE bajar ≥2% en las próximas 24h
3. Si los datos no son claros → confidence < 50 (no se alertará)
4. Busca confluencia: tendencia + momentum + volumen en la misma dirección
5. Un RSI extremo (>75 o <25) con volumen alto ES una señal fuerte

SEÑAL FUERTE (confidence 70-85):
- Tendencia 6h Y 1h en la misma dirección + volumen por encima de la media
- RSI extremo (>78 o <22) con momentum acelerando
- Funding rate extremo (>0.05% o <-0.05%) indicando crowded trade a punto de liquidarse

SEÑAL DÉBIL (confidence < 60):
- Datos mixtos (1h up pero 6h down)
- Volumen bajo (mercado sin interés)
- RSI en zona neutral (35-65)
- Precio consolidando sin dirección clara

CALIBRACIÓN:
- 80-85: Confluencia total (trend + momentum + volume + RSI extremo). Raro.
- 70-79: Buena confluencia, dirección clara
- 55-69: Hay señal pero falta confirmación — NO ALERTAR
- < 55: Sin señal clara — descartar

Responde SOLO con JSON válido."""

SCHEDULED_PROMPT_TEMPLATE = """Análisis técnico programado para {asset}:

DATOS DE MERCADO ACTUALES:
- Precio: ${price:.6g}
- Cambio 1h: {change_1h:+.2f}%
- Cambio 6h: {change_6h:+.2f}%
- Cambio 24h: {change_24h:+.2f}%
- Volumen 24h: ${volume:.0f}
- Volumen vs media: {volume_label}
- RSI(14): {rsi:.0f} ({rsi_label})
- Tendencia 7d: {trend_7d}
- Cambio 7d: {change_7d:+.1f}%
- Funding rate: {funding}

¿Se moverá {asset} ≥2% en una dirección en las próximas 24h?

Responde con JSON exacto:
{{
  "direction": "up|down|neutral",
  "timeframe": "hours",
  "confidence": <entero 25-85>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": ["{asset}"],
  "reasoning": "<UNA frase máx 120 chars EN ESPAÑOL explicando la señal técnica>",
  "verification_window_hours": 24
}}"""


def _binance_sym(asset: str) -> str:
    return _BINANCE_SYMBOL_MAP.get(asset.upper(), asset.upper())


def _get_market_data(asset: str) -> dict | None:
    """Fetches comprehensive market data for an asset from Binance."""
    if asset.upper() in _NO_BINANCE_SPOT:
        return None

    sym = _binance_sym(asset) + "USDT"
    data = {}

    try:
        # 24hr ticker for price + volume + 24h change
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbol": sym},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        t = r.json()
        data["price"] = float(t["lastPrice"])
        data["change_24h"] = float(t["priceChangePercent"])
        data["volume"] = float(t["quoteVolume"])
    except Exception as e:
        logger.debug(f"Failed to get ticker for {asset}: {e}")
        return None

    try:
        # 1h klines for 6h and 1h changes
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": sym, "interval": "1h", "limit": 7},
            timeout=5,
        )
        if r.status_code == 200:
            candles = r.json()
            if len(candles) >= 7:
                open_6h = float(candles[0][1])
                close_now = float(candles[-1][4])
                data["change_6h"] = (close_now - open_6h) / open_6h * 100 if open_6h > 0 else 0
                open_1h = float(candles[-1][1])
                data["change_1h"] = (close_now - open_1h) / open_1h * 100 if open_1h > 0 else 0
    except Exception:
        data.setdefault("change_6h", 0)
        data.setdefault("change_1h", 0)

    try:
        # Daily klines for RSI and 7d trend
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": sym, "interval": "1d", "limit": 15},
            timeout=5,
        )
        if r.status_code == 200:
            candles = r.json()
            closes = [float(c[4]) for c in candles]
            if len(closes) >= 14:
                data["rsi"] = _calc_rsi(closes)
            if len(closes) >= 7:
                data["change_7d"] = (closes[-1] - closes[-7]) / closes[-7] * 100
                data["trend_7d"] = "alcista" if data["change_7d"] > 2 else ("bajista" if data["change_7d"] < -2 else "lateral")
            else:
                data["change_7d"] = 0
                data["trend_7d"] = "lateral"
    except Exception:
        pass

    data.setdefault("rsi", 50)
    data.setdefault("change_6h", 0)
    data.setdefault("change_1h", 0)
    data.setdefault("change_7d", 0)
    data.setdefault("trend_7d", "lateral")

    # Funding rate from futures
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": sym, "limit": 1},
            timeout=5,
        )
        if r.status_code == 200 and r.json():
            data["funding_rate"] = float(r.json()[0]["fundingRate"])
        else:
            data["funding_rate"] = 0
    except Exception:
        data["funding_rate"] = 0

    return data


def _calc_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _get_volume_label(asset: str, volume: float) -> str:
    """Classify volume relative to expected ranges."""
    # Rough 24h volume tiers (in USD)
    if asset in ("BTC",):
        return "alto" if volume > 25_000_000_000 else ("medio" if volume > 15_000_000_000 else "bajo")
    if asset in ("ETH",):
        return "alto" if volume > 10_000_000_000 else ("medio" if volume > 5_000_000_000 else "bajo")
    if asset in ("SOL", "BNB", "XRP", "DOGE"):
        return "alto" if volume > 1_000_000_000 else ("medio" if volume > 500_000_000 else "bajo")
    # Default for mid/small caps
    return "alto" if volume > 200_000_000 else ("medio" if volume > 50_000_000 else "bajo")


def _get_rsi_label(rsi: float) -> str:
    if rsi > 75:
        return "sobrecomprado"
    if rsi > 65:
        return "alto"
    if rsi < 25:
        return "sobrevendido"
    if rsi < 35:
        return "bajo"
    return "neutral"


def run_scheduled_analysis() -> list[dict]:
    """
    Runs scheduled analysis on priority + secondary assets.
    Returns list of events ready to be saved/alerted.
    """
    from src.services.claude_analyzer import _call_claude, _validate_analysis

    logger.info("📅 ANÁLISIS PROGRAMADO — Iniciando análisis de activos principales")

    # Determine which assets to analyze this cycle
    # Priority always, secondary rotated (half each cycle)
    cycle_secondary = SECONDARY_ASSETS[:]
    assets_to_analyze = PRIORITY_ASSETS + cycle_secondary

    events = []
    analyzed = 0

    for asset in assets_to_analyze:
        market_data = _get_market_data(asset)
        if not market_data:
            logger.debug(f"No market data for {asset}, skipping")
            continue

        # Build prompt with real data
        funding_str = f"{market_data['funding_rate']*100:.4f}%" if market_data['funding_rate'] != 0 else "neutral (0%)"
        prompt = SCHEDULED_PROMPT_TEMPLATE.format(
            asset=asset,
            price=market_data["price"],
            change_1h=market_data["change_1h"],
            change_6h=market_data["change_6h"],
            change_24h=market_data["change_24h"],
            volume=market_data["volume"],
            volume_label=_get_volume_label(asset, market_data["volume"]),
            rsi=market_data["rsi"],
            rsi_label=_get_rsi_label(market_data["rsi"]),
            trend_7d=market_data["trend_7d"],
            change_7d=market_data["change_7d"],
            funding=funding_str,
        )

        result = _call_claude(prompt, system_prompt=SCHEDULED_SYSTEM_PROMPT)
        if not result:
            logger.warning(f"Claude returned None for {asset}")
            continue

        validated = _validate_analysis(result)
        analyzed += 1

        confidence = validated.get("confidence", 0)
        direction = validated.get("direction", "neutral")

        # Only generate event if confidence is high enough
        if direction == "neutral" or confidence < 65:
            logger.info(f"   📊 {asset}: {direction} conf={confidence} — descartado (bajo umbral)")
            continue

        # Build event structure compatible with pipeline
        event = {
            "title": f"[Análisis programado] {asset} señal técnica {direction.upper()}",
            "description": validated.get("reasoning", ""),
            "source": "Scheduled Analysis",
            "score": min(85, confidence + 5),
            "suggested_asset": asset,
            "category": "scheduled_technical",
            "_silent": False,
            "analysis": {
                "direction": direction,
                "confidence": confidence,
                "most_affected_assets": [asset],
                "timeframe": "hours",
                "reasoning": validated.get("reasoning", ""),
                "signal_strength": validated.get("signal_strength", "medium"),
                "verification_window_hours": 24,
                "signal_factors": {
                    "type": "scheduled_analysis",
                    "rsi": market_data["rsi"],
                    "change_1h": market_data["change_1h"],
                    "change_6h": market_data["change_6h"],
                    "change_24h": market_data["change_24h"],
                    "volume_label": _get_volume_label(asset, market_data["volume"]),
                    "funding_rate": market_data["funding_rate"],
                },
            },
            "_market_data": market_data,
        }
        events.append(event)
        logger.info(f"   ✅ {asset}: {direction} conf={confidence} — señal generada")

        # Small delay between Claude calls to avoid rate limiting
        time.sleep(0.5)

    logger.info(f"📅 Análisis programado completo: {analyzed} analizados, {len(events)} señales generadas")
    return events
