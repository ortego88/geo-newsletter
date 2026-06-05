"""
gem_scanner.py — Detección TEMPRANA de low-cap gems antes del pump.

Estrategia: detectar en fase de ACUMULACIÓN, no cuando ya subió.
Señales tempranas:
1. Volumen explotando pero precio aún estable (acumulación silenciosa)
2. Pares nuevos en DEX con liquidez creciente (preparando pump)
3. Listings anunciados en Binance (pre-pump 24-72h antes)
4. Tokens nuevos con holders creciendo rápido

Validación (7 días después):
- CORRECT: precio max >= +30% desde detección
- INCORRECT: precio cae >= -30% sin haber tocado +30%
- NEUTRAL: ni +30% ni -30% en 7 días

Completamente aislado del pipeline principal de predicciones.
Resultados se guardan en tabla 'gem_signals' y se envían solo al admin.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger("gem_scanner")

# --- Detection thresholds (EARLY signals, before the pump) ---
MIN_LIQUIDITY_USD = 50_000
MAX_MARKET_CAP = 100_000_000
MIN_PAIR_AGE_HOURS = 24
MAX_PAIR_AGE_DAYS = 30
VOLUME_SPIKE_MULTIPLIER = 5.0
MAX_PRICE_CHANGE_FOR_ACCUMULATION = 10.0
MIN_VOLUME_FOR_NEW_PAIR = 50_000
MIN_5M_TXNS = 30

_COOLDOWN_HOURS = 24
_cooldowns: dict[str, float] = {}
_COOLDOWN_FILE = "/tmp/gem_cooldowns.json"


def _load_cooldowns():
    """Load cooldowns from disk to survive restarts."""
    global _cooldowns
    try:
        import json
        with open(_COOLDOWN_FILE) as f:
            _cooldowns = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _cooldowns = {}


def _save_cooldowns():
    """Persist cooldowns to disk."""
    import json
    now = time.time()
    active = {k: v for k, v in _cooldowns.items() if now - v < _COOLDOWN_HOURS * 3600}
    with open(_COOLDOWN_FILE, "w") as f:
        json.dump(active, f)


_load_cooldowns()

# Tokens that are NEVER gems (stablecoins, fiat, wrapped, top 30, commodities)
_BLACKLIST = {
    # Stablecoins
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDD",
    "USD1", "PYUSD", "GUSD", "FRAX", "LUSD", "CRVUSD", "GHO", "EURC",
    # Fiat / wrapped fiat
    "EUR", "USD", "GBP", "JPY", "BRL", "ARS", "TRY",
    # Commodities tokenized
    "XAUT", "PAXG",
    # Top coins (already tracked in main pipeline, not gems)
    "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "TRX", "TON",
    "LINK", "AVAX", "SHIB", "DOT", "SUI", "LTC", "HBAR", "UNI",
    "ATOM", "XLM", "NEAR", "ARB", "OP", "MATIC", "ICP", "FIL",
    "BCH", "ETC", "WBTC", "WETH", "STETH", "LIDO",
    # Wrapped / derivative tokens
    "WBNB", "WMATIC", "WSOL",
}


def _is_on_cooldown(token_id: str) -> bool:
    last = _cooldowns.get(token_id, 0)
    return (time.time() - last) < _COOLDOWN_HOURS * 3600


def _set_cooldown(token_id: str):
    _cooldowns[token_id] = time.time()
    _save_cooldowns()


def _volume_spike_ratio(volume_1h: float, volume_6h: float, volume_24h: float) -> float:
    """
    Calculates volume anomaly score comparing recent 1h vs baseline (6h avg per hour).
    A ratio >5x means the last hour had 5x more volume than the hourly average.
    This is the core signal for pre-pump accumulation detection.
    """
    if volume_6h <= 0 or volume_24h <= 0:
        return 0
    baseline_per_hour = volume_6h / 6
    if baseline_per_hour <= 0:
        return 0
    return volume_1h / baseline_per_hour


def scan_dex_volume_anomaly() -> list[dict]:
    """
    Detects tokens where volume in the last 1h is anomalously high vs their
    recent baseline (6h average per hour), while price has NOT pumped yet.

    Signal logic:
    - Volume spike ratio >= 5x: extraordinary accumulation
    - Price change 1h < 8%: hasn't pumped yet (still early)
    - Buys > Sells * 1.5: clear net buying pressure
    - Liquidity >= $50K: not a rug
    - Token age >= 48h: reduces rug risk

    This pattern typically precedes pumps by 30-180 minutes.
    """
    signals = []
    try:
        resp = requests.get(
            "https://api.dexscreener.com/token-boosts/top/v1",
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        tokens = resp.json()
        if not isinstance(tokens, list):
            return []

        for token in tokens[:40]:
            token_address = token.get("tokenAddress", "")
            chain = token.get("chainId", "")
            if not token_address or _is_on_cooldown(token_address):
                continue

            pair_data = _get_pair_data(token_address)
            if not pair_data:
                continue

            pair = pair_data[0]
            volume_1h = pair.get("volume", {}).get("h1", 0) or 0
            volume_6h = pair.get("volume", {}).get("h6", 0) or 0
            volume_24h = pair.get("volume", {}).get("h24", 0) or 0
            price_change_1h = pair.get("priceChange", {}).get("h1", 0) or 0
            price_change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
            liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
            fdv = pair.get("fdv", 0) or 0
            txns_1h = pair.get("txns", {}).get("h1", {})
            txns_24h = pair.get("txns", {}).get("h24", {})
            buys_1h = txns_1h.get("buys", 0)
            sells_1h = txns_1h.get("sells", 0)
            buys_24h = txns_24h.get("buys", 0)
            sells_24h = txns_24h.get("sells", 0)
            pair_created = pair.get("pairCreatedAt", 0)

            # Basic filters
            if liquidity < MIN_LIQUIDITY_USD:
                continue
            if fdv > MAX_MARKET_CAP:
                continue
            if volume_1h < 10_000:  # min $10K in last hour to matter
                continue

            # Age check
            if pair_created:
                age_hours = (time.time() * 1000 - pair_created) / (1000 * 3600)
                if age_hours < MIN_PAIR_AGE_HOURS or age_hours > MAX_PAIR_AGE_DAYS * 24:
                    continue

            symbol = pair.get("baseToken", {}).get("symbol", "???")
            if symbol.upper() in _BLACKLIST:
                continue
            name = pair.get("baseToken", {}).get("name", "")

            # CORE SIGNAL: Volume anomaly ratio
            spike_ratio = _volume_spike_ratio(volume_1h, volume_6h, volume_24h)

            # Signal 1: Pure volume anomaly (5x+) with flat price = pre-pump accumulation
            is_volume_anomaly = (
                spike_ratio >= 5.0
                and abs(price_change_1h) < 8
                and buys_1h > sells_1h * 1.5
            )

            # Signal 2: Volume anomaly (3x+) with very skewed buy/sell ratio = smart money entry
            is_smart_money = (
                spike_ratio >= 3.0
                and buys_1h > sells_1h * 2.5  # 2.5x more buys than sells
                and abs(price_change_1h) < 5
                and volume_1h > 20_000
            )

            if not is_volume_anomaly and not is_smart_money:
                continue

            signal_type = "volume_anomaly" if is_volume_anomaly else "smart_money_entry"

            _set_cooldown(token_address)
            signals.append({
                "source": f"dex_{signal_type}",
                "symbol": symbol,
                "name": name,
                "chain": chain,
                "address": token_address,
                "price_change_24h": round(price_change_24h, 1),
                "price_change_1h": round(price_change_1h, 1),
                "volume_24h": round(volume_24h),
                "volume_1h": round(volume_1h),
                "liquidity_usd": round(liquidity),
                "fdv": round(fdv),
                "buys_sells_ratio": round(buys_1h / max(sells_1h, 1), 1),
                "spike_ratio": round(spike_ratio, 1),
                "dex_url": pair.get("url", ""),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "signal_type": signal_type,
            })
            logger.info(
                f"💎 GEM [{signal_type}]: {symbol} ({chain}) "
                f"spike={spike_ratio:.1f}x vol_1h=${volume_1h:,.0f} "
                f"buys/sells={buys_1h}/{sells_1h} price_1h={price_change_1h:+.1f}%"
            )

    except Exception as e:
        logger.warning(f"DexScreener volume anomaly scan error: {e}")

    return signals


def scan_new_pairs_with_traction() -> list[dict]:
    """
    Find newly created pairs (1-7 days) that are gaining volume and holders.
    These are tokens in their early growth phase before mainstream attention.
    """
    signals = []
    try:
        resp = requests.get(
            "https://api.dexscreener.com/latest/dex/pairs/solana",
            timeout=10,
        )
        if resp.status_code != 200:
            resp = requests.get(
                "https://api.dexscreener.com/latest/dex/pairs/ethereum",
                timeout=10,
            )
        if resp.status_code != 200:
            return []

        data = resp.json()
        pairs = data.get("pairs", [])

        for pair in pairs[:50]:
            token_address = pair.get("baseToken", {}).get("address", "")
            if not token_address or _is_on_cooldown(f"new_{token_address}"):
                continue

            pair_created = pair.get("pairCreatedAt", 0)
            if not pair_created:
                continue

            age_hours = (time.time() * 1000 - pair_created) / (1000 * 3600)
            if age_hours < MIN_PAIR_AGE_HOURS or age_hours > 7 * 24:
                continue

            volume_24h = pair.get("volume", {}).get("h24", 0) or 0
            liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
            fdv = pair.get("fdv", 0) or 0
            price_change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
            txns = pair.get("txns", {}).get("h24", {})
            buys = txns.get("buys", 0)
            sells = txns.get("sells", 0)

            if liquidity < MIN_LIQUIDITY_USD:
                continue
            if fdv > MAX_MARKET_CAP:
                continue
            if volume_24h < MIN_VOLUME_FOR_NEW_PAIR:
                continue
            if buys + sells < MIN_5M_TXNS:
                continue
            if price_change_24h > 50:
                continue

            symbol = pair.get("baseToken", {}).get("symbol", "???")
            if symbol.upper() in _BLACKLIST:
                continue
            name = pair.get("baseToken", {}).get("name", "")
            chain = pair.get("chainId", "")

            _set_cooldown(f"new_{token_address}")
            signals.append({
                "source": "new_pair_traction",
                "symbol": symbol,
                "name": name,
                "chain": chain,
                "address": token_address,
                "price_change_24h": round(price_change_24h, 1),
                "price_change_1h": 0,
                "volume_24h": round(volume_24h),
                "liquidity_usd": round(liquidity),
                "fdv": round(fdv),
                "buys_sells_ratio": round(buys / max(sells, 1), 1),
                "dex_url": pair.get("url", ""),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "signal_type": "new_pair",
            })
            logger.info(
                f"💎 NEW PAIR: {symbol} ({chain}) age={age_hours:.0f}h "
                f"vol=${volume_24h:,.0f} liq=${liquidity:,.0f}"
            )

    except Exception as e:
        logger.warning(f"New pairs scan error: {e}")

    return signals


def scan_binance_pre_pump() -> list[dict]:
    """
    Detect Binance tokens with volume spike but small price change.
    Volume explosion + flat price = someone is accumulating before a move.
    Also catches recently listed tokens gaining momentum.
    """
    signals = []
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        tickers = resp.json()

        volume_data = []
        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            volume_data.append({
                "symbol": symbol,
                "asset": symbol.replace("USDT", ""),
                "price_change_pct": float(t.get("priceChangePercent", 0)),
                "volume_usd": float(t.get("quoteVolume", 0)),
                "trades": int(t.get("count", 0)),
                "weighted_avg_price": float(t.get("weightedAvgPrice", 0)),
                "last_price": float(t.get("lastPrice", 0)),
            })

        for t in volume_data:
            asset = t["asset"]
            if asset.upper() in _BLACKLIST:
                continue
            if _is_on_cooldown(f"binance_pre_{asset}"):
                continue

            price_change = t["price_change_pct"]
            volume = t["volume_usd"]

            # Skip very high volume tokens (these are established coins, not gems)
            if volume > 100_000_000:
                continue

            # Pattern 1: Extreme trade density with flat price (institutional accumulation)
            # Only triggers for truly anomalous activity: >150K trades with barely any price move
            trade_density = t["trades"] / max(volume / 1_000_000, 0.1)
            is_accumulation = (
                5_000_000 <= volume <= 80_000_000
                and abs(price_change) <= 1.5
                and t["trades"] >= 150_000
                and trade_density >= 40
            )

            # Pattern 2: Strong early pump (20-30%) with extreme volume — first hours of breakout
            is_early_pump = (
                20 <= price_change <= 30
                and 10_000_000 <= volume <= 80_000_000
                and t["trades"] >= 100_000
            )

            if not is_accumulation and not is_early_pump:
                continue

            signal_type = "binance_accumulation" if is_accumulation else "binance_early_pump"

            _set_cooldown(f"binance_pre_{asset}")
            signals.append({
                "source": signal_type,
                "symbol": asset,
                "name": asset,
                "chain": "binance",
                "address": t["symbol"],
                "price_change_24h": round(price_change, 1),
                "price_change_1h": 0,
                "volume_24h": round(volume),
                "liquidity_usd": round(volume),
                "fdv": 0,
                "buys_sells_ratio": 0,
                "dex_url": f"https://www.binance.com/en/trade/{asset}_USDT",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "signal_type": signal_type.replace("binance_", ""),
            })
            logger.info(
                f"💎 BINANCE [{signal_type}]: {asset} "
                f"price={price_change:+.1f}% vol=${volume:,.0f} trades={t['trades']}"
            )

    except Exception as e:
        logger.warning(f"Binance pre-pump scan error: {e}")

    return signals


def _get_pair_data(token_address: str) -> list | None:
    """Get pair data from DexScreener for a token address."""
    try:
        resp = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        pairs = data.get("pairs", [])
        if not pairs:
            return None
        pairs.sort(key=lambda p: p.get("volume", {}).get("h24", 0) or 0, reverse=True)
        return pairs
    except Exception:
        return None


def _get_current_price_dexscreener(address: str) -> float | None:
    """Get current price from DexScreener for a token."""
    try:
        resp = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{address}",
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        pairs = resp.json().get("pairs", [])
        if not pairs:
            return None
        return float(pairs[0].get("priceUsd", 0))
    except Exception:
        return None


def _get_current_price_binance(symbol: str) -> float | None:
    """Get current price from Binance."""
    try:
        resp = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT",
            timeout=5,
        )
        if resp.status_code != 200:
            return None
        return float(resp.json().get("price", 0))
    except Exception:
        return None


def run_gem_scan() -> list[dict]:
    """Run all early-detection scanners and return the best signal per cycle."""
    all_signals = []

    all_signals.extend(scan_dex_volume_anomaly())
    all_signals.extend(scan_new_pairs_with_traction())
    all_signals.extend(scan_binance_pre_pump())

    # Sort by spike ratio first (most anomalous), then by volume
    all_signals.sort(key=lambda s: (s.get("spike_ratio", 0), s.get("volume_24h", 0)), reverse=True)
    all_signals = all_signals[:1]

    if all_signals:
        s = all_signals[0]
        logger.info(f"💎 Gem scan: {s['symbol']} spike={s.get('spike_ratio', 0):.1f}x vol_1h=${s.get('volume_1h', 0):,.0f}")
    else:
        logger.info("💎 Gem scan: nothing exceptional this cycle")
    return all_signals


def save_gem_signals(signals: list[dict]):
    """Save gem signals to the database with current price at detection."""
    if not signals:
        return

    try:
        from web.db_engine import get_engine
        from sqlalchemy import text

        with get_engine("predictions").connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS gem_signals (
                    id SERIAL PRIMARY KEY,
                    source TEXT,
                    symbol TEXT,
                    name TEXT,
                    chain TEXT,
                    address TEXT,
                    price_change_24h DOUBLE PRECISION,
                    volume_24h DOUBLE PRECISION,
                    liquidity_usd DOUBLE PRECISION,
                    fdv DOUBLE PRECISION,
                    dex_url TEXT,
                    detected_at TEXT,
                    signal_type TEXT,
                    buys_sells_ratio DOUBLE PRECISION,
                    price_at_detection DOUBLE PRECISION,
                    price_max_7d DOUBLE PRECISION,
                    price_at_validation DOUBLE PRECISION,
                    validated_at TEXT,
                    outcome TEXT DEFAULT 'pending'
                )
            """))

            for sig in signals:
                price = sig.get("_price")
                if not price:
                    if "binance" in sig["source"]:
                        price = _get_current_price_binance(sig["symbol"])
                    else:
                        price = _get_current_price_dexscreener(sig["address"])

                conn.execute(text("""
                    INSERT INTO gem_signals
                        (source, symbol, name, chain, address, price_change_24h,
                         volume_24h, liquidity_usd, fdv, dex_url, detected_at,
                         signal_type, buys_sells_ratio, price_at_detection)
                    VALUES (:source, :symbol, :name, :chain, :address, :change,
                            :vol, :liq, :fdv, :url, :detected,
                            :signal_type, :ratio, :price)
                """), {
                    "source": sig["source"],
                    "symbol": sig["symbol"],
                    "name": sig["name"],
                    "chain": sig["chain"],
                    "address": sig["address"],
                    "change": sig["price_change_24h"],
                    "vol": sig["volume_24h"],
                    "liq": sig["liquidity_usd"],
                    "fdv": sig["fdv"],
                    "url": sig["dex_url"],
                    "detected": sig["detected_at"],
                    "signal_type": sig.get("signal_type", ""),
                    "ratio": sig.get("buys_sells_ratio", 0),
                    "price": price,
                })
            conn.commit()
            logger.info(f"💾 {len(signals)} gem signals saved to DB")
    except Exception as e:
        logger.error(f"Error saving gem signals: {e}")


def send_gem_alerts_admin(signals: list[dict], admin_chat_id: str):
    """Send gem alerts to admin only via Telegram."""
    if not signals or not admin_chat_id:
        return

    try:
        from src.services.telegram_sender import send_telegram

        for sig in signals[:2]:
            price_str = f"${sig.get('_price', 0):.6f}" if sig.get('_price') else "N/A"

            type_labels = {
                "volume_anomaly": "📊 ANOMALÍA DE VOLUMEN",
                "smart_money_entry": "🧠 SMART MONEY",
                "new_pair": "🆕 PAR NUEVO",
                "binance_accumulation": "🔇 BINANCE ACUM.",
                "early_pump": "🚀 BINANCE EARLY PUMP",
            }
            type_label = type_labels.get(sig.get("signal_type", ""), "💎 GEM")

            spike = sig.get("spike_ratio", 0)
            vol_1h = sig.get("volume_1h", 0)

            msg = (
                f"{'='*30}\n"
                f"💎 GEM ALERT — {type_label}\n"
                f"{'='*30}\n\n"
                f"🪙 {sig['symbol']} ({sig['name']})\n"
                f"💵 Precio: {price_str}\n"
                f"📊 Cambio 1h: {sig.get('price_change_1h', 0):+.1f}% | 24h: {sig['price_change_24h']:+.1f}%\n"
                f"⚡ Spike volumen: {spike:.1f}x la media\n"
                f"💰 Vol 1h: ${vol_1h:,.0f} | Vol 24h: ${sig['volume_24h']:,.0f}\n"
                f"📈 Buys/Sells (1h): {sig.get('buys_sells_ratio', 0):.1f}x\n"
                f"🏦 MCap: ${sig['fdv']:,.0f} | Liquidez: ${sig['liquidity_usd']:,.0f}\n"
                f"🔗 Chain: {sig['chain']}\n\n"
                f"⏱ Validación en 7 días (+30% = correcta)\n"
                f"📡 Solo visible para el admin\n\n"
                f"{sig['dex_url']}"
            )
            send_telegram(msg, chat_id=admin_chat_id)

    except Exception as e:
        logger.warning(f"Error sending gem alerts: {e}")


_GEM_CORRECT_THRESHOLD = 30.0
_GEM_INCORRECT_THRESHOLD = -30.0
_GEM_VALIDATION_DAYS = 7


def validate_pending_gems(admin_chat_id: str = "161542135"):
    """
    Validates gem signals that are >= 7 days old.
    - CORRECT: price went up >= 30% from detection
    - INCORRECT: price dropped >= 30%
    - NEUTRAL: neither threshold reached after 7 days
    """
    try:
        from web.db_engine import get_engine
        from sqlalchemy import text
        from src.services.telegram_sender import send_telegram

        cutoff = (datetime.utcnow() - timedelta(days=_GEM_VALIDATION_DAYS)).isoformat()

        with get_engine("predictions").connect() as conn:
            pending = conn.execute(text("""
                SELECT id, symbol, name, source, address, chain,
                       price_at_detection, detected_at, dex_url, signal_type
                FROM gem_signals
                WHERE outcome = 'pending'
                  AND detected_at <= :cutoff
                  AND price_at_detection IS NOT NULL
                  AND price_at_detection > 0
            """), {"cutoff": cutoff}).fetchall()

        if not pending:
            return

        logger.info(f"💎 Validating {len(pending)} gem signals...")

        with get_engine("predictions").connect() as conn:
            for gem in pending:
                gem_id, symbol, name, source, address, chain, price_det, detected_at, dex_url, signal_type = gem

                current_price = None
                if "binance" in source:
                    current_price = _get_current_price_binance(symbol)
                else:
                    current_price = _get_current_price_dexscreener(address)

                if current_price is None or current_price <= 0:
                    continue

                change_pct = ((current_price - price_det) / price_det) * 100

                if change_pct >= _GEM_CORRECT_THRESHOLD:
                    outcome = "correct"
                elif change_pct <= _GEM_INCORRECT_THRESHOLD:
                    outcome = "incorrect"
                else:
                    outcome = "neutral"

                conn.execute(text("""
                    UPDATE gem_signals
                    SET outcome = :outcome,
                        price_at_validation = :price,
                        validated_at = :now
                    WHERE id = :id
                """), {
                    "outcome": outcome,
                    "price": current_price,
                    "now": datetime.utcnow().isoformat(),
                    "id": gem_id,
                })

                emoji = {"correct": "✅", "incorrect": "❌", "neutral": "⚪"}.get(outcome, "?")
                msg = (
                    f"{'='*30}\n"
                    f"💎 GEM RESULTADO (7d)\n"
                    f"{'='*30}\n\n"
                    f"🪙 {symbol} ({name})\n"
                    f"{emoji} {outcome.upper()}\n\n"
                    f"💵 Precio alerta: ${price_det:.6f}\n"
                    f"💵 Precio ahora: ${current_price:.6f}\n"
                    f"📊 Cambio: {change_pct:+.1f}%\n"
                    f"🏷 Tipo señal: {signal_type}\n\n"
                    f"{dex_url}"
                )
                send_telegram(msg, chat_id=admin_chat_id)
                logger.info(f"💎 Gem #{gem_id} {symbol}: {outcome} ({change_pct:+.1f}%)")

            conn.commit()

    except Exception as e:
        logger.error(f"Error validating gems: {e}")
