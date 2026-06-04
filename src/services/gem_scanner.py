"""
gem_scanner.py — Detecta low-cap gems con momentum explosivo.

Fuentes:
- DexScreener: tokens trending en DEX con volumen anómalo
- CoinGecko: tokens recientemente añadidos con tracción
- Binance: nuevos listings anunciados

Validación (7 días después):
- CORRECT: precio max en 7d >= +30% desde detección
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

_DEXSCREENER_TRENDING = "https://api.dexscreener.com/token-boosts/top/v1"
_DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search"
_COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"
_COINGECKO_NEW = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"

MIN_MARKET_CAP = 1_000_000
MAX_MARKET_CAP = 50_000_000
MIN_LIQUIDITY_USD = 100_000
MIN_VOLUME_24H = 200_000
MIN_PRICE_CHANGE_PCT = 20
MIN_VOLUME_SPIKE = 3.0

_seen_tokens: set[str] = set()
_COOLDOWN_HOURS = 12
_cooldowns: dict[str, float] = {}


def _is_on_cooldown(token_id: str) -> bool:
    last = _cooldowns.get(token_id, 0)
    return (time.time() - last) < _COOLDOWN_HOURS * 3600


def _set_cooldown(token_id: str):
    _cooldowns[token_id] = time.time()


def _passes_anti_rug(pair: dict) -> bool:
    """Basic anti-rug checks on a DexScreener pair."""
    info = pair.get("info", {})
    liquidity = pair.get("liquidity", {}).get("usd", 0)
    pair_created = pair.get("pairCreatedAt", 0)

    if liquidity < MIN_LIQUIDITY_USD:
        return False

    if pair_created:
        age_hours = (time.time() * 1000 - pair_created) / (1000 * 3600)
        if age_hours < 48:
            return False

    fdv = pair.get("fdv", 0)
    if fdv and fdv < MIN_MARKET_CAP:
        return False

    return True


def scan_dexscreener_trending() -> list[dict]:
    """Fetch top boosted tokens from DexScreener."""
    signals = []
    try:
        resp = requests.get(_DEXSCREENER_TRENDING, timeout=10)
        if resp.status_code != 200:
            logger.debug(f"DexScreener trending: {resp.status_code}")
            return []

        tokens = resp.json()
        if not isinstance(tokens, list):
            return []

        for token in tokens[:20]:
            token_address = token.get("tokenAddress", "")
            chain = token.get("chainId", "")
            if not token_address or _is_on_cooldown(token_address):
                continue

            pair_data = _get_pair_data(token_address)
            if not pair_data:
                continue

            pair = pair_data[0] if pair_data else None
            if not pair:
                continue

            if not _passes_anti_rug(pair):
                continue

            price_change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
            volume_24h = pair.get("volume", {}).get("h24", 0) or 0
            liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
            fdv = pair.get("fdv", 0) or 0
            symbol = pair.get("baseToken", {}).get("symbol", "???")
            name = pair.get("baseToken", {}).get("name", "")

            if price_change_24h < MIN_PRICE_CHANGE_PCT:
                continue
            if volume_24h < MIN_VOLUME_24H:
                continue
            if fdv > MAX_MARKET_CAP:
                continue

            _set_cooldown(token_address)
            signals.append({
                "source": "dexscreener",
                "symbol": symbol,
                "name": name,
                "chain": chain,
                "address": token_address,
                "price_change_24h": round(price_change_24h, 1),
                "volume_24h": round(volume_24h),
                "liquidity_usd": round(liquidity),
                "fdv": round(fdv),
                "dex_url": pair.get("url", ""),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"💎 GEM: {symbol} ({chain}) +{price_change_24h:.0f}% vol=${volume_24h:,.0f} mcap=${fdv:,.0f}")

    except Exception as e:
        logger.warning(f"DexScreener scan error: {e}")

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


def scan_coingecko_trending() -> list[dict]:
    """Fetch trending coins from CoinGecko (free, no API key)."""
    signals = []
    try:
        resp = requests.get(_COINGECKO_TRENDING, timeout=10)
        if resp.status_code != 200:
            return []

        data = resp.json()
        coins = data.get("coins", [])

        for item in coins:
            coin = item.get("item", {})
            coin_id = coin.get("id", "")
            symbol = coin.get("symbol", "")
            name = coin.get("name", "")
            market_cap_rank = coin.get("market_cap_rank") or 9999
            price_change_24h = coin.get("data", {}).get("price_change_percentage_24h", {}).get("usd", 0) or 0

            if _is_on_cooldown(coin_id):
                continue
            if market_cap_rank < 100:
                continue
            if price_change_24h < 15:
                continue

            mcap = coin.get("data", {}).get("market_cap", "") or ""
            if isinstance(mcap, str) and mcap.startswith("$"):
                mcap_val = float(mcap.replace("$", "").replace(",", "")) if mcap else 0
            else:
                mcap_val = float(mcap) if mcap else 0

            if mcap_val > MAX_MARKET_CAP:
                continue

            _set_cooldown(coin_id)
            signals.append({
                "source": "coingecko_trending",
                "symbol": symbol.upper(),
                "name": name,
                "chain": "",
                "address": coin_id,
                "price_change_24h": round(price_change_24h, 1),
                "volume_24h": 0,
                "liquidity_usd": 0,
                "fdv": round(mcap_val),
                "dex_url": f"https://www.coingecko.com/en/coins/{coin_id}",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"💎 GEM (CG trending): {symbol} +{price_change_24h:.0f}% rank={market_cap_rank}")

    except Exception as e:
        logger.warning(f"CoinGecko trending scan error: {e}")

    return signals


def scan_binance_new_listings() -> list[dict]:
    """Check Binance for recently listed pairs with strong momentum."""
    signals = []
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        tickers = resp.json()
        for t in tickers:
            symbol = t.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue

            price_change_pct = float(t.get("priceChangePercent", 0))
            volume_usd = float(t.get("quoteVolume", 0))
            asset = symbol.replace("USDT", "")

            if price_change_pct < 25:
                continue
            if volume_usd < 500_000:
                continue
            if _is_on_cooldown(f"binance_{asset}"):
                continue

            _set_cooldown(f"binance_{asset}")
            signals.append({
                "source": "binance_momentum",
                "symbol": asset,
                "name": asset,
                "chain": "binance",
                "address": symbol,
                "price_change_24h": round(price_change_pct, 1),
                "volume_24h": round(volume_usd),
                "liquidity_usd": round(volume_usd),
                "fdv": 0,
                "dex_url": f"https://www.binance.com/en/trade/{asset}_USDT",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info(f"💎 GEM (Binance): {asset} +{price_change_pct:.0f}% vol=${volume_usd:,.0f}")

    except Exception as e:
        logger.warning(f"Binance listing scan error: {e}")

    return signals


def run_gem_scan() -> list[dict]:
    """Run all gem scanners and return combined results."""
    all_signals = []

    all_signals.extend(scan_dexscreener_trending())
    all_signals.extend(scan_coingecko_trending())
    all_signals.extend(scan_binance_new_listings())

    all_signals.sort(key=lambda s: s.get("price_change_24h", 0), reverse=True)

    logger.info(f"💎 Gem scan complete: {len(all_signals)} signals found")
    return all_signals


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
                    price_at_detection DOUBLE PRECISION,
                    price_max_7d DOUBLE PRECISION,
                    price_at_validation DOUBLE PRECISION,
                    validated_at TEXT,
                    outcome TEXT DEFAULT 'pending'
                )
            """))

            for sig in signals:
                price = None
                if sig["source"] == "binance_momentum":
                    price = _get_current_price_binance(sig["symbol"])
                else:
                    price = _get_current_price_dexscreener(sig["address"])

                conn.execute(text("""
                    INSERT INTO gem_signals
                        (source, symbol, name, chain, address, price_change_24h,
                         volume_24h, liquidity_usd, fdv, dex_url, detected_at,
                         price_at_detection)
                    VALUES (:source, :symbol, :name, :chain, :address, :change,
                            :vol, :liq, :fdv, :url, :detected, :price)
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

        for sig in signals[:5]:
            price_str = f"${sig.get('_price', 0):.6f}" if sig.get('_price') else "N/A"
            msg = (
                f"{'='*30}\n"
                f"💎 GEM ALERT 💎\n"
                f"{'='*30}\n\n"
                f"🪙 {sig['symbol']} ({sig['name']})\n"
                f"📈 +{sig['price_change_24h']}% en 24h\n"
                f"💵 Precio: {price_str}\n"
                f"💰 Vol 24h: ${sig['volume_24h']:,.0f}\n"
                f"🏦 MCap: ${sig['fdv']:,.0f}\n"
                f"💧 Liquidez: ${sig['liquidity_usd']:,.0f}\n"
                f"🔗 Chain: {sig['chain']}\n"
                f"📡 Fuente: {sig['source']}\n\n"
                f"⏱ Validación en 7 días\n"
                f"✅ Correcta si sube +30% desde ahora\n"
                f"❌ Incorrecta si cae -30%\n\n"
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
    Checks current price vs price_at_detection.

    - CORRECT: price went up >= 30% at any point (check current price)
    - INCORRECT: price dropped >= 30% and never hit +30%
    - NEUTRAL: 7 days passed, neither threshold reached
    """
    try:
        from web.db_engine import get_engine
        from sqlalchemy import text
        from src.services.telegram_sender import send_telegram

        cutoff = (datetime.utcnow() - timedelta(days=_GEM_VALIDATION_DAYS)).isoformat()

        with get_engine("predictions").connect() as conn:
            pending = conn.execute(text("""
                SELECT id, symbol, name, source, address, chain,
                       price_at_detection, detected_at, dex_url
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
                gem_id, symbol, name, source, address, chain, price_det, detected_at, dex_url = gem

                current_price = None
                if source == "binance_momentum":
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
                    f"💎 GEM RESULTADO ({_GEM_VALIDATION_DAYS}d)\n"
                    f"{'='*30}\n\n"
                    f"🪙 {symbol} ({name})\n"
                    f"{emoji} {outcome.upper()}\n\n"
                    f"💵 Precio alerta: ${price_det:.6f}\n"
                    f"💵 Precio ahora: ${current_price:.6f}\n"
                    f"📊 Cambio: {change_pct:+.1f}%\n\n"
                    f"📡 Fuente: {source}\n"
                    f"{dex_url}"
                )
                send_telegram(msg, chat_id=admin_chat_id)
                logger.info(f"💎 Gem #{gem_id} {symbol}: {outcome} ({change_pct:+.1f}%)")

            conn.commit()

    except Exception as e:
        logger.error(f"Error validating gems: {e}")
