"""
Pipeline principal v2.
Flujo: fetch RSS → deduplicar → scoring → filtrar por activo → analizar con IA → guardar predicciones.

Scope: IBEX 35, ETFs y Criptodivisas únicamente.
Noticias que no hacen match con ningún activo de estas categorías son descartadas.
"""

import logging
import hashlib
import math
import re
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
    "crypto": "BTC",
    "ibex35": "IBEX35",
    "etf": "SPY",
    "mercados": "IBEX35",
    "financial": "IBEX35",
    "finance": "IBEX35",
    "general": "IBEX35",
    "geopolítica": "IBEX35",
    "geopolitical": "IBEX35",
    "conflicto": "IBEX35",
    "energía": "IBEX35",
    "energy": "IBEX35",
    "commodities": "GLD",
}

# --- Fuentes RSS: IBEX 35 / Mercados españoles + Crypto ---
RSS_SOURCES = [
    # --- Mercado español / IBEX 35 ---
    {"name": "Expansión Mercados", "url": "https://e00-expansion.uecdn.es/rss/mercados.xml"},
    {"name": "CincoDías Mercados", "url": "https://cincodias.elpais.com/rss/cincodias/mercados.xml"},
    {"name": "ElEconomista Bolsa", "url": "https://www.eleconomista.es/rss/rss-bolsa-mercados.php"},
    {"name": "Bolsamanía", "url": "https://www.bolsamania.com/rss/todas-las-noticias.xml"},
    {"name": "El Confidencial Mercados", "url": "https://rss.elconfidencial.com/mercados/"},
    {"name": "Investing.com España", "url": "https://es.investing.com/rss/news.rss"},
    # --- Crypto (inglés) ---
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/.rss/full/"},
    # --- Crypto (español) ---
    {"name": "Cointelegraph ES", "url": "https://es.cointelegraph.com/rss"},
    {"name": "CriptoNoticias", "url": "https://www.criptonoticias.com/feed/"},
    {"name": "BeInCrypto ES", "url": "https://es.beincrypto.com/feed/"},
]

# ---------------------------------------------------------------------------
# ASSET_KEYWORDS — diccionario de activos con sus palabras clave de detección.
# Clave: ticker del activo. Valor: lista de keywords (case-insensitive).
# Se usa para asignar el activo primario a una noticia y para filtrar noticias
# que no son relevantes para IBEX 35, ETFs o Criptodivisas.
# ---------------------------------------------------------------------------
ASSET_KEYWORDS: dict[str, list[str]] = {
    # ── IBEX 35 — índice general ────────────────────────────────────────────
    "IBEX35": [
        "ibex", "ibex35", "ibex 35", "bolsa española", "bolsa de madrid",
        "bolsa madrid", "mercado continuo", "bme", "bmex", "cnmv",
        "bolsa de valores española", "renta variable española",
    ],
    # ── IBEX 35 — empresas ──────────────────────────────────────────────────
    "ACS": ["acs actividades", "grupo acs", "acs construccion", "hochtief"],
    "ACX": ["acerinox", "acerinox sa", "columbus stainless"],
    "AENA": ["aena", "aeropuertos españoles", "aeropuerto adolfo suárez", "aeropuerto barajas", "aena sa"],
    "ALM": ["almirall"],
    "AMS": ["amadeus it", "amadeus"],
    "ANA": ["acciona", "acciona energia", "acciona sa"],
    "BBVA": ["bbva", "banco bilbao vizcaya", "bilbao vizcaya argentaria", "banco bilbao"],
    "BKT": ["bankinter", "bankinter sa", "bankinter bank"],
    "CABK": ["caixabank", "la caixa", "caixa bank", "caixabank sa"],
    "CLNX": ["cellnex", "cellnex telecom", "cellnex towers"],
    "COL": ["inmobiliaria colonial", "colonial reit"],
    "ELE": ["endesa", "endesa sa", "enel endesa"],
    "ENG": ["enagás", "enagas", "enagas sa", "enagás transporte"],
    "FDR": ["fluidra"],
    "FER": ["ferrovial", "ferrovial sa", "cintra", "heathrow airport"],
    "GRF": ["grifols", "grifols sa", "grifols plasma"],
    "IAG": ["iag", "iberia airlines", "british airways", "vueling", "aer lingus", "iberia express", "international airlines group"],
    "IBE": ["iberdrola", "iberdrola renovables", "scottish power"],
    "IDR": ["indra sistemas", "indra", "indra sa"],
    "ITX": ["inditex", "grupo inditex", "zara", "amancio ortega", "pull&bear", "massimo dutti", "bershka", "stradivarius"],
    "LOG": ["logista", "compañía de distribución integral logista"],
    "MAP": ["mapfre", "mapfre sa", "mapfre seguros"],
    "MEL": ["meliá hotels", "melia hotels", "meliá", "melia international", "sol meliá"],
    "MRL": ["merlin properties"],
    "MTS": ["arcelormittal", "arcelor mittal", "arcelor", "mittal steel"],
    "NTGY": ["naturgy", "gas natural fenosa", "naturgy energy"],
    "PHM": ["puig brands", "puig beauty"],
    "RED": ["red eléctrica", "red electrica", "ree", "red eléctrica de españa", "redeia"],
    "REP": ["repsol", "repsol ypf", "repsol sinopec"],
    "ROVI": ["laboratorios rovi", "rovi pharma", "rovi"],
    "SAB": ["banco sabadell", "sabadell", "tsb bank", "banco sabadell sa"],
    "SAN": ["banco santander", "grupo santander", "santander bank", "santander"],
    "SGRE": ["siemens gamesa", "gamesa", "siemens gamesa renewable", "sgre"],
    "TEF": ["telefónica", "telefonica", "movistar", "o2 telefonica", "telefónica españa"],
    # ── ETFs ────────────────────────────────────────────────────────────────
    "SPY": ["spy etf", "spdr s&p 500", "s&p 500 etf"],
    "QQQ": ["qqq etf", "invesco qqq", "nasdaq etf", "invesco nasdaq"],
    "GLD": ["gld etf", "spdr gold", "gold etf", "etf oro"],
    "SLV": ["slv etf", "ishares silver", "silver etf", "etf plata"],
    "IWM": ["iwm etf", "russell 2000 etf", "ishares russell 2000"],
    "EWZ": ["ewz etf", "brazil etf", "ishares msci brazil"],
    "EEM": ["eem etf", "emerging markets etf", "ishares msci emerging", "mercados emergentes etf"],
    "VIX": ["vix index", "cboe vix", "fear index", "volatility index", "índice de volatilidad"],
    "ARKK": ["arkk etf", "ark innovation", "cathie wood"],
    "TLT": ["tlt etf", "ishares 20+ year treasury", "treasury bond etf"],
    "XLF": ["xlf etf", "financial select sector", "financial sector etf"],
    "XLE": ["xle etf", "energy select sector etf"],
    # ── Criptodivisas ───────────────────────────────────────────────────────
    "BTC": [
        "bitcoin", "btc", "criptomoneda", "criptomonedas", "crypto",
        "blockchain", "defi", "nft", "stablecoin", "halving",
        "altcoin", "moneda digital", "activo digital",
    ],
    "ETH": ["ethereum", "ether", "eth", "erc-20", "erc20"],
    "XRP": ["ripple", "xrp"],
    "SOL": ["solana"],
    "BNB": ["binance coin", "bnb", "binance smart chain"],
    "ADA": ["cardano"],
    "DOGE": ["dogecoin", "doge"],
    "DOT": ["polkadot"],
    "AVAX": ["avalanche", "avax"],
    "MATIC": ["polygon matic", "polygon network"],
    "LINK": ["chainlink"],
    "UNI": ["uniswap"],
    "LTC": ["litecoin"],
    "ATOM": ["cosmos hub", "cosmos network", "cosmos blockchain"],
    "XLM": ["stellar lumens", "stellar xlm"],
    "ALGO": ["algorand"],
    "FIL": ["filecoin"],
    "NEAR": ["near protocol"],
    "ARB": ["arbitrum"],
    "OP": ["optimism rollup", "optimism network", "optimism l2", "optimism blockchain"],
}



# Tiers de prioridad — un ticker de Nivel 1 siempre gana sobre Nivel 2, etc.
_PRIORITY_TIERS = [
    # Tier 1: Empresas específicas IBEX35
    frozenset({"ACS", "ACX", "AENA", "ALM", "AMS", "ANA", "BBVA", "BKT", "CABK",
               "CLNX", "COL", "ELE", "ENG", "FDR", "FER", "GRF", "IAG", "IBE",
               "IDR", "ITX", "LOG", "MAP", "MEL", "MRL", "MTS", "NTGY", "PHM",
               "RED", "REP", "ROVI", "SAB", "SAN", "SGRE", "TEF"}),
    # Tier 2: Criptos específicas (no BTC)
    frozenset({"ETH", "XRP", "SOL", "BNB", "ADA", "DOGE", "DOT", "AVAX", "MATIC",
               "LINK", "UNI", "LTC", "ATOM", "XLM", "ALGO", "FIL", "NEAR", "ARB", "OP"}),
    # Tier 3: ETFs específicos
    frozenset({"SPY", "QQQ", "GLD", "SLV", "IWM", "EWZ", "EEM", "VIX", "ARKK", "TLT", "XLF", "XLE"}),
    # Tier 4: Genéricos — solo si no hay nada en tiers superiores
    frozenset({"IBEX35", "BTC"}),
]


def _get_ticker_tier(ticker: str) -> int:
    """Devuelve el tier de prioridad de un ticker (0=máxima prioridad, 3=mínima)."""
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
    "ibex35_companies": {
        "keywords": [
            # Empresas IBEX 35 (nombres completos y abreviados)
            "inditex", "zara", "santander", "bbva", "iberdrola", "telefónica", "telefonica",
            "repsol", "caixabank", "bankinter", "sabadell", "mapfre", "endesa", "ferrovial",
            "acciona", "amadeus", "cellnex", "grifols", "acerinox", "aena", "almirall",
            "enagás", "enagas", "fluidra", "logista", "meliá", "melia", "arcelormittal",
            "naturgy", "puig", "red eléctrica", "rovi", "laboratorios rovi", "siemens gamesa",
            "colonial", "indra", "merlin properties", "vueling", "iberia", "movistar",
            "grupo acs", "acs actividades", "acerinox", "ferrovial", "inmobiliaria colonial",
            "fluidra", "merlin", "siemens gamesa", "gamesa", "bankinter", "naturgy",
            # IBEX genérico
            "ibex", "ibex 35", "bolsa española", "bolsa de madrid", "mercado continuo",
            "bolsa madrid", "bme", "cnmv", "prima de riesgo", "bono español",
        ],
        "base_severity": 58,
        "category": "IBEX35",
    },
    "etf_market": {
        "keywords": [
            "etf", "spy", "qqq", "gld", "slv", "iwm", "eem", "ewz",
            "arkk", "tlt", "xlf", "xle", "vix", "ishares", "spdr", "invesco",
            "fondo cotizado", "exchange traded fund",
        ],
        "base_severity": 52,
        "category": "ETF",
    },
    "crypto_market": {
        "keywords": [
            "bitcoin", "ethereum", "crypto", "blockchain", "defi", "nft",
            "stablecoin", "ripple", "xrp", "solana", "cardano", "dogecoin",
            "criptomoneda", "criptomonedas", "moneda digital", "halving",
            "altcoin", "binance", "polkadot", "avalanche", "chainlink",
            "uniswap", "litecoin", "algorand", "filecoin", "arbitrum",
        ],
        "base_severity": 50,
        "category": "CRYPTO",
    },
    "financial_market": {
        "keywords": [
            "stock market", "fed", "interest rate", "inflation", "recession",
            "central bank", "bond market", "yield curve",
            "s&p 500", "nasdaq", "dow jones", "wall street",
            "mercado bursátil", "tipo de interés", "banco central europeo",
            "bce", "bolsa de valores", "renta variable", "renta fija",
        ],
        "base_severity": 48,
        "category": "MERCADOS",
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

        # Paso 3b: Filtrar por activo IBEX35 / ETF / Crypto
        logger.info("🎯 PASO 3b: Filtrando por activos IBEX35/ETF/Crypto...")
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
            f"   ✅ {len(relevant)} eventos relevantes (IBEX35/ETF/Crypto) "
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
        logger.info("💾 PASO 5: Guardando predicciones...")
        for event in analyzed:
            analysis = event.get("analysis", {})
            assets = analysis.get("most_affected_assets", ["UNKNOWN"])
            primary_asset = assets[0] if assets else "UNKNOWN"

            # Validar el activo primario contra la lista conocida
            if primary_asset.upper() not in VALID_ASSETS:
                # Preferir el mejor match por tier entre todos los activos detectados
                suggested = event.get("suggested_asset", "")
                matched = event.get("matched_assets", [])

                all_candidates = ([suggested] if suggested else []) + matched
                valid_candidates = [a for a in all_candidates if a.upper() in VALID_ASSETS]

                if valid_candidates:
                    best = min(valid_candidates, key=lambda a: _get_ticker_tier(a.upper()))
                    logger.warning(
                        f"   Activo IA '{primary_asset}' desconocido → usando mejor match '{best}' "
                        f"(tier={_get_ticker_tier(best.upper())})"
                    )
                    primary_asset = best
                else:
                    category = event.get("category", "general").lower()
                    fallback = CATEGORY_FALLBACK.get(category, "IBEX35")
                    logger.warning(
                        f"   Activo desconocido '{primary_asset}' → fallback '{fallback}'"
                    )
                    primary_asset = fallback

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
