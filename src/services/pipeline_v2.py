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
    # ── Criptodivisas — Top 35 por capitalización ───────────────────────────
    "BTC": [
        "bitcoin", "btc", "halving", "satoshi",
        "bitcoin etf", "bitcoin spot", "btc etf",
    ],
    "ETH": ["ethereum", "ether", "eth", "erc-20", "erc20", "ethereum etf", "vitalik"],
    "XRP": ["ripple", "xrp", "ripple labs"],
    "SOL": ["solana", "sol token"],
    "BNB": ["binance coin", "bnb", "binance smart chain", "bsc"],
    "ADA": ["cardano", "ada token", "charles hoskinson"],
    "DOGE": ["dogecoin", "doge", "elon musk doge"],
    "DOT": ["polkadot", "dot token", "parachains"],
    "AVAX": ["avalanche", "avax", "avalanche subnet"],
    "MATIC": ["polygon matic", "polygon network", "polygon labs", "pol token"],
    "LINK": ["chainlink", "link token", "chainlink oracle"],
    "UNI": ["uniswap", "uni token", "uniswap governance"],
    "LTC": ["litecoin", "ltc token"],
    "ATOM": ["cosmos hub", "cosmos network", "cosmos blockchain", "atom token"],
    "XLM": ["stellar lumens", "stellar xlm", "stellar network"],
    "ALGO": ["algorand", "algo token"],
    "FIL": ["filecoin", "fil token"],
    "NEAR": ["near protocol", "near token"],
    "ARB": ["arbitrum", "arb token", "arbitrum one"],
    "OP": ["optimism rollup", "optimism network", "optimism l2", "optimism blockchain"],
    # ── Nuevas criptomonedas ────────────────────────────────────────────────
    "SUI": ["sui network", "sui blockchain", "sui token"],
    "APT": ["aptos", "aptos labs", "apt token"],
    "SEI": ["sei network", "sei blockchain", "sei token"],
    "TIA": ["celestia", "tia token", "celestia modular"],
    "INJ": ["injective", "inj token", "injective protocol"],
    "RENDER": ["render network", "render token", "rndr"],
    "FET": ["fetch.ai", "fetch ai", "artificial superintelligence", "fet token"],
    "PEPE": ["pepe coin", "pepe token", "pepe memecoin"],
    "WIF": ["dogwifhat", "wif token"],
    "SHIB": ["shiba inu", "shib token", "shibarium"],
    "TON": ["toncoin", "ton network", "telegram open network", "ton blockchain"],
    "TRX": ["tron", "trx token", "tron network", "justin sun"],
    "HBAR": ["hedera", "hbar token", "hedera hashgraph"],
    "ICP": ["internet computer", "icp token", "dfinity"],
    "AAVE": ["aave", "aave protocol", "aave lending"],
    # ── Genérico crypto (catch-all para noticias de mercado general) ────────
    "CRYPTO_MARKET": [
        "criptomoneda", "criptomonedas", "crypto", "cryptocurrency",
        "blockchain", "defi", "nft", "stablecoin", "altcoin",
        "moneda digital", "activo digital", "web3", "dex", "cex",
        "mercado crypto", "crypto market",
    ],
}



# Tiers de prioridad — un ticker de Nivel 1 siempre gana sobre Nivel 2, etc.
_PRIORITY_TIERS = [
    # Tier 1: Criptos específicas de alta cap (BTC, ETH, SOL, etc.)
    frozenset({"BTC", "ETH", "XRP", "SOL", "BNB", "ADA", "TON", "DOGE", "DOT",
               "AVAX", "LINK", "SHIB", "TRX", "MATIC"}),
    # Tier 2: Criptos de media cap
    frozenset({"UNI", "LTC", "ATOM", "XLM", "ALGO", "FIL", "NEAR", "ARB", "OP",
               "SUI", "APT", "SEI", "TIA", "INJ", "RENDER", "FET", "HBAR", "ICP", "AAVE"}),
    # Tier 3: Memecoins y baja cap
    frozenset({"PEPE", "WIF"}),
    # Tier 4: Genérico crypto — solo si no hay nada en tiers superiores
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
    2. Dentro del mismo tier: mayor número de keyword hits
    3. En empate de hits dentro del mismo tier: el primero en ASSET_KEYWORDS

    Devuelve (primary_ticker, [all_matched_tickers]).
    """
    title = article.get("title") or ""
    description = article.get("description") or article.get("summary") or ""
    text = (title + " " + description).lower()

    hits_per_ticker: dict[str, int] = {}
    for ticker, keywords in ASSET_KEYWORDS.items():
        count = sum(1 for kw in keywords if _kw_matches(kw, text))
        if count > 0:
            hits_per_ticker[ticker] = count

    if not hits_per_ticker:
        return None, []

    # Ordenar por: 1) tier ascendente (0=mejor), 2) hits descendente
    sorted_tickers = sorted(
        hits_per_ticker.items(),
        key=lambda x: (_get_ticker_tier(x[0]), -x[1]),
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
        ],
        "base_severity": 55,
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

        # Paso 4: Analizar con IA
        logger.info("🤖 PASO 4: Analizando con IA (Ollama)...")
        analyzed = []
        for i, event in enumerate(scored, 1):
            logger.info(f"   [{i}/{len(scored)}] Analizando: {event['title'][:55]}...")
            analysis = self.analyzer.analyze(event)
            event["analysis"] = analysis
            analyzed.append(event)

        logger.info(f"   ✅ {len(analyzed)} eventos analizados")

        # Paso 5: Guardar predicciones con precios reales
        # Guardar predicciones con umbral moderado para más cobertura
        logger.info("💾 PASO 5: Guardando predicciones...")
        for event in analyzed:
            analysis = event.get("analysis", {})

            event_score = event.get("score", 0)
            event_confidence = analysis.get("confidence", 0)
            if event_score < 45 or event_confidence < 55:
                logger.info(
                    f"   ⏭️ No guardada (score={event_score}, conf={event_confidence}): "
                    f"{event.get('title', '')[:55]}"
                )
                continue

            assets = analysis.get("most_affected_assets", ["UNKNOWN"])
            primary_asset = assets[0] if assets else "UNKNOWN"

            # Validar el activo primario contra la lista conocida
            if primary_asset.upper() not in VALID_ASSETS:
                # Preferir el mejor match por tier entre todos los activos detectados.
                # matched_assets ya está ordenado por tier (ascendente) y hits (descendente)
                # desde _match_asset(), por lo que el primer válido es el mejor candidato.
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

            current_price = self.price_fetcher.get_price(primary_asset)
            if current_price is None:
                logger.warning(
                    f"   No se pudo obtener precio para {primary_asset}, omitiendo predicción"
                )
                continue

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
