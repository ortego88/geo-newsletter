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

# Mid-caps that scheduled analysis works well for (>50% accuracy historically)
# Large caps (BTC, ETH, SOL, BNB) only included with STRICT threshold — they rarely move 2% without catalyst
# Excluded entirely: DOT (33%), GRT (0%), LINK (42%) — consistently fail
PRIORITY_ASSETS = ["NEAR", "ADA", "OP", "SUI", "ARB", "XRP", "LINK", "AVAX", "DOT"]
SECONDARY_ASSETS = [
    "DOGE", "INJ", "MANA", "ENJ", "AXS", "WIF", "PENDLE", "CRV", "GALA",
    "AAVE", "UNI", "FIL", "ATOM", "RENDER", "FET", "APT", "TIA", "MATIC",
    "SHIB", "LTC", "ICP", "STX", "HBAR",
]

LARGE_CAP_ASSETS = ["BTC", "ETH", "SOL", "BNB"]
LARGE_CAP_MIN_CONFIDENCE = 60

_BINANCE_SYMBOL_MAP = {"JUPITER": "JUP"}
_NO_BINANCE_SPOT = {"MNT", "AIOZ", "CRO", "OKB", "GT", "KAS"}

SCHEDULED_SYSTEM_PROMPT = """Eres un analista crypto de élite. Se te proporcionan datos técnicos y de microestructura de un activo. Tu trabajo es predecir la dirección MÁS PROBABLE del precio en las próximas 24 horas.

UMBRALES DE VALIDACIÓN (el precio debe moverse ESTO en la dirección predicha):
- BTC, ETH: ≥1%
- SOL, BNB, XRP, ADA, DOGE, AVAX, DOT, LINK: ≥1.5%
- Resto de mid/small caps: ≥2%

REGLAS:
1. Elige UP o DOWN solo cuando tengas al menos 2 indicadores alineados.
2. Si los datos son mixtos sin sesgo claro, usa confidence < 55 para indicar baja convicción.
3. NO asumas que "down" es siempre más probable — analiza los datos sin sesgo direccional.
4. El order book (bid/ask ratio) y el open interest son señales de presión compradora/vendedora.
5. Si BTC se mueve fuerte en una dirección, las altcoins suelen seguir (correlación).

CALIBRACIÓN DE CONFIDENCE:
- 75-82: Confluencia fuerte — tendencia + momentum + microestructura alineados.
- 68-74: Señal clara, 2-3 indicadores coinciden. Alta probabilidad.
- 62-67: Sesgo identificable con alguna ambigüedad. Predicción razonable.
- 55-61: Señal débil, solo 1 indicador sugiere dirección.
- 50-54: Sin señal real — lateralidad. Evita predecir con alta convicción aquí.

INDICADORES CLAVE:
- RSI >70 o <30: sobrecompra/sobreventa — posible reversión
- 1h y 6h en misma dirección: confluencia temporal (+8 confianza)
- Order book >60% bids: presión compradora. >60% asks: presión vendedora.
- Funding rate positivo extremo (>0.05%): longs sobrepalancados → probable caída
- Funding rate negativo extremo (<-0.03%): shorts sobrepalancados → probable subida
- Volumen alto + dirección clara: el movimiento tiene fuerza
- BTC y activo moviéndose en misma dirección: confirmación del sector

Responde SOLO con JSON válido."""

SCHEDULED_PROMPT_TEMPLATE = """Análisis técnico programado para {asset}:

DATOS DE MERCADO:
- Precio: ${price:.6g}
- Cambio 1h: {change_1h:+.2f}%
- Cambio 6h: {change_6h:+.2f}%
- Cambio 24h: {change_24h:+.2f}%
- Volumen 24h: ${volume:.0f} ({volume_label})
- RSI(14): {rsi:.0f} ({rsi_label})
- Tendencia 7d: {trend_7d} ({change_7d:+.1f}%)

MICROESTRUCTURA:
- Funding rate: {funding} (últimas 3 lecturas: {funding_history})
- Order book: {bid_ratio}% bids / {ask_ratio}% asks (top 20 niveles)
- Open interest: {open_interest}
- BTC contexto: {btc_change_1h:+.2f}% (1h), {btc_change_6h:+.2f}% (6h)

Pregunta: ¿Cuál es la dirección MÁS PROBABLE de {asset} en las próximas 24h?

Si no hay al menos 2 indicadores claros alineados, responde con confidence < 55.

Responde con JSON exacto:
{{
  "direction": "up|down",
  "timeframe": "hours",
  "confidence": <entero 50-82>,
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
            params={"symbol": sym, "limit": 3},
            timeout=5,
        )
        if r.status_code == 200 and r.json():
            rates = r.json()
            data["funding_rate"] = float(rates[0]["fundingRate"])
            data["funding_history"] = [round(float(x["fundingRate"]) * 100, 4) for x in rates]
        else:
            data["funding_rate"] = 0
            data["funding_history"] = []
    except Exception:
        data["funding_rate"] = 0
        data["funding_history"] = []

    # Open interest change (futures)
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": sym},
            timeout=5,
        )
        if r.status_code == 200:
            data["open_interest"] = float(r.json().get("openInterest", 0))
        else:
            data["open_interest"] = 0
    except Exception:
        data["open_interest"] = 0

    # Order book imbalance (top 20 levels)
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/depth",
            params={"symbol": sym, "limit": 20},
            timeout=5,
        )
        if r.status_code == 200:
            book = r.json()
            bid_vol = sum(float(b[1]) * float(b[0]) for b in book.get("bids", []))
            ask_vol = sum(float(a[1]) * float(a[0]) for a in book.get("asks", []))
            total = bid_vol + ask_vol
            data["bid_ratio"] = round(bid_vol / total * 100, 1) if total > 0 else 50
            data["ask_ratio"] = round(ask_vol / total * 100, 1) if total > 0 else 50
        else:
            data["bid_ratio"] = 50
            data["ask_ratio"] = 50
    except Exception:
        data["bid_ratio"] = 50
        data["ask_ratio"] = 50

    # BTC context (if not BTC itself)
    if asset.upper() != "BTC":
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1h", "limit": 7},
                timeout=5,
            )
            if r.status_code == 200:
                btc_candles = r.json()
                if len(btc_candles) >= 7:
                    btc_open_6h = float(btc_candles[0][1])
                    btc_close = float(btc_candles[-1][4])
                    data["btc_change_6h"] = round((btc_close - btc_open_6h) / btc_open_6h * 100, 2)
                    btc_open_1h = float(btc_candles[-1][1])
                    data["btc_change_1h"] = round((btc_close - btc_open_1h) / btc_open_1h * 100, 2)
        except Exception:
            pass
    data.setdefault("btc_change_6h", 0)
    data.setdefault("btc_change_1h", 0)

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
    # Priority + secondary (mid-caps with good accuracy) + large caps (strict threshold)
    assets_to_analyze = PRIORITY_ASSETS + SECONDARY_ASSETS + LARGE_CAP_ASSETS

    events = []
    analyzed = 0

    for asset in assets_to_analyze:
        market_data = _get_market_data(asset)
        if not market_data:
            logger.debug(f"No market data for {asset}, skipping")
            continue

        # Build prompt with real data
        funding_str = f"{market_data['funding_rate']*100:.4f}%" if market_data['funding_rate'] != 0 else "neutral (0%)"
        funding_hist = market_data.get("funding_history", [])
        funding_hist_str = ", ".join(f"{x:.4f}%" for x in funding_hist) if funding_hist else "N/A"
        oi_val = market_data.get("open_interest", 0)
        oi_str = f"{oi_val:,.0f}" if oi_val > 0 else "N/A"
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
            funding_history=funding_hist_str,
            bid_ratio=market_data.get("bid_ratio", 50),
            ask_ratio=market_data.get("ask_ratio", 50),
            open_interest=oi_str,
            btc_change_1h=market_data.get("btc_change_1h", 0),
            btc_change_6h=market_data.get("btc_change_6h", 0),
        )

        result = _call_claude(prompt, system_prompt=SCHEDULED_SYSTEM_PROMPT)
        if not result:
            logger.warning(f"Claude returned None for {asset}")
            continue

        validated = _validate_analysis(result)
        analyzed += 1

        confidence = validated.get("confidence", 0)
        direction = validated.get("direction", "neutral")

        # Dynamic threshold: large caps need much higher confidence (they rarely move 2%)
        if asset in LARGE_CAP_ASSETS:
            min_conf = LARGE_CAP_MIN_CONFIDENCE
        else:
            min_conf = 60

        if direction == "neutral" or confidence < min_conf:
            logger.info(f"   📊 {asset}: {direction} conf={confidence} — descartado (umbral={min_conf})")
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
