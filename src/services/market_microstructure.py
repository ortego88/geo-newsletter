"""
market_microstructure.py — Detects market structure signals BEFORE news breaks.

Signals checked every pipeline cycle:
1. Funding rates (Binance) — extreme positive/negative = overleverage → reversal likely
2. Order book imbalance (Binance) — bid/ask wall ratio → directional pressure
3. Liquidation cascades (Binance) — ongoing forced selling/buying
4. Open interest divergence — price moves without OI confirmation = weak move

These signals precede price moves by 15-120 minutes, before any news outlet publishes.
All data from Binance public API — no auth required.
"""

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger("microstructure")

_BINANCE_BASE = "https://fapi.binance.com"  # Futures API
_BINANCE_SPOT = "https://api.binance.com/api/v3"

_cache: dict = {}
_cache_time: dict = {}
_CACHE_TTL = 180  # 3 min cache to avoid rate limits

# 30-min cooldown per asset+signal_type to prevent duplicate alerts
# from the same event appearing in consecutive pipeline cycles
_signal_cooldowns: dict[str, float] = {}
_SIGNAL_COOLDOWN_SECS = 30 * 60


def _signal_on_cooldown(asset: str, signal_type: str) -> bool:
    key = f"{asset}_{signal_type}"
    last = _signal_cooldowns.get(key, 0)
    return (time.time() - last) < _SIGNAL_COOLDOWN_SECS


def _signal_set_cooldown(asset: str, signal_type: str):
    _signal_cooldowns[f"{asset}_{signal_type}"] = time.time()


def _cached(key: str, fn, ttl: int = _CACHE_TTL):
    now = time.time()
    if key in _cache and now - _cache_time.get(key, 0) < ttl:
        return _cache[key]
    try:
        result = fn()
        _cache[key] = result
        _cache_time[key] = now
        return result
    except Exception as e:
        logger.debug(f"Cache miss for {key}: {e}")
        return None


def get_funding_rate(symbol: str = "BTCUSDT") -> dict | None:
    """
    Returns current funding rate for a perpetual futures contract.
    Extreme positive (>0.1%) = market overleveraged long → likely correction
    Extreme negative (<-0.05%) = market overleveraged short → likely squeeze
    Normal range: -0.01% to 0.03%
    """
    def fetch():
        resp = requests.get(
            f"{_BINANCE_BASE}/fapi/v1/fundingRate",
            params={"symbol": symbol, "limit": 1},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        rate = float(data[0]["fundingRate"]) * 100  # as percentage
        return {
            "symbol": symbol,
            "rate_pct": round(rate, 4),
            "extreme_long": rate > 0.08,    # longs paying >0.08% per 8h = overleverage
            "extreme_short": rate < -0.04,  # shorts paying >0.04% per 8h = overleverage
            "timestamp": data[0].get("fundingTime"),
        }
    return _cached(f"funding_{symbol}", fetch)


def get_funding_rates_all() -> list[dict]:
    """Gets funding rates for all 65 tracked assets that have futures on Binance."""
    FUTURES_SYMBOLS = [
        # Top caps
        "BTCUSDT","ETHUSDT","XRPUSDT","SOLUSDT","BNBUSDT","ADAUSDT","DOGEUSDT",
        "TRXUSDT","TONUSDT","LINKUSDT","AVAXUSDT","SHIBUSDT","DOTUSDT","SUIUSDT",
        "LTCUSDT","HBARUSDT","UNIUSDT","ATOMUSDT","XLMUSDT","NEARUSDT",
        # Mid caps
        "ARBUSDT","OPUSDT","ICPUSDT","FILUSDT","IMXUSDT","STXUSDT",
        # DeFi/AI
        "AAVEUSDT","MKRUSDT","CRVUSDT","LDOUSDT","DYDXUSDT","SNXUSDT",
        "PENDLEUSDT","ONDOUSDT","FETUSDT","RENDERUSDT","INJUSDT","TAOUSDT",
        # Gaming
        "AXSUSDT","SANDUSDT","MANAUSDT","GALAUSDT","ENJUSDT",
        # Memecoins
        "PEPEUSDT","WIFUSDT","FLOKIUSDT","BONKUSDT",
        # Others
        "VETUSDT","THETAUSDT","FTMUSDT","RUNEUSDT","GRTUSDT","KASUSDT",
    ]
    def fetch():
        resp = requests.get(
            f"{_BINANCE_BASE}/fapi/v1/premiumIndex",
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for item in data:
            sym = item.get("symbol", "")
            if sym not in FUTURES_SYMBOLS:
                continue
            rate = float(item.get("lastFundingRate", 0)) * 100
            asset = sym.replace("USDT", "")
            results.append({
                "symbol": sym,
                "asset": asset,
                "rate_pct": round(rate, 4),
                "mark_price": float(item.get("markPrice", 0)),
                "extreme_long": rate > 0.08,
                "extreme_short": rate < -0.04,
                "very_extreme_long": rate > 0.15,
                "very_extreme_short": rate < -0.08,
            })
        return results

    result = _cached("funding_all", fetch, ttl=300)
    return result or []


def get_order_book_imbalance(symbol: str = "BTCUSDT", depth: int = 20) -> dict | None:
    """
    Measures bid vs ask pressure in the order book top N levels.
    bid_ratio > 0.65 = strong buying pressure
    bid_ratio < 0.35 = strong selling pressure
    """
    def fetch():
        resp = requests.get(
            f"{_BINANCE_SPOT}/depth",
            params={"symbol": symbol, "limit": depth},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        bid_volume = sum(float(b[1]) * float(b[0]) for b in data.get("bids", []))
        ask_volume = sum(float(a[1]) * float(a[0]) for a in data.get("asks", []))
        total = bid_volume + ask_volume
        if total == 0:
            return None
        bid_ratio = bid_volume / total
        return {
            "symbol": symbol,
            "bid_ratio": round(bid_ratio, 3),
            "ask_ratio": round(1 - bid_ratio, 3),
            "strong_buy_pressure": bid_ratio > 0.65,
            "strong_sell_pressure": bid_ratio < 0.35,
            "bid_volume_usd": round(bid_volume),
            "ask_volume_usd": round(ask_volume),
        }
    return _cached(f"orderbook_{symbol}", fetch, ttl=60)


def get_liquidations_24h(symbol: str = "BTCUSDT") -> dict | None:
    """
    Gets recent forced liquidations from Binance futures.
    Large liquidations in one direction = cascade risk continues.
    """
    def fetch():
        resp = requests.get(
            f"{_BINANCE_BASE}/fapi/v1/allForceOrders",
            params={"symbol": symbol, "limit": 100},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return {"long_liquidations_usd": 0, "short_liquidations_usd": 0}

        long_liq = sum(float(o["origQty"]) * float(o["price"]) for o in data if o.get("side") == "SELL")
        short_liq = sum(float(o["origQty"]) * float(o["price"]) for o in data if o.get("side") == "BUY")

        return {
            "symbol": symbol,
            "long_liquidations_usd": round(long_liq),
            "short_liquidations_usd": round(short_liq),
            "cascade_down": long_liq > 5_000_000,   # $5M+ long liquidations = cascade risk
            "cascade_up": short_liq > 5_000_000,    # $5M+ short liquidations = squeeze risk
        }
    return _cached(f"liq_{symbol}", fetch, ttl=120)


def get_open_interest_change(symbol: str = "BTCUSDT") -> dict | None:
    """
    Compares current OI vs OI 1h ago.
    Price up + OI down = weak rally, likely to reverse
    Price down + OI down = capitulation, potential bounce
    Price down + OI up = new shorts entering, trend continuation
    Price up + OI up = strong uptrend with new longs entering
    """
    def fetch():
        # Current OI
        resp = requests.get(
            f"{_BINANCE_BASE}/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        current_oi = float(resp.json().get("openInterest", 0))

        # OI history (last 2 data points)
        resp2 = requests.get(
            f"{_BINANCE_BASE}/futures/data/openInterestHist",
            params={"symbol": symbol, "period": "1h", "limit": 3},
            timeout=8,
        )
        if resp2.status_code != 200:
            return {"current_oi": current_oi}

        hist = resp2.json()
        if len(hist) < 2:
            return {"current_oi": current_oi}

        prev_oi = float(hist[-2]["sumOpenInterest"])
        if prev_oi == 0:
            return {"current_oi": current_oi}

        oi_change_pct = (current_oi - prev_oi) / prev_oi * 100

        return {
            "symbol": symbol,
            "current_oi": round(current_oi),
            "oi_change_1h_pct": round(oi_change_pct, 2),
            "oi_increasing": oi_change_pct > 1,
            "oi_decreasing": oi_change_pct < -1,
        }
    return _cached(f"oi_{symbol}", fetch, ttl=300)


def get_large_trades(symbol: str = "BTCUSDT", min_usd: float = 200_000) -> dict | None:
    """
    Detects large individual trades in the last ~500 trades on Binance spot.
    A single trade >$500K is unusual and indicates institutional activity.
    Multiple large sells in a short window = distribution signal.

    Binance spot shows real buying/selling pressure (not just derivatives).
    isBuyerMaker=True means the buyer was the passive side → SELL order hit the book.
    """
    def fetch():
        resp = requests.get(
            f"{_BINANCE_SPOT}/trades",
            params={"symbol": symbol, "limit": 500},
            timeout=8,
        )
        if resp.status_code != 200:
            return None

        trades = resp.json()
        now_ms = time.time() * 1000
        window_ms = 3 * 60 * 1000  # last 3 minutes (scanner runs every 3 min)

        recent = [t for t in trades if now_ms - t["time"] <= window_ms]
        if not recent:
            return None

        large_sells = []
        large_buys = []

        for t in recent:
            usd = float(t["qty"]) * float(t["price"])
            if usd < min_usd:
                continue
            # isBuyerMaker=True → seller initiated (aggressive sell)
            if t["isBuyerMaker"]:
                large_sells.append(usd)
            else:
                large_buys.append(usd)

        total_sell_usd = sum(large_sells)
        total_buy_usd = sum(large_buys)
        sell_count = len(large_sells)
        buy_count = len(large_buys)

        return {
            "symbol": symbol,
            "window_minutes": 5,
            "large_sell_usd": round(total_sell_usd),
            "large_buy_usd": round(total_buy_usd),
            "large_sell_count": sell_count,
            "large_buy_count": buy_count,
            "sell_dominance": total_sell_usd > total_buy_usd * 2.5 and total_sell_usd > 2_000_000,
            "buy_dominance": total_buy_usd > total_sell_usd * 2.5 and total_buy_usd > 2_000_000,
            "whale_dump": sell_count >= 5 and total_sell_usd > 3_000_000,
            "whale_accumulation": buy_count >= 5 and total_buy_usd > 3_000_000,
        }
    return _cached(f"large_trades_{symbol}", fetch, ttl=60)


def _get_btc_1h_change() -> float:
    """Returns BTC price change in the last 1 hour. Used to filter signals in rebound."""
    def fetch():
        resp = requests.get(
            f"{_BINANCE_SPOT}/klines",
            params={"symbol": "BTCUSDT", "interval": "1h", "limit": 2},
            timeout=8,
        )
        if resp.status_code != 200:
            return 0.0
        candles = resp.json()
        if len(candles) < 2:
            return 0.0
        prev_close = float(candles[0][4])
        last_close = float(candles[1][4])
        if prev_close <= 0:
            return 0.0
        return (last_close - prev_close) / prev_close * 100
    result = _cached("btc_1h_change", fetch, ttl=120)
    return result if result is not None else 0.0


def scan_microstructure_signals() -> list[dict]:
    """
    Main function: scans all microstructure signals and returns
    actionable alerts with high confidence.

    Returns list of signal dicts ready to inject into the prediction pipeline.
    """
    signals = []

    # Check market context: if BTC rebounded >1.5% in last 1h, suppress DOWN signals
    # This prevents sending DOWN alerts when the market already reversed
    btc_1h = _get_btc_1h_change()
    market_rebounding = btc_1h > 1.5
    if market_rebounding:
        logger.info(f"🔬 Market rebounding (BTC +{btc_1h:.1f}% 1h) — suppressing DOWN microstructure signals")

    # 1. Funding rates scan
    funding_data = get_funding_rates_all()
    for f in funding_data:
        asset = f["asset"]

        if f["very_extreme_long"]:
            if market_rebounding:
                continue
            confidence = 82
            reasoning = (
                f"Funding rate extremo positivo ({f['rate_pct']}%/8h) en {asset}. "
                f"El mercado está masivamente apalancado en largo. "
                f"Históricamente este nivel precede correcciones bruscas en 1-6h."
            )
            signals.append(_build_signal(asset, "down", confidence, reasoning, "funding_extreme_long", f["rate_pct"]))

        elif f["very_extreme_short"]:
            # <-0.08%: market massively overleveraged short → short squeeze likely
            confidence = 78
            reasoning = (
                f"Funding rate extremo negativo ({f['rate_pct']}%/8h) en {asset}. "
                f"Sobreapalancamiento en corto. Riesgo elevado de short squeeze en 1-6h."
            )
            signals.append(_build_signal(asset, "up", confidence, reasoning, "funding_extreme_short", f["rate_pct"]))

    # 2. Order book + large trades scan for all 65 assets
    # min_trade: minimum single trade size to count
    # whale_threshold: total volume needed to trigger signal
    LARGE_TRADE_ASSETS = [
        # Tier 1 — major caps (high liquidity, large trades)
        ("BTCUSDT",   "BTC",   200_000, 3_000_000),
        ("ETHUSDT",   "ETH",   200_000, 3_000_000),
        ("BNBUSDT",   "BNB",    50_000,   800_000),
        # Tier 2 — large altcoins
        ("SOLUSDT",   "SOL",    50_000,   500_000),
        ("XRPUSDT",   "XRP",    50_000,   500_000),
        ("ADAUSDT",   "ADA",    30_000,   300_000),
        ("TRXUSDT",   "TRX",    30_000,   300_000),
        ("TONUSDT",   "TON",    30_000,   300_000),
        ("LINKUSDT",  "LINK",   30_000,   300_000),
        ("AVAXUSDT",  "AVAX",   30_000,   300_000),
        ("DOTUSDT",   "DOT",    30_000,   300_000),
        ("LTCUSDT",   "LTC",    30_000,   300_000),
        ("SUIUSDT",   "SUI",    20_000,   200_000),
        ("NEARUSDT",  "NEAR",   20_000,   200_000),
        ("ATOMUSDT",  "ATOM",   20_000,   200_000),
        ("XLMUSDT",   "XLM",    20_000,   200_000),
        ("UNIUSDT",   "UNI",    20_000,   200_000),
        ("ARBUSDT",   "ARB",    20_000,   200_000),
        ("OPUSDT",    "OP",     20_000,   200_000),
        ("ICPUSDT",   "ICP",    20_000,   200_000),
        ("FILUSDT",   "FIL",    20_000,   200_000),
        ("HBARUSDT",  "HBAR",   20_000,   200_000),
        ("IMXUSDT",   "IMX",    20_000,   200_000),
        ("STXUSDT",   "STX",    20_000,   200_000),
        # Tier 3 — DeFi / AI
        ("AAVEUSDT",  "AAVE",   20_000,   200_000),
        ("CRVUSDT",   "CRV",    15_000,   150_000),
        ("LDOUSDT",   "LDO",    15_000,   150_000),
        ("DYDXUSDT",  "DYDX",   15_000,   150_000),
        ("SNXUSDT",   "SNX",    15_000,   150_000),
        ("PENDLEUSDT","PENDLE", 15_000,   150_000),
        ("FETUSDT",   "FET",    15_000,   150_000),
        ("RENDERUSDT","RENDER", 15_000,   150_000),
        ("INJUSDT",   "INJ",    15_000,   150_000),
        ("TAOUSDT",   "TAO",    15_000,   150_000),
        ("ONDOUSDT",  "ONDO",   15_000,   150_000),
        # Tier 4 — Gaming
        ("AXSUSDT",   "AXS",    10_000,   100_000),
        ("SANDUSDT",  "SAND",   10_000,   100_000),
        ("MANAUSDT",  "MANA",   10_000,   100_000),
        ("GALAUSDT",  "GALA",   10_000,   100_000),
        ("ENJUSDT",   "ENJ",    10_000,   100_000),
        # Tier 5 — Memecoins & small caps
        ("DOGEUSDT",  "DOGE",   20_000,   200_000),
        ("SHIBUSDT",  "SHIB",   10_000,   100_000),
        ("PEPEUSDT",  "PEPE",   10_000,   100_000),
        ("WIFUSDT",   "WIF",    10_000,   100_000),
        ("FLOKIUSDT", "FLOKI",  10_000,   100_000),
        ("BONKUSDT",  "BONK",   10_000,   100_000),
        # Others
        ("VETUSDT",   "VET",    10_000,   100_000),
        ("THETAUSDT", "THETA",  10_000,   100_000),
        ("FTMUSDT",   "FTM",    10_000,   100_000),
        ("RUNEUSDT",  "RUNE",   15_000,   150_000),
        ("GRTUSDT",   "GRT",    10_000,   100_000),
        ("KASUSDT",   "KAS",    10_000,   100_000),
    ]

    for sym, asset, min_trade, whale_threshold in LARGE_TRADE_ASSETS:
        # Order book imbalance (only for BTC and ETH — meaningful depth)
        if sym in ("BTCUSDT", "ETHUSDT"):
            ob = get_order_book_imbalance(sym)
            if ob and ob["strong_sell_pressure"] and ob["ask_volume_usd"] > 2_000_000:
                confidence = 72
                reasoning = (
                    f"Presión vendedora fuerte en el libro de órdenes de {asset}. "
                    f"Ratio bid/ask: {ob['bid_ratio']}/{ob['ask_ratio']}. "
                    f"Volumen en ventas: ${ob['ask_volume_usd']:,}."
                )
                signals.append(_build_signal(asset, "down", confidence, reasoning, "orderbook_sell_wall", ob["bid_ratio"]))

        # Large trades — real-time activity
        lt = get_large_trades(sym, min_usd=min_trade)
        if not lt:
            continue

        if lt["whale_dump"] or (lt["large_sell_count"] >= 5 and lt["large_sell_usd"] > whale_threshold):
            if market_rebounding:
                continue
            confidence = 78
            reasoning = (
                f"Ventas institucionales detectadas en {asset}: "
                f"{lt['large_sell_count']} ventas grandes (${lt['large_sell_usd']:,} total) "
                f"en los últimos 5 minutos. Distribución activa — presión bajista inminente."
            )
            signals.append(_build_signal(asset, "down", confidence, reasoning, "whale_dump", lt["large_sell_usd"]))

        elif not market_rebounding and (lt["sell_dominance"] or (lt["large_sell_usd"] > lt["large_buy_usd"] * 2.5 and lt["large_sell_usd"] > whale_threshold * 0.5)):
            confidence = 75  # raised from 70 — requires stronger conviction
            reasoning = (
                f"Dominio vendedor en {asset}: "
                f"${lt['large_sell_usd']:,} en ventas vs ${lt['large_buy_usd']:,} en compras (5 min). "
                f"Presión bajista sostenida."
            )
            signals.append(_build_signal(asset, "down", confidence, reasoning, "large_sell_dominance", lt["large_sell_usd"]))

        elif lt["whale_accumulation"] or (lt["large_buy_count"] >= 5 and lt["large_buy_usd"] > whale_threshold):
            confidence = 75
            reasoning = (
                f"Acumulación institucional en {asset}: "
                f"{lt['large_buy_count']} compras grandes (${lt['large_buy_usd']:,} total) "
                f"en los últimos 5 minutos. Demanda institucional activa."
            )
            signals.append(_build_signal(asset, "up", confidence, reasoning, "whale_accumulation", lt["large_buy_usd"]))

    # 3. Liquidation cascades
    for sym, asset in [("BTCUSDT","BTC"), ("ETHUSDT","ETH"), ("SOLUSDT","SOL")]:
        liq = get_liquidations_24h(sym)
        if not liq:
            continue
        if liq.get("cascade_down") and liq["long_liquidations_usd"] > 10_000_000:
            confidence = 75
            reasoning = (
                f"Cascade de liquidaciones en largo en {asset}: "
                f"${liq['long_liquidations_usd']:,} liquidados recientemente. "
                f"Las cascadas de liquidación tienden a continuar hasta agotar las posiciones apalancadas."
            )
            signals.append(_build_signal(asset, "down", confidence, reasoning, "liquidation_cascade", liq["long_liquidations_usd"]))

    # Filter None (cooldown) and UP signals below 80% confidence
    signals = [s for s in signals if s is not None]
    signals = [s for s in signals if s["analysis"]["direction"] == "down" or s["analysis"]["confidence"] >= 80]

    logger.info(f"🔬 Microstructure scan: {len(signals)} signals found")
    return signals


def _build_signal(asset: str, direction: str, confidence: int, reasoning: str, source: str, value) -> dict | None:
    """Returns None if this asset+source is on cooldown (same event, next cycle)."""
    if _signal_on_cooldown(asset, source):
        return None
    _signal_set_cooldown(asset, source)
    return {
        "title": f"Señal de microestructura: {asset} — {direction.upper()} (funding/orderbook)",
        "description": reasoning,
        "source": f"microstructure_{source}",
        "sources": ["Market Microstructure"],
        "suggested_asset": asset,
        "matched_assets": [asset],
        "score": min(85, 60 + confidence // 5),
        "category": "CRYPTO",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "analysis": {
            "direction": direction,
            "confidence": confidence,
            "most_affected_assets": [asset],
            "timeframe": "hours",
            "reasoning": reasoning,
            "signal_strength": "high" if confidence >= 80 else "medium",
            "verification_window_hours": 6,
        },
        "_change_pct": 0,
        "_micro_value": value,
    }
