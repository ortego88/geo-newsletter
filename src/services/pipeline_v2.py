"""
Pipeline principal v2.
Flujo: fetch RSS → deduplicar → scoring → analizar con IA → guardar predicciones.
"""

import logging
import hashlib
from datetime import datetime, timedelta, timezone

import feedparser

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
]

# --- Taxonomía de eventos para scoring ---
EVENT_TAXONOMY = {
    "chokepoints_disruption": {
        "keywords": [
            "strait of hormuz", "hormuz", "suez canal", "suez", "strait of malacca",
            "malacca", "bosporus", "bab el-mandeb", "strait", "chokepoint",
            "tanker", "shipping lane", "maritime", "naval blockade", "ormuz",
        ],
        "base_severity": 88,
        "category": "ENERGÍA",
    },
    "oil_supply_shock": {
        "keywords": [
            "oil", "crude", "opec", "petroleum", "barrel", "refinery",
            "pipeline", "petróleo", "brent", "wti", "energy crisis",
            "oil price", "saudi", "iraq", "iran oil", "oil production",
        ],
        "base_severity": 82,
        "category": "ENERGÍA",
    },
    "military_conflict": {
        "keywords": [
            "war", "attack", "missile", "bomb", "military", "troops", "invasion",
            "ceasefire", "airstrike", "combat", "offensive", "armed forces",
            "conflict", "battlefield", "weapon", "nuclear",
        ],
        "base_severity": 85,
        "category": "CONFLICTO",
    },
    "sanctions_trade": {
        "keywords": [
            "sanction", "tariff", "trade war", "embargo", "export ban",
            "import restriction", "trade deal", "wto", "customs", "protectionism",
        ],
        "base_severity": 75,
        "category": "COMERCIO",
    },
    "crypto_market": {
        "keywords": [
            "bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft",
            "stablecoin", "exchange hack", "crypto regulation", "cbdc",
        ],
        "base_severity": 70,
        "category": "CRYPTO",
    },
    "financial_market": {
        "keywords": [
            "stock market", "fed", "interest rate", "inflation", "recession",
            "bank failure", "central bank", "bond market", "yield curve",
            "credit rating", "debt ceiling", "gdp", "unemployment",
        ],
        "base_severity": 72,
        "category": "MERCADOS",
    },
    "geopolitical_tension": {
        "keywords": [
            "geopolit", "diplomatic", "tension", "protest", "coup", "election",
            "government crisis", "political instability", "civil unrest",
        ],
        "base_severity": 65,
        "category": "GEOPOLÍTICA",
    },
}


def _score_event(article: dict) -> tuple[int, str]:
    """Devuelve (score, category) basado en la taxonomía."""
    text = (
        (article.get("title") or "") + " " +
        (article.get("description") or article.get("summary") or "")
    ).lower()

    best_score = 0
    best_category = "GENERAL"

    for event_type, config in EVENT_TAXONOMY.items():
        hits = sum(1 for kw in config["keywords"] if kw in text)
        if hits > 0:
            score = min(99, config["base_severity"] + hits)
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

        logger.info("✅ PIPELINE COMPLETADO")
        return analyzed
