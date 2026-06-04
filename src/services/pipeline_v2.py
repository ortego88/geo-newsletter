"""
Pipeline principal v2.
Flujo: fetch RSS → deduplicar → scoring → filtrar por activo → analizar con IA → guardar predicciones.

Scope: SOLO Criptodivisas.
Noticias que no hacen match con ningún activo crypto son descartadas.
"""

import logging
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone

import feedparser

from src.services.content_filter import is_entertainment_noise
from src.services.deduplicator import Deduplicator
from src.services.fast_signals import fetch_fast_signals
from src.services.gpt_analyzer import EventAnalyzer
from src.services.prediction_tracker import PredictionTracker
from src.services.real_price_fetcher import RealPriceFetcher, CRYPTO_IDS, YAHOO_TICKERS

logger = logging.getLogger("geo-newsletter")

# --- Conjunto de activos válidos conocidos ---
VALID_ASSETS = set(CRYPTO_IDS.keys()) | set(YAHOO_TICKERS.keys())

# --- Fallback de activo por categoría cuando el modelo inventa tickers ---
CATEGORY_FALLBACK = {
    "crypto": "BTC",
    "mercados": "BTC",
    "financial": "BTC",
    "finance": "BTC",
    "general": "BTC",
    "geopolítica": "BTC",
    "geopolitical": "BTC",
    "conflicto": "BTC",
    "energía": "BTC",
    "energy": "BTC",
    "commodities": "BTC",
}

# --- Fuentes RSS: SOLO Crypto ---
# Priorizadas por velocidad de publicación (las más rápidas primero).
# Las fuentes "wire" y exchanges publican con menor latencia que los medios editoriales.
RSS_SOURCES = [
    # --- Fuentes rápidas (baja latencia, wire-style) ---
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "The Block", "url": "https://www.theblock.co/rss.xml"},
    {"name": "DL News", "url": "https://www.dlnews.com/arc/outboundfeeds/rss/"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/"},
    {"name": "U.Today", "url": "https://u.today/rss"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/"},
    {"name": "Bitcoinist", "url": "https://bitcoinist.com/feed/"},

    # --- Medios crypto editoriales (buena calidad, algo más lentos) ---
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/.rss/full/"},

    # --- Fuentes adicionales (cobertura amplia) ---
    {"name": "BeInCrypto", "url": "https://beincrypto.com/feed/"},
    {"name": "CoinGape", "url": "https://coingape.com/feed/"},
    {"name": "Crypto News", "url": "https://crypto.news/feed/"},
    {"name": "AMBCrypto", "url": "https://ambcrypto.com/feed/"},

    # --- Crypto (español) ---
    {"name": "Cointelegraph ES", "url": "https://es.cointelegraph.com/rss"},
    {"name": "CriptoNoticias", "url": "https://www.criptonoticias.com/feed/"},
    {"name": "BeInCrypto ES", "url": "https://es.beincrypto.com/feed/"},
]

# ---------------------------------------------------------------------------
# ASSET_KEYWORDS — diccionario de activos con sus palabras clave de detección.
# Clave: ticker del activo. Valor: lista de keywords (case-insensitive).
# Scope: SOLO criptodivisas.
# ---------------------------------------------------------------------------
ASSET_KEYWORDS: dict[str, list[str]] = {
    # ── Criptodivisas — Top por capitalización ────────────────────────────
    "BTC": [
        "bitcoin", "btc", "halving", "satoshi",
        "bitcoin etf", "bitcoin spot", "btc etf",
    ],
    "ETH": ["ethereum", "ether", "eth", "erc-20", "erc20", "ethereum etf", "vitalik"],
    "XRP": ["ripple", "xrp", "ripple labs", "ripple sec"],
    "SOL": ["solana", "sol token", "solana network", "solana ecosystem"],
    "BNB": ["binance coin", "bnb", "binance smart chain", "bsc", "binance chain"],
    "ADA": ["cardano", "ada token", "charles hoskinson", "cardano network"],
    "DOGE": ["dogecoin", "doge", "elon musk doge"],
    "DOT": ["polkadot", "dot token", "parachains", "polkadot network"],
    "AVAX": ["avalanche", "avax", "avalanche subnet", "avalanche network"],
    "MATIC": ["polygon matic", "polygon network", "polygon labs", "pol token", "polygon"],
    "LINK": ["chainlink", "link token", "chainlink oracle", "chainlink network"],
    "UNI": ["uniswap", "uni token", "uniswap governance", "uniswap v4"],
    "LTC": ["litecoin", "ltc token", "litecoin network"],
    "ATOM": ["cosmos", "cosmos hub", "cosmos network", "cosmos blockchain", "atom token", "interchain"],
    "XLM": ["stellar", "stellar lumens", "stellar xlm", "stellar network"],
    "ALGO": ["algorand", "algo token", "algorand network"],
    "FIL": ["filecoin", "fil token", "filecoin network"],
    "NEAR": ["near protocol", "near token", "near blockchain"],
    "ARB": ["arbitrum", "arb token", "arbitrum one", "arbitrum network"],
    "OP": ["optimism rollup", "optimism network", "optimism l2", "optimism blockchain"],
    # ── Layer 2 & Infra ─────────────────────────────────────────────────────
    "SUI": ["sui network", "sui blockchain", "sui token", "sui ecosystem"],
    "APT": ["aptos", "aptos labs", "apt token", "aptos network"],
    "SEI": ["sei network", "sei blockchain", "sei token", "sei v2"],
    "TIA": ["celestia", "tia token", "celestia modular", "celestia network"],
    "INJ": ["injective", "inj token", "injective protocol", "injective network"],
    "ICP": ["internet computer", "icp token", "dfinity", "icp network"],
    "STX": ["stacks", "stx token", "stacks bitcoin", "stacks network"],
    "MNT": ["mantle network", "mantle token", "mnt token", "mantle chain"],
    "IMX": ["immutable", "immutable x", "imx token", "immutable gaming"],
    # ── DeFi ──────────────────────────────────────────────────────────────
    "AAVE": ["aave", "aave protocol", "aave lending", "aave v3", "aave governance"],
    "MKR": ["maker", "makerdao", "maker dao", "mkr token", "dai stablecoin", "sky maker"],
    "CRV": ["curve finance", "curve dao", "crv token", "curve protocol", "curve wars"],
    "LDO": ["lido dao", "lido finance", "lido staking", "ldo token", "lido protocol"],
    "DYDX": ["dydx", "dydx exchange", "dydx protocol", "dydx chain"],
    "SNX": ["synthetix", "snx token", "synthetix protocol", "synthetix perps"],
    "PENDLE": ["pendle", "pendle finance", "pendle protocol", "pendle yield"],
    "JUPITER": ["jupiter exchange", "jupiter solana", "jupiter dex", "jup token", "jupiter aggregator"],
    # ── AI & Data ─────────────────────────────────────────────────────────
    "RENDER": ["render network", "render token", "rndr", "render gpu"],
    "FET": ["fetch.ai", "fetch ai", "artificial superintelligence", "fet token", "asi alliance"],
    "TAO": ["bittensor", "tao token", "bittensor network", "bittensor subnet"],
    "ONDO": ["ondo finance", "ondo token", "ondo rwa", "ondo tokenization"],
    "AIOZ": ["aioz network", "aioz token", "aioz node"],
    # ── Gaming & Metaverse ────────────────────────────────────────────────
    "AXS": ["axie infinity", "axs token", "axie"],
    "SAND": ["the sandbox", "sandbox metaverse", "sand token", "sandbox game"],
    "MANA": ["decentraland", "mana token", "decentraland metaverse"],
    "GALA": ["gala games", "gala token", "gala gaming", "gala entertainment"],
    "ENJ": ["enjin", "enjin coin", "enj token", "enjin platform"],
    # ── Memecoins ─────────────────────────────────────────────────────────
    "PEPE": ["pepe coin", "pepe token", "pepe memecoin", "$pepe"],
    "WIF": ["dogwifhat", "wif token", "$wif"],
    "FLOKI": ["floki", "floki inu", "floki token"],
    "BONK": ["bonk", "bonk token", "bonk solana", "$bonk"],
    "SHIB": ["shiba inu", "shib token", "shibarium", "shib burn"],
    # ── Exchange tokens ───────────────────────────────────────────────────
    "CRO": ["cronos", "crypto.com", "cro token", "cronos chain"],
    "OKB": ["okb", "okx token", "okex", "okx exchange"],
    "GT": ["gate token", "gate.io", "gatechain"],
    # ── Otros relevantes ──────────────────────────────────────────────────
    "TON": ["toncoin", "ton network", "telegram open network", "ton blockchain", "ton ecosystem"],
    "TRX": ["tron", "trx token", "tron network", "justin sun"],
    "HBAR": ["hedera", "hbar token", "hedera hashgraph", "hedera network"],
    "VET": ["vechain", "vet token", "vechain supply", "vechain network"],
    "THETA": ["theta network", "theta token", "theta blockchain"],
    "FTM": ["fantom", "ftm token", "fantom opera", "sonic", "sonic network"],
    "EOS": ["eos", "eos network", "block.one"],
    "RUNE": ["thorchain", "rune token", "thorchain dex", "thorchain network"],
    "GRT": ["the graph", "graph protocol", "grt token", "subgraph"],
    "KAS": ["kaspa", "kas token", "kaspa blockchain", "kaspa network"],
    # ── Genérico crypto (catch-all para noticias de mercado general) ────────
    "CRYPTO_MARKET": [
        "criptomoneda", "criptomonedas", "crypto market",
        "cryptocurrency market", "mercado crypto",
        "moneda digital", "activo digital",
    ],
}



# Tiers de prioridad — un ticker de Nivel 1 siempre gana sobre Nivel 2, etc.
_PRIORITY_TIERS = [
    # Tier 1: Top 20 por capitalización
    frozenset({"BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "TON", "DOGE", "DOT",
               "AVAX", "LINK", "SHIB", "TRX", "MATIC", "SUI", "LTC", "HBAR",
               "UNI", "ATOM", "XLM", "NEAR"}),
    # Tier 2: Layer 2, DeFi, AI, Infra
    frozenset({"ARB", "OP", "ICP", "FIL", "IMX", "STX", "MNT",
               "AAVE", "MKR", "CRV", "LDO", "DYDX", "SNX", "PENDLE", "JUPITER",
               "FET", "RENDER", "INJ", "TAO", "ONDO", "AIOZ",
               "APT", "SEI", "TIA", "KAS", "ALGO"}),
    # Tier 3: Gaming, exchange tokens, otros
    frozenset({"AXS", "SAND", "MANA", "GALA", "ENJ",
               "CRO", "OKB", "GT",
               "VET", "THETA", "FTM", "EOS", "RUNE", "GRT"}),
    # Tier 4: Memecoins
    frozenset({"PEPE", "WIF", "FLOKI", "BONK"}),
    # Tier 5: Genérico crypto — solo si no hay nada en tiers superiores
    frozenset({"CRYPTO_MARKET"}),
]


def _get_ticker_tier(ticker: str) -> int:
    """Devuelve el tier de prioridad de un ticker (0=máxima prioridad, 3=mínima).
    Tickers desconocidos reciben tier 4 (fuera de los tiers definidos)."""
    for i, tier in enumerate(_PRIORITY_TIERS):
        if ticker in tier:
            return i
    return len(_PRIORITY_TIERS)  # desconocido → mínima prioridad


def _kw_matches(keyword: str, text: str) -> bool:
    """
    Comprueba si un keyword está presente en el texto con límite de palabra.

    Para keywords de más de 5 caracteres se usa búsqueda simple (substring)
    ya que la probabilidad de falso positivo es baja.
    Para keywords cortos (≤5 chars) se usa regex con límite de palabra (\b)
    para evitar falsos positivos (ej. 'OP' en 'compra', 'SOL' en 'absoluto').
    """
    if len(keyword) <= 5:
        return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text, re.IGNORECASE))
    return keyword in text


def _match_asset(article: dict) -> tuple[str | None, list[str]]:
    """
    Busca keywords de ASSET_KEYWORDS en el título + descripción del artículo.

    Prioridad de selección:
    1. Tier más alto (empresa específica > crypto específica > ETF > genérico)
    2. Dentro del mismo tier: title mentions > description-only mentions
    3. Dentro del mismo tier y ubicación: mayor número de keyword hits

    Devuelve (primary_ticker, [all_matched_tickers]).
    """
    title = article.get("title") or ""
    description = article.get("description") or article.get("summary") or ""
    title_lower = title.lower()
    text = (title + " " + description).lower()

    hits_per_ticker: dict[str, int] = {}
    title_hits_per_ticker: dict[str, int] = {}
    for ticker, keywords in ASSET_KEYWORDS.items():
        count = sum(1 for kw in keywords if _kw_matches(kw, text))
        if count > 0:
            hits_per_ticker[ticker] = count
            title_hits_per_ticker[ticker] = sum(1 for kw in keywords if _kw_matches(kw, title_lower))

    if not hits_per_ticker:
        return None, []

    # Sort by: 1) tier asc, 2) title hits desc (title mention = more relevant), 3) total hits desc
    sorted_tickers = sorted(
        hits_per_ticker.items(),
        key=lambda x: (_get_ticker_tier(x[0]), -title_hits_per_ticker.get(x[0], 0), -x[1]),
    )

    all_matched = [t for t, _ in sorted_tickers]
    primary = sorted_tickers[0][0]

    # Log cuando hay override de genérico por específico
    if len(sorted_tickers) > 1:
        second = sorted_tickers[1][0]
        primary_tier = _get_ticker_tier(primary)
        second_tier = _get_ticker_tier(second)
        if primary_tier < second_tier:
            logger.debug(
                f"Tier override: {primary}(tier={primary_tier}, hits={hits_per_ticker[primary]}) "
                f"> {second}(tier={second_tier}, hits={hits_per_ticker[second]})"
            )

    return primary, all_matched


# --- Taxonomía de eventos para scoring de calidad ---
EVENT_TAXONOMY = {
    "crypto_high_impact": {
        "keywords": [
            "bitcoin", "ethereum", "btc", "eth", "solana", "xrp", "ripple",
            "sec", "etf approved", "etf aprobado", "halving", "hack", "exploit",
            "regulation", "regulación", "ban", "prohibición", "adoption",
            "blackrock", "fidelity", "institutional", "institucional",
            "fed", "interest rate", "tipo de interés",
            "whale", "ballena", "liquidation", "liquidación",
        ],
        "base_severity": 65,
        "category": "CRYPTO",
    },
    "crypto_medium_impact": {
        "keywords": [
            "crypto", "blockchain", "defi", "nft", "stablecoin",
            "criptomoneda", "criptomonedas", "moneda digital",
            "altcoin", "binance", "coinbase", "kraken",
            "polkadot", "avalanche", "chainlink", "cardano",
            "uniswap", "litecoin", "algorand", "filecoin", "arbitrum",
            "dogecoin", "polygon", "cosmos", "stellar",
            "sui", "aptos", "celestia", "injective", "toncoin",
            "layer 2", "l2", "rollup", "airdrop", "staking",
            "token", "dex", "cex", "exchange", "trading",
            "solana", "near", "render", "bittensor", "pendle",
            "aave", "lido", "curve", "synthetix", "jupiter",
            "thorchain", "hedera", "kaspa", "mantle", "sei",
            "immutable", "fetch.ai", "ondo", "gala",
        ],
        "base_severity": 58,
        "category": "CRYPTO",
    },
    "crypto_macro": {
        "keywords": [
            "stock market", "fed", "interest rate", "inflation", "recession",
            "central bank", "risk assets", "activos de riesgo",
            "liquidity", "liquidez", "dollar", "dólar", "dxy",
            "treasury", "bond yield",
        ],
        "base_severity": 45,
        "category": "CRYPTO",
    },
}


_MAX_KEYWORD_BONUS = 15   # maximum bonus points from keyword hits
_LOG_SCALE_FACTOR = 10   # scale factor for logarithmic keyword bonus


def _score_event(article: dict) -> tuple[int, str]:
    """Devuelve (score, category) basado en la taxonomía.

    Scoring uses a logarithmic bonus formula so that keyword hits produce
    a more distributed score range rather than clustering near base_severity:

        score = base_severity + min(_MAX_KEYWORD_BONUS, int(log(hits + 1) * _LOG_SCALE_FACTOR))

    This means a single-keyword match produces a noticeably lower score
    than multiple matches, and the base_severity alone no longer dominates.

    Fast signals (volume spikes) get a direct score based on the spike magnitude.
    """
    # Fast signals (volume spikes from Binance) bypass keyword scoring
    if article.get("_fast_signal") and article.get("_volume_ratio"):
        ratio = article["_volume_ratio"]
        # 3x → 70, 5x → 80, 8x+ → 90
        score = min(95, int(60 + ratio * 4))
        return score, "CRYPTO"

    title = article.get("title") or ""
    description = article.get("description") or article.get("summary") or ""

    if is_entertainment_noise(title, description):
        return 0, "FILTERED"

    text = (title + " " + description).lower()

    best_score = 0
    best_category = "GENERAL"

    for event_type, config in EVENT_TAXONOMY.items():
        hits = sum(1 for kw in config["keywords"] if kw in text)
        if hits > 0:
            bonus = min(_MAX_KEYWORD_BONUS, int(math.log(hits + 1) * _LOG_SCALE_FACTOR))
            score = min(95, config["base_severity"] + bonus)
            if score > best_score:
                best_score = score
                best_category = config["category"]

    return best_score, best_category


def _fetch_rss(minutes: int = 120) -> list[dict]:
    """Descarga artículos de todas las fuentes RSS."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    for source in RSS_SOURCES:
        try:
            logger.info(f"📰 Buscando en {source['name']}...")
            feed = feedparser.parse(source["url"])
            for entry in feed.entries:
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                title = entry.get("title", "")
                if len(title) < 20:
                    continue
                articles.append({
                    "title": title,
                    "description": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "source": source["name"],
                    "sources": [source["name"]],
                    "published_at": entry.get("published", ""),
                })
        except Exception as e:
            logger.warning(f"Error en {source['name']}: {e}")

    logger.info(f"✅ Total de noticias encontradas: {len(articles)}")
    return articles


def _make_event_id(article: dict) -> str:
    raw = f"{article.get('title', '')}|{article.get('url', '')}"
    return hashlib.md5(raw.encode()).hexdigest()


class AnalysisPipeline:
    def __init__(self, db_path: str = "data/predictions.db"):
        self.deduplicator = Deduplicator()
        self.analyzer = EventAnalyzer(use_ollama=True)
        self.tracker = PredictionTracker(db_path=db_path)
        self.price_fetcher = RealPriceFetcher()

    def run(self, minutes: int = 120, min_score: int = 30) -> list[dict]:
        """
        Ejecuta el pipeline completo y devuelve los eventos relevantes analizados.
        """
        logger.info("🚀 INICIANDO PIPELINE DE ANÁLISIS")

        # Paso 1: Fetch (RSS + fast signals)
        logger.info("📰 PASO 1: Recolectando noticias...")
        articles = _fetch_rss(minutes=minutes)
        logger.info(f"   ✅ {len(articles)} noticias RSS")

        # Paso 1b: Fuentes rápidas (Binance volume spikes + CryptoPanic)
        try:
            fast = fetch_fast_signals()
            if fast:
                articles.extend(fast)
                logger.info(f"   ⚡ {len(fast)} señales rápidas añadidas")
        except Exception as e:
            logger.warning(f"   ⚠️ Error en fast signals: {e}")

        logger.info(f"   ✅ {len(articles)} noticias totales")

        # Paso 2: Deduplicar
        logger.info("🔄 PASO 2: Deduplicando noticias...")
        articles = self.deduplicator.deduplicate(articles)
        logger.info(f"   ✅ {len(articles)} noticias únicas")

        if not articles:
            logger.info("Sin noticias nuevas.")
            return []

        # Paso 3: Scoring
        logger.info("📊 PASO 3: Scoring de eventos...")
        scored = []
        for article in articles:
            score, category = _score_event(article)
            if category == "FILTERED":
                logger.info(f"   🚫 Filtrado (entretenimiento): {article.get('title', '')[:60]}")
                continue
            if score >= min_score:
                article["score"] = score
                article["category"] = category
                article["event_id"] = _make_event_id(article)
                scored.append(article)

        scored.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"   ✅ {len(scored)} eventos con score >= {min_score}")

        # Paso 3b: Filtrar por activo Crypto
        logger.info("🎯 PASO 3b: Filtrando por activos Crypto...")
        relevant = []
        for article in scored:
            primary_asset, matched_assets = _match_asset(article)
            if primary_asset is None:
                logger.debug(f"   ⛔ Sin activo match: {article.get('title', '')[:60]}")
                continue
            article["suggested_asset"] = primary_asset
            article["matched_assets"] = matched_assets
            relevant.append(article)
        logger.info(
            f"   ✅ {len(relevant)} eventos relevantes (Crypto) "
            f"de {len(scored)} totales"
        )
        scored = relevant

        if not scored:
            return []

        # Paso 3c: Deduplicación semántica (Nivel 2) — últimas 48h, mismo ticker
        logger.info("🧠 PASO 3c: Deduplicación semántica (TF-IDF) por ticker...")
        self.deduplicator.purge_old_recent()
        non_duplicate = []
        for article in scored:
            ticker = article.get("suggested_asset", "")
            if self.deduplicator.check_semantic(article, ticker):
                continue
            non_duplicate.append(article)
        logger.info(
            f"   ✅ {len(non_duplicate)} noticias únicas tras dedup semántica "
            f"(descartadas: {len(scored) - len(non_duplicate)})"
        )
        scored = non_duplicate

        if not scored:
            return []

        # Paso 4: Analizar con IA (batch mode — reduce token usage)
        logger.info(f"🤖 PASO 4: Analizando {len(scored)} eventos con IA (batch)...")
        BATCH_SIZE = 5
        analyzed = []
        for batch_start in range(0, len(scored), BATCH_SIZE):
            batch = scored[batch_start:batch_start + BATCH_SIZE]
            logger.info(f"   📦 Batch {batch_start // BATCH_SIZE + 1}: {len(batch)} eventos")
            from src.services.claude_analyzer import analyze_events_batch
            batch_results = analyze_events_batch(batch)
            for event, analysis in zip(batch, batch_results):
                if analysis is None:
                    analysis = {}
                event["analysis"] = analysis
                analyzed.append(event)

        logger.info(f"   ✅ {len(analyzed)} eventos analizados")

        # Paso 5: Guardar predicciones con precios reales
        logger.info("💾 PASO 5: Guardando predicciones...")
        for event in analyzed:
            analysis = event.get("analysis", {})

            event_score = event.get("score", 0)
            event_confidence = analysis.get("confidence", 0)
            if event_score < 60 or event_confidence < 65:
                logger.info(
                    f"   ⏭️ No guardada (score={event_score}, conf={event_confidence}): "
                    f"{event.get('title', '')[:55]}"
                )
                continue

            assets = analysis.get("most_affected_assets", ["UNKNOWN"])
            primary_asset = assets[0] if assets else "UNKNOWN"

            # Skip stablecoins
            from src.services.real_price_fetcher import STABLECOIN_BLACKLIST
            if primary_asset.upper() in STABLECOIN_BLACKLIST:
                logger.info(f"   ⏭️ Stablecoin {primary_asset} — omitiendo predicción")
                continue

            # Validar el activo primario contra la lista conocida
            if primary_asset.upper() not in VALID_ASSETS:
                suggested = event.get("suggested_asset", "")
                matched = event.get("matched_assets", [])

                all_candidates = ([suggested] if suggested else []) + [
                    a for a in matched if a != suggested
                ]
                valid_candidates = [a for a in all_candidates if a.upper() in VALID_ASSETS]

                if valid_candidates:
                    best = valid_candidates[0]
                    logger.warning(
                        f"   Activo IA '{primary_asset}' desconocido → usando mejor match '{best}' "
                        f"(tier={_get_ticker_tier(best.upper())})"
                    )
                    primary_asset = best
                else:
                    logger.warning(
                        f"   ⏭️ Activo desconocido '{primary_asset}' sin match válido → omitiendo predicción"
                    )
                    continue

            direction = analysis.get("direction", "neutral")

            # ── Filtro 1: Lenguaje especulativo + hedging en predicciones UP ─
            # Si Claude usa "podría/sugiere" + "aunque/pero" sin catalizador confirmado
            # → la convicción es realmente baja, penalizar confidence
            if direction == "up":
                reasoning_lower = (analysis.get("reasoning") or "").lower()
                speculative_words = ("podría", "sugiere", "posible", "puede que", "si se aprueba")
                hedge_words = ("aunque", "pero", "sin embargo", "a pesar")
                certainty_words = ("confirmado", "aprobado", "anuncio", "compra de",
                                   "lanza", "adquisición", "partnership", "alianza")
                has_speculative = any(w in reasoning_lower for w in speculative_words)
                has_hedge = any(w in reasoning_lower for w in hedge_words)
                has_certainty = any(w in reasoning_lower for w in certainty_words)
                if has_speculative and has_hedge and not has_certainty:
                    original_conf = analysis.get("confidence", 0)
                    analysis["confidence"] = original_conf - 5
                    event_confidence = analysis["confidence"]
                    logger.info(
                        f"   ⚠️ Speculative penalty: reasoning especulativo+hedge "
                        f"(conf {original_conf}→{event_confidence}): {event.get('title', '')[:50]}"
                    )

            # ── Filtro 2: Tendencia de mercado por activo + mercado general ──
            # En bear market, exigir más confianza para predicciones UP.
            # Usa tanto la tendencia del activo como la de BTC (proxy del mercado).
            if direction == "up":
                ctx = self.price_fetcher.get_price_context(primary_asset)
                change_7d = ctx.get("change_7d_pct", 0)

                btc_ctx = self.price_fetcher.get_price_context("BTC") if primary_asset != "BTC" else ctx
                btc_7d = btc_ctx.get("change_7d_pct", 0)

                asset_bearish = change_7d <= -5
                market_bearish = btc_7d <= -5

                if asset_bearish and market_bearish:
                    required_conf = 80
                elif asset_bearish or market_bearish:
                    required_conf = 75
                else:
                    required_conf = 65

                if event_confidence < required_conf:
                    logger.info(
                        f"   ⏭️ Bear filter: {primary_asset} {change_7d:+.1f}% / BTC {btc_7d:+.1f}% en 7d → "
                        f"requiere conf>={required_conf}, tiene {event_confidence}: "
                        f"{event.get('title', '')[:50]}"
                    )
                    continue

            # ── Filtro 3: Fuentes con bajo accuracy en UP ─────────────────
            if direction == "up":
                source = event.get("source", "")
                low_accuracy_up_sources = {"AMBCrypto", "U.Today"}
                if source in low_accuracy_up_sources:
                    original_conf = analysis.get("confidence", 0)
                    analysis["confidence"] = min(original_conf, 65)
                    if analysis["confidence"] < 70:
                        logger.info(
                            f"   ⏭️ Source filter: {source} tiene bajo accuracy UP "
                            f"(conf {original_conf}→{analysis['confidence']}): "
                            f"{event.get('title', '')[:50]}"
                        )
                        continue

            # ── Filtro 4: Títulos especulativos / clickbait ───────────────
            title_lower = (event.get("title") or "").lower()
            speculative_title_patterns = (
                "can it reach", "can it hit", "is next", "eyes ",
                "analyst eyes", "analyst predicts", "analyst says",
                "could ", "what it means", "what about",
                "suggests", "metrics suggest", "signals show",
                "outpacing", "outperform",
            )
            if any(p in title_lower for p in speculative_title_patterns):
                if direction == "up":
                    logger.info(
                        f"   ⏭️ Title filter: patrón especulativo detectado en UP: "
                        f"{event.get('title', '')[:60]}"
                    )
                    continue

            current_price = self.price_fetcher.get_price(primary_asset)
            if current_price is None or current_price <= 0:
                logger.warning(
                    f"   No se pudo obtener precio para {primary_asset} (price={current_price}), omitiendo predicción"
                )
                continue

            # Momentum check: si el precio ya se movió >2.5% en la dirección
            # predicha en las últimas 4h → reducir confidence o descartar
            recent_change = self.price_fetcher.get_recent_change(primary_asset, hours=4)
            if recent_change is not None and direction in ("up", "down"):
                already_moved_same_dir = (
                    (direction == "up" and recent_change >= 2.5)
                    or (direction == "down" and recent_change <= -2.5)
                )
                if already_moved_same_dir:
                    original_conf = analysis.get("confidence", 0)
                    penalty = min(25, int(abs(recent_change) * 5))
                    new_conf = original_conf - penalty
                    if new_conf < 55:
                        logger.info(
                            f"   ⏭️ Momentum filter: {primary_asset} ya se movió {recent_change:+.1f}% "
                            f"en 4h (dirección: {direction}). Conf {original_conf}→{new_conf} < 55 → descartada"
                        )
                        continue
                    analysis["confidence"] = new_conf
                    analysis["reasoning"] = (
                        f"[Precio ya movido {recent_change:+.1f}% en 4h, conf reducida] "
                        + analysis.get("reasoning", "")
                    )
                    logger.info(
                        f"   ⚠️ Momentum: {primary_asset} ya {recent_change:+.1f}% en 4h → "
                        f"conf reducida {original_conf}→{new_conf}"
                    )

            prediction_id = self.tracker.save_prediction(event, current_price)
            if prediction_id:
                event["prediction_id"] = prediction_id
                logger.info(
                    f"   ✅ Predicción #{prediction_id} guardada: {primary_asset} @ {current_price:.2f} ({analysis.get('direction', 'unknown')})"
                )
            else:
                logger.warning(
                    f"   ❌ Predicción NO guardada para {primary_asset}: precio {current_price}, direction {analysis.get('direction', 'unknown')}"
                )

        # Paso 6: Ordenar por criticidad
        logger.info("📈 PASO 6: Ordenando por criticidad...")
        analyzed.sort(key=lambda x: x.get("score", 0), reverse=True)
        for i, event in enumerate(analyzed, 1):
            event["rank"] = i

        # Paso 7: Resolver conflictos de señales contradictorias
        logger.info("⚖️  PASO 7: Resolviendo conflictos de señal...")
        from src.services.signal_resolver import resolve_signals
        pre_count = len(analyzed)
        analyzed = resolve_signals(analyzed)
        logger.info(f"   ✅ {pre_count} → {len(analyzed)} eventos tras resolución")

        logger.info("✅ PIPELINE COMPLETADO")
        return analyzed
