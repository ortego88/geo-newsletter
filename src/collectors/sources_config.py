"""
Configuración centralizada de fuentes de noticias
Incluye: noticias generales, energía, crypto, finanzas, OSINT
"""

NEWS_SOURCES = [
    # ========== NOTICIAS GENERALES (Reuters, Bloomberg, AP News, etc) ==========
    {
        "name": "Reuters News",
        "type": "RSS",
        "url": "https://feeds.reuters.com/reuters/worldNews",
        "priority": 5,
        "category": "general",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Reuters Business",
        "type": "RSS",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "priority": 5,
        "category": "general",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Bloomberg News",
        "type": "RSS",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
        "priority": 5,
        "category": "general",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "AP News",
        "type": "RSS",
        "url": "https://apnews.com/hub/world-news",
        "priority": 4,
        "category": "general",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "BBC News",
        "type": "RSS",
        "url": "http://feeds.bbc.co.uk/news/world/rss.xml",
        "priority": 4,
        "category": "general",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Sky News",
        "type": "RSS",
        "url": "http://feeds.skynews.com/feeds/rss/world.xml",
        "priority": 4,
        "category": "general",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    
    # ========== NOTICIAS DE ENERGÍA ==========
    {
        "name": "Energy Intelligence",
        "type": "RSS",
        "url": "https://www.energyintel.com/rss",
        "priority": 5,
        "category": "energy",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Reuters Energy",
        "type": "RSS",
        "url": "https://feeds.reuters.com/reuters/businessNews?taxonomy=10207",
        "priority": 5,
        "category": "energy",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Oil & Gas Journal",
        "type": "RSS",
        "url": "https://www.ogj.com/feed",
        "priority": 4,
        "category": "energy",
        "update_frequency_minutes": 60,
        "trusted": True,
    },
    {
        "name": "S&P Global Platts",
        "type": "RSS",
        "url": "https://www.spglobal.com/platts/rss/feeds",
        "priority": 4,
        "category": "energy",
        "update_frequency_minutes": 60,
        "trusted": True,
    },
    {
        "name": "OPEC Official",
        "type": "RSS",
        "url": "https://www.opec.org/rss/feeds",
        "priority": 5,
        "category": "energy",
        "update_frequency_minutes": 120,
        "trusted": True,
    },
    
    # ========== CRIPTOMONEDAS ==========
    {
        "name": "CoinGecko Top 100",
        "type": "API",
        "url": "https://api.coingecko.com/api/v3/",
        "priority": 4,
        "category": "crypto",
        "update_frequency_minutes": 60,
        "requires_key": False,
        "trusted": True,
    },
    {
        "name": "CoinMarketCap News",
        "type": "RSS",
        "url": "https://coinmarketcap.com/feed",
        "priority": 4,
        "category": "crypto",
        "update_frequency_minutes": 60,
        "trusted": True,
    },
    {
        "name": "Crypto News Feed",
        "type": "RSS",
        "url": "https://cointelegraph.com/feed",
        "priority": 3,
        "category": "crypto",
        "update_frequency_minutes": 30,
        "trusted": False,
    },
    {
        "name": "CriptoNoticias",
        "type": "RSS",
        "url": "https://www.criptonoticias.com/feed/",
        "priority": 4,
        "category": "crypto",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Cointelegraph ES",
        "type": "RSS",
        "url": "https://es.cointelegraph.com/rss",
        "priority": 3,
        "category": "crypto",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "BeInCrypto ES",
        "type": "RSS",
        "url": "https://es.beincrypto.com/feed/",
        "priority": 3,
        "category": "crypto",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    
    # ========== FINANZAS Y MERCADOS ==========
    {
        "name": "Yahoo Finance",
        "type": "API",
        "url": "https://query1.finance.yahoo.com/",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 60,
        "trusted": True,
    },
    {
        "name": "MarketWatch",
        "type": "RSS",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "CNBC",
        "type": "RSS",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Financial Times",
        "type": "RSS",
        "url": "https://feeds.ft.com/markets",
        "priority": 5,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Expansión Mercados",
        "type": "RSS",
        "url": "https://e00-expansion.uecdn.es/rss/mercados.xml",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "CincoDías Mercados",
        "type": "RSS",
        "url": "https://cincodias.elpais.com/rss/mercados/",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "ElEconomista Mercados",
        "type": "RSS",
        "url": "https://www.eleconomista.es/rss/rss-mercados.php",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    {
        "name": "Investing.com España",
        "type": "RSS",
        "url": "https://es.investing.com/rss/news.rss",
        "priority": 4,
        "category": "finance",
        "update_frequency_minutes": 30,
        "trusted": True,
    },
    
    # ========== OSINT - RECOLECCIÓN DE INTELIGENCIA ABIERTA ==========
    {
        "name": "GDELT",
        "type": "OSINT",
        "url": "https://www.gdeltproject.org/",
        "priority": 4,
        "category": "osint",
        "update_frequency_minutes": 15,
        "trusted": True,
        "description": "Global Database of Events, Language and Tone"
    },
    {
        "name": "ACLED",
        "type": "OSINT",
        "url": "https://acleddata.com/",
        "priority": 4,
        "category": "osint",
        "update_frequency_minutes": 60,
        "trusted": True,
        "description": "Armed Conflict Location Event Data"
    },
    {
        "name": "LiveUA Map",
        "type": "OSINT",
        "url": "https://liveuamap.com/",
        "priority": 3,
        "category": "osint",
        "update_frequency_minutes": 30,
        "trusted": True,
        "description": "Real-time conflict tracking"
    },
    {
        "name": "Crisis24",
        "type": "OSINT",
        "url": "https://www.controlrisks.com/",
        "priority": 3,
        "category": "osint",
        "update_frequency_minutes": 120,
        "trusted": True,
        "description": "Crisis management and risk assessment"
    },
    {
        "name": "AIS Shipping",
        "type": "OSINT",
        "url": "https://www.marinetraffic.com/",
        "priority": 3,
        "category": "osint",
        "update_frequency_minutes": 60,
        "trusted": True,
        "description": "Real-time ship tracking"
    },
    {
        "name": "FIRMS Satellites",
        "type": "OSINT",
        "url": "https://firms.modaps.eosdis.nasa.gov/",
        "priority": 3,
        "category": "osint",
        "update_frequency_minutes": 180,
        "trusted": True,
        "description": "Fire detection via satellite"
    },
]

# Categorías disponibles
CATEGORIES = {
    "general": "Noticias generales internacionales",
    "energy": "Noticias de energía y petróleo",
    "crypto": "Criptomonedas y blockchain",
    "finance": "Mercados financieros y stocks",
    "osint": "Intelligence abierta (OSINT)",
}

# Funciones de utilidad
def get_sources_by_category(category: str):
    """Obtiene fuentes por categoría"""
    return [s for s in NEWS_SOURCES if s.get("category") == category]

def get_trusted_sources():
    """Obtiene solo fuentes confiables"""
    return [s for s in NEWS_SOURCES if s.get("trusted", False)]

def get_high_priority_sources():
    """Obtiene fuentes con prioridad alta (4-5)"""
    return [s for s in NEWS_SOURCES if s.get("priority", 0) >= 4]

def get_sources_by_frequency(minutes: int):
    """Obtiene fuentes que se actualizan cada X minutos o más frecuentemente"""
    return [s for s in NEWS_SOURCES if s.get("update_frequency_minutes", 999) <= minutes]