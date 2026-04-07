"""
Pipeline principal v2.
Flujo: fetch RSS → deduplicar → scoring → analizar con IA → guardar predicciones.
"""

import logging
import hashlib
import math
from datetime import datetime, timedelta, timezone

import feedparser

from src.services.content_filter import is_entertainment_noise
from src.services.deduplicator import Deduplicator
from src.services.gpt_analyzer import EventAnalyzer
from src.services.prediction_tracker import PredictionTracker
from src.services.real_price_fetcher import RealPriceFetcher, CRYPTO_IDS, YAHOO_TICKERS

logger = logging.getLogger("geo-newsletter")

# --- Conjunto de activos válidos conocidos ---
VALID_ASSETS = set(CRYPTO_IDS.keys()) | set(YAHOO_TICKERS.keys())

# --- Fallback de activo por categoría cuando el modelo inventa tickers ---
CATEGORY_FALLBACK = {
    "energía": "WTI_OIL",
    "energy": "WTI_OIL",
    "crypto": "BTC",
    "finance": "SPX",
    "mercados": "SPX",
    "financial": "SPX",
    "commodities": "GOLD",
    "geopolítica": "SPX",
    "geopolitical": "SPX",
    "conflicto": "SPX",
    "general": "SPX",
}

# --- Fuentes RSS ---
RSS_SOURCES = [
    {"name": "Reuters News", "url": "https://feeds.reuters.com/reuters/worldNews"},
    {"name": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "Bloomberg News", "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "AP News", "url": "https://apnews.com/hub/world-news"},
    {"name": "BBC News", "url": "http://feeds.bbc.co.uk/news/world/rss.xml"},
    {"name": "Sky News", "url": "http://feeds.skynews.com/feeds/rss/world.xml"},
    {"name": "Reuters Energy", "url": "https://feeds.reuters.com/reuters/businessNews?taxonomy=10207"},
    {"name": "Oil & Gas Journal", "url": "https://www.ogj.com/feed"},
    {"name": "OPEC Official", "url": "https://www.opec.org/rss/feeds"},
    {"name": "CoinMarketCap", "url": "https://coinmarketcap.com/feed"},
    {"name": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories/"},
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "Financial Times", "url": "https://feeds.ft.com/markets"},
    {"name": "GDELT", "url": "https://api.gdeltproject.org/api/v2/top10/top10?OUTPUTMODE=RSS"},
    {"name": "ACLED", "url": "https://acleddata.com/feed/"},
    # --- Fuentes mercado español ---
    {"name": "Expansión Mercados", "url": "https://e00-expansion.uecdn.es/rss/mercados.xml"},
    {"name": "CincoDías Mercados", "url": "https://cincodias.elpais.com/rss/mercados/"},
    {"name": "ElEconomista Mercados", "url": "https://www.eleconomista.es/rss/rss-mercados.php"},
    {"name": "Investing.com España", "url": "https://es.investing.com/rss/news.rss"},
    # --- Fuentes crypto en español ---
    {"name": "CriptoNoticias", "url": "https://www.criptonoticias.com/feed/"},
    {"name": "Cointelegraph ES", "url": "https://es.cointelegraph.com/rss"},
    {"name": "BeInCrypto ES", "url": "https://es.beincrypto.com/feed/"},
    # --- Fuente crypto adicional (inglés) ---
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/feed"},
]

# --- Taxonomía de eventos para scoring ---
EVENT_TAXONOMY = {
    "chokepoints_disruption": {
        "keywords": [
            "strait of hormuz", "hormuz", "suez canal", "suez", "strait of malacca",
            "malacca", "bosporus", "bab el-mandeb", "strait", "chokepoint",
            "tanker", "shipping lane", "maritime", "naval blockade", "ormuz",
        ],
        "base_severity": 75,
        "category": "ENERGÍA",
    },
    "oil_supply_shock": {
        "keywords": [
            "oil", "crude", "opec", "petroleum", "barrel", "refinery",
            "pipeline", "petróleo", "brent", "wti", "energy crisis",
            "oil price", "saudi", "iraq", "iran oil", "oil production",
            "crudo", "gasolina", "refinería", "precio del petróleo",
        ],
        "base_severity": 65,
        "category": "ENERGÍA",
    },
    "military_conflict": {
        "keywords": [
            "war", "attack", "missile", "bomb", "military", "troops", "invasion",
            "ceasefire", "airstrike", "combat", "offensive", "armed forces",
            "conflict", "battlefield", "weapon", "nuclear",
        ],
        "base_severity": 70,
        "category": "CONFLICTO",
    },
    "sanctions_trade": {
        "keywords": [
            "sanction", "tariff", "trade war", "embargo", "export ban",
            "import restriction", "trade deal", "wto", "customs", "protectionism",
            "arancel", "aranceles", "guerra comercial", "sanciones",
        ],
        "base_severity": 58,
        "category": "COMERCIO",
    },
    "crypto_market": {
        "keywords": [
            "bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft",
            "stablecoin", "exchange hack", "crypto regulation", "cbdc",
            "ripple", "xrp", "solana", "cardano", "dogecoin",
            "criptomoneda", "criptomonedas", "moneda digital", "halving",
            "altcoin", "minería crypto", "regulación crypto",
        ],
        "base_severity": 50,
        "category": "CRYPTO",
    },
    "financial_market": {
        "keywords": [
            "stock market", "fed", "interest rate", "inflation", "recession",
            "bank failure", "central bank", "bond market", "yield curve",
            "credit rating", "debt ceiling", "gdp", "unemployment",
            "ibex", "bolsa española", "bolsa madrid", "ftse", "dax",
            "s&p 500", "nasdaq", "dow jones", "wall street",
            "etf", "spy", "qqq",
            "mercado bursátil", "tipo de interés", "banco central europeo",
            "bce", "mercado continuo", "cnmv", "prima de riesgo",
            "bolsa de valores", "renta variable", "renta fija",
        ],
        "base_severity": 55,
        "category": "MERCADOS",
    },
    "geopolitical_tension": {
        "keywords": [
            "geopolit", "diplomatic", "tension", "protest", "coup", "election",
            "government crisis", "political instability", "civil unrest",
            "golpe de estado", "inestabilidad política", "crisis política",
            "elecciones", "tensión diplomática",
        ],
        "base_severity": 45,
        "category": "GEOPOLÍTICA",
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
    """
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

        # Paso 1: Fetch
        logger.info("📰 PASO 1: Recolectando noticias...")
        articles = _fetch_rss(minutes=minutes)
        logger.info(f"   ✅ {len(articles)} noticias encontradas")

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
        logger.info("💾 PASO 5: Guardando predicciones...")
        for event in analyzed:
            analysis = event.get("analysis", {})
            assets = analysis.get("most_affected_assets", ["UNKNOWN"])
            primary_asset = assets[0] if assets else "UNKNOWN"

            # Validar el activo primario contra la lista conocida
            if primary_asset.upper() not in VALID_ASSETS:
                category = event.get("category", "general").lower()
                fallback = CATEGORY_FALLBACK.get(category, "SPX")
                logger.warning(
                    f"   Activo desconocido '{primary_asset}' → usando fallback '{fallback}' "
                    f"(categoría: {category})"
                )
                primary_asset = fallback

            current_price = self.price_fetcher.get_price(primary_asset)
            if current_price is None:
                current_price = 100.0

            prediction_id = self.tracker.save_prediction(event, current_price)
            if prediction_id:
                event["prediction_id"] = prediction_id
                logger.info(
                    f"   Predicción #{prediction_id}: {primary_asset} @ {current_price:.2f}"
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
