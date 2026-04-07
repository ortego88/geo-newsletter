"""
Formateador de alertas para el sistema geo-newsletter.
AssetPriceFetcher intenta obtener precios reales con RealPriceFetcher
y cae al mock solo si el precio real no está disponible.
"""

import logging
import re
from datetime import datetime

import pytz

from src.services.real_price_fetcher import RealPriceFetcher

try:
    from src.services.translator import TitleTranslator
except Exception:
    TitleTranslator = None

logger = logging.getLogger("alert_formatter")

_MADRID_TZ = pytz.timezone("Europe/Madrid")


def _now_madrid():
    return datetime.now(_MADRID_TZ)


# Module-level constant for IBEX 35 stocks that trade in euros
_IBEX35_COMPANY_SYMBOLS = frozenset({
    "ACS", "ACX", "AENA", "ALM", "AMS", "ANA", "BBVA", "BKT", "CABK",
    "CLNX", "COL", "ELE", "ENG", "FDR", "FER", "GRF", "IAG", "IBE",
    "IDR", "ITX", "LOG", "MAP", "MEL", "MRL", "MTS", "NTGY", "PHM",
    "RED", "REP", "ROVI", "SAB", "SAN", "SGRE", "TEF",
})
MOCK_PRICES = {
    # Crypto
    "BTC": 62450.0,
    "ETH": 3280.0,
    "XRP": 0.52,
    "SOL": 145.0,
    "ADA": 0.45,
    "BNB": 580.0,
    "DOGE": 0.12,
    "DOT": 7.0,
    "AVAX": 25.0,
    "MATIC": 0.55,
    "LINK": 14.0,
    "UNI": 8.0,
    "LTC": 85.0,
    "ATOM": 6.0,
    "XLM": 0.10,
    "ALGO": 0.15,
    "FIL": 4.5,
    "NEAR": 4.0,
    "ARB": 0.75,
    "OP": 1.0,
    # Índices
    "SPX": 5210.0,
    "SP500": 5210.0,
    "INDU": 38500.0,
    "CCMP": 16400.0,
    "NASDAQ": 16400.0,
    "FTSE": 7800.0,
    "DAX": 17500.0,
    "IBEX35": 11200.0,
    "IBEX": 11200.0,
    # Volatilidad
    "VIX": 18.0,
    # Commodities
    "GOLD": 2350.0,
    "SILVER": 28.50,
    # Bonos
    "US10Y": 4.35,
    "US2Y": 4.85,
    "BONDS": 4.35,
    # ETFs
    "SPY": 520.0,
    "QQQ": 440.0,
    "GLD": 215.0,
    "SLV": 25.0,
    "IWM": 200.0,
    "DIA": 385.0,
    "EEM": 42.0,
    "EWZ": 28.0,
    "VTI": 250.0,
    "ARKK": 45.0,
    "TLT": 90.0,
    "XLF": 44.0,
    "XLE": 95.0,
    # ── IBEX 35 empresas (precios en €, aproximados) ────────────────────────
    "ACS": 43.0,
    "ACX": 10.0,
    "AENA": 175.0,
    "ALM": 4.0,
    "AMS": 75.0,
    "ANA": 16.0,
    "BBVA": 10.0,
    "BKT": 7.0,
    "CABK": 7.0,
    "CLNX": 30.0,
    "COL": 6.0,
    "ELE": 22.0,
    "ENG": 14.0,
    "FDR": 22.0,
    "FER": 45.0,
    "GRF": 7.0,
    "IAG": 3.0,
    "IBE": 13.0,
    "IDR": 14.0,
    "ITX": 50.0,
    "LOG": 40.0,
    "MAP": 3.0,
    "MEL": 8.0,
    "MRL": 10.0,
    "MTS": 28.0,
    "NTGY": 24.0,
    "PHM": 20.0,
    "RED": 16.0,
    "REP": 13.0,
    "ROVI": 47.0,
    "SAB": 2.0,
    "SAN": 5.0,
    "SGRE": 23.0,
    "TEF": 4.0,
}

# --- Iconos por tipo de activo ---
ASSET_ICONS = {
    # Crypto
    "BTC": "🪙",
    "ETH": "🔷",
    "XRP": "💧",
    "SOL": "☀️",
    "ADA": "🔵",
    "BNB": "🟡",
    "DOGE": "🐶",
    "DOT": "⚫",
    "AVAX": "🔺",
    "MATIC": "🟣",
    "LINK": "🔗",
    "UNI": "🦄",
    "LTC": "🥈",
    "ATOM": "⚛️",
    "XLM": "⭐",
    "ALGO": "🔷",
    "FIL": "📁",
    "NEAR": "🌐",
    "ARB": "🔵",
    "OP": "🔴",
    # Índices
    "SPX": "📈",
    "SP500": "📈",
    "INDU": "🏭",
    "CCMP": "💻",
    "NASDAQ": "💻",
    "FTSE": "🇬🇧",
    "DAX": "🇩🇪",
    "IBEX35": "🇪🇸",
    "IBEX": "🇪🇸",
    # Volatilidad
    "VIX": "⚡",
    # Commodities
    "GOLD": "🥇",
    "SILVER": "🥈",
    # Bonos
    "US10Y": "📊",
    "US2Y": "📊",
    "BONDS": "📊",
    # ETFs
    "SPY": "📊",
    "QQQ": "📊",
    "GLD": "📊",
    "SLV": "📊",
    "IWM": "📊",
    "DIA": "📊",
    "EEM": "📊",
    "EWZ": "📊",
    "VTI": "📊",
    "ARKK": "🚀",
    "TLT": "📊",
    "XLF": "🏦",
    "XLE": "⚡",
    # ── IBEX 35 empresas ────────────────────────────────────────────────────
    "ACS": "🏗️",
    "ACX": "🔩",
    "AENA": "✈️",
    "ALM": "💊",
    "AMS": "💻",
    "ANA": "🌱",
    "BBVA": "🏦",
    "BKT": "🏦",
    "CABK": "🏦",
    "CLNX": "📡",
    "COL": "🏢",
    "ELE": "⚡",
    "ENG": "🔵",
    "FDR": "💧",
    "FER": "🌉",
    "GRF": "🩸",
    "IAG": "✈️",
    "IBE": "⚡",
    "IDR": "💻",
    "ITX": "👗",
    "LOG": "📦",
    "MAP": "🛡️",
    "MEL": "🏨",
    "MRL": "🏢",
    "MTS": "⚙️",
    "NTGY": "🔥",
    "PHM": "🧴",
    "RED": "⚡",
    "REP": "⛽",
    "ROVI": "💉",
    "SAB": "🏦",
    "SAN": "🏦",
    "SGRE": "🌬️",
    "TEF": "📱",
}

# --- Nombres legibles en español ---
ASSET_NAMES = {
    # Crypto
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "XRP": "Ripple",
    "SOL": "Solana",
    "ADA": "Cardano",
    "BNB": "Binance Coin",
    "DOGE": "Dogecoin",
    "DOT": "Polkadot",
    "AVAX": "Avalanche",
    "MATIC": "Polygon",
    "LINK": "Chainlink",
    "UNI": "Uniswap",
    "LTC": "Litecoin",
    "ATOM": "Cosmos",
    "XLM": "Stellar",
    "ALGO": "Algorand",
    "FIL": "Filecoin",
    "NEAR": "NEAR Protocol",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    # Índices
    "SPX": "S&P 500",
    "SP500": "S&P 500",
    "INDU": "Dow Jones",
    "CCMP": "Nasdaq",
    "NASDAQ": "Nasdaq 100",
    "FTSE": "FTSE 100",
    "DAX": "DAX 40",
    "IBEX35": "IBEX 35",
    "IBEX": "IBEX 35",
    # Volatilidad
    "VIX": "CBOE VIX (Volatilidad)",
    # Commodities
    "GOLD": "Oro",
    "SILVER": "Plata",
    # Bonos
    "US10Y": "Bono Tesoro 10Y",
    "US2Y": "Bono Tesoro 2Y",
    "BONDS": "Bonos USA",
    # ETFs
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco Nasdaq 100 ETF",
    "GLD": "SPDR Gold ETF",
    "SLV": "iShares Silver ETF",
    "IWM": "iShares Russell 2000 ETF",
    "DIA": "SPDR Dow Jones ETF",
    "EEM": "iShares Emerging Markets ETF",
    "EWZ": "iShares MSCI Brazil ETF",
    "VTI": "Vanguard Total Stock Market ETF",
    "ARKK": "ARK Innovation ETF",
    "TLT": "iShares 20+ Year Treasury ETF",
    "XLF": "Financial Select Sector ETF",
    "XLE": "Energy Select Sector ETF",
    # ── IBEX 35 empresas ────────────────────────────────────────────────────
    "ACS": "ACS Actividades",
    "ACX": "Acerinox",
    "AENA": "AENA",
    "ALM": "Almirall",
    "AMS": "Amadeus IT",
    "ANA": "Acciona",
    "BBVA": "BBVA",
    "BKT": "Bankinter",
    "CABK": "CaixaBank",
    "CLNX": "Cellnex",
    "COL": "Inmobiliaria Colonial",
    "ELE": "Endesa",
    "ENG": "Enagás",
    "FDR": "Fluidra",
    "FER": "Ferrovial",
    "GRF": "Grifols",
    "IAG": "IAG (Iberia / British Airways)",
    "IBE": "Iberdrola",
    "IDR": "Indra Sistemas",
    "ITX": "Inditex",
    "LOG": "Logista",
    "MAP": "Mapfre",
    "MEL": "Meliá Hotels",
    "MRL": "Merlin Properties",
    "MTS": "ArcelorMittal",
    "NTGY": "Naturgy",
    "PHM": "Puig",
    "RED": "Red Eléctrica (REE)",
    "REP": "Repsol",
    "ROVI": "Laboratorios Rovi",
    "SAB": "Banco Sabadell",
    "SAN": "Banco Santander",
    "SGRE": "Siemens Gamesa",
    "TEF": "Telefónica",
}

# --- Traducción básica de inglés a español para el campo reasoning ---
_EN_ES = {
    "positive impact": "impacto positivo",
    "negative impact": "impacto negativo",
    "oil prices": "precios del petróleo",
    "crude oil": "petróleo crudo",
    "natural gas": "gas natural",
    "financial markets": "mercados financieros",
    "stock market": "bolsa de valores",
    "cryptocurrency": "criptomoneda",
    "bitcoin": "bitcoin",
    "supply disruption": "interrupción de suministro",
    "could lead": "podría llevar",
    "will likely": "probablemente",
    "geopolitical": "geopolítico",
    "conflict": "conflicto",
    "sanctions": "sanciones",
    "increased demand": "aumento de demanda",
    "decreased demand": "caída de demanda",
    "bullish": "alcista",
    "bearish": "bajista",
    "volatility": "volatilidad",
    "investors": "inversores",
    "market": "mercado",
    "increase": "aumento",
    "decrease": "disminución",
    "disruption": "disrupción",
    "supply": "suministro",
    "demand": "demanda",
    "region": "región",
    "decision": "decisión",
    "suggests": "sugiere",
    "potentially": "potencialmente",
    "uncertainty": "incertidumbre",
    "tensions": "tensiones",
    "tension": "tensión",
    "rise": "subida",
    "fall": "caída",
    "risk": "riesgo",
    "price": "precio",
    "significant": "significativo",
    "major": "importante",
    "minor": "menor",
    "likely": "probable",
    "expected": "esperado",
    "This ": "Esto ",
    "The ": "El ",
    "geopolitical tensions": "tensiones geopolíticas",
    "oil prices to drop": "caída en los precios del petróleo",
    "oil prices to rise": "subida en los precios del petróleo",
    "are causing": "están causando",
    "is causing": "está causando",
    "regarding iran": "respecto a Irán",
    "could cause": "podría causar",
    "is expected to": "se espera que",
    "are expected to": "se espera que",
    "due to": "debido a",
    "as a result of": "como resultado de",
    "leading to": "llevando a",
    "resulting in": "resultando en",
    "in response to": "en respuesta a",
    "amid concerns": "ante las preocupaciones",
    "amid": "en medio de",
    "pushing": "impulsando",
    "boosting": "impulsando al alza",
    "weighing on": "presionando a la baja",
    "pressuring": "presionando",
    "safe-haven": "refugio seguro",
    "safe haven": "refugio seguro",
    "flight to safety": "huida hacia activos refugio",
    "risk-off": "aversión al riesgo",
    "risk off": "aversión al riesgo",
    "risk-on": "apetito por el riesgo",
    "risk on": "apetito por el riesgo",
    "hawkish": "restrictivo",
    "dovish": "expansivo",
    "interest rates": "tipos de interés",
    "trade war": "guerra comercial",
    "tariffs": "aranceles",
    "tariff": "arancel",
    "barrel": "barril",
    "gold prices": "precio del oro",
    "bond yields": "rendimientos de los bonos",
    "treasury yields": "rendimientos del Tesoro",
    "dollar": "dólar",
    "recession fears": "temores de recesión",
    "economic growth": "crecimiento económico",
    "production cuts": "recortes de producción",
    "output cuts": "recortes de producción",
    "supply cuts": "recortes de suministro",
    "ceasefire deal": "acuerdo de alto el fuego",
    "peace talks": "negociaciones de paz",
    "nuclear deal": "acuerdo nuclear",
    "sanctions relief": "alivio de sanciones",
    "military escalation": "escalada militar",
    "drone attack": "ataque con drones",
    "missile strike": "ataque con misiles",
    "causing": "causando",
    "decline": "descenso",
    "surge": "repunte",
    "crash": "colapso",
    "rebound": "rebote",
    "plunge": "desplome",
    "soar": "dispararse",
    "fears": "temores",
    "concerns": "preocupaciones",
    "outlook": "perspectivas",
    "forecast": "previsión",
    "warning": "advertencia",
    "agreement": "acuerdo",
    "threat": "amenaza",
    "Iran": "Irán",
    "Russia": "Rusia",
    "Ukraine": "Ucrania",
    "Saudi": "Arabia Saudí",
    "Federal Reserve": "Reserva Federal",
    "White House": "Casa Blanca",
    "crude": "petróleo crudo",
    "drop": "caída",
}


def translate_reasoning(text: str) -> str:
    """Traducción básica inglés→español para el campo reasoning (red de seguridad)."""
    if not text:
        return text
    result = text
    # Sort by length descending so longer phrases match before shorter substrings
    sorted_pairs = sorted(_EN_ES.items(), key=lambda x: len(x[0]), reverse=True)
    for en, es in sorted_pairs:
        pattern = re.compile(re.escape(en), re.IGNORECASE)
        result = pattern.sub(es, result)
    if len(result) > 1:
        result = result[0].upper() + result[1:]
    elif result:
        result = result.upper()
    return result[:300]


def _translate_title(title: str) -> str:
    """Traduce un título al español usando TitleTranslator si está disponible."""
    if TitleTranslator is not None:
        try:
            return TitleTranslator.translate(title)
        except Exception as e:
            logger.debug(f"Error traduciendo título: {e}")
    return title


class AssetPriceFetcher:
    """
    Obtiene precios de activos.
    Intenta primero con RealPriceFetcher; cae a MOCK_PRICES si falla.
    """

    def __init__(self):
        self._real = RealPriceFetcher()

    def get_price(self, asset: str) -> float:
        real_price = None
        try:
            real_price = self._real.get_price(asset)
        except Exception as e:
            logger.warning(f"Error obteniendo precio real para {asset}: {e}")

        if real_price is not None:
            return real_price

        mock = MOCK_PRICES.get(asset.upper())
        if mock is not None:
            logger.debug(f"Usando precio mock para {asset}: {mock}")
            return mock

        logger.warning(f"Sin precio disponible para {asset}, usando 0.0")
        return 0.0

    def get_formatted_price(self, asset: str) -> str:
        price = self.get_price(asset)
        asset_upper = asset.upper()
        if asset_upper in ("BTC", "ETH", "GOLD"):
            return f"${price:,.0f}"
        if asset_upper in ("SPX", "SP500", "INDU", "CCMP", "NASDAQ", "FTSE", "DAX", "IBEX35", "IBEX"):
            return f"{price:,.0f}"
        # IBEX 35 companies trade in euros
        if asset_upper in _IBEX35_COMPANY_SYMBOLS:
            if price >= 100:
                return f"€{price:,.0f}"
            return f"€{price:.2f}"
        if price >= 1000:
            return f"${price:,.0f}"
        if price >= 1:
            return f"${price:.2f}"
        return f"${price:.4f}"


def format_alert(event: dict, analysis: dict) -> str:
    """
    Genera el texto completo de la alerta en español.
    """
    fetcher = AssetPriceFetcher()

    title = _translate_title(event.get("title", "Sin título"))
    score = event.get("score", event.get("impact_score", 0))
    category = event.get("category", "geopolítico").upper()
    sources = event.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    source_text = ", ".join(sources[:3]) if sources else "Desconocido"
    timestamp = _now_madrid().strftime("%d/%m/%Y %H:%M")

    direction = analysis.get("direction", "neutral")
    impact_pct = analysis.get("market_impact_percent", 0)

    # Asegurar consistencia entre dirección y signo del impacto
    if direction in ("up", "bullish", "positive", "alza"):
        impact_pct = abs(impact_pct)
    elif direction in ("down", "bearish", "negative", "baja"):
        impact_pct = -abs(impact_pct)
    else:
        impact_pct = 0
    timeframe = analysis.get("timeframe", "desconocido")
    confidence = analysis.get("confidence", 0)
    reasoning = translate_reasoning(analysis.get("reasoning", ""))
    affected_assets = analysis.get("most_affected_assets", [])

    if direction in ("up", "bullish", "positive", "alza"):
        direction_icon = "📈"
        direction_text = "Subida esperada"
    elif direction in ("down", "bearish", "negative", "baja"):
        direction_icon = "📉"
        direction_text = "Bajada esperada"
    else:
        direction_icon = "➡️"
        direction_text = "Movimiento lateral"

    if score >= 80:
        criticality = "CRÍTICA"
        alert_icon = "🔴"
    elif score >= 60:
        criticality = "ALTA"
        alert_icon = "🟠"
    elif score >= 40:
        criticality = "MEDIA"
        alert_icon = "🟡"
    else:
        criticality = "BAJA"
        alert_icon = "🟢"

    # Traducir timeframe
    timeframe_es = {
        "hours": "horas",
        "days": "días",
        "hours to days": "horas a días",
        "days to weeks": "días a semanas",
        "weeks": "semanas",
        "immediate": "inmediato",
    }.get(timeframe, timeframe)

    lines = []
    lines.append("=" * 80)
    lines.append(f"EVENTO #{event.get('rank', 1)}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"{alert_icon} ALERTA {criticality} - {category}")
    lines.append("")
    lines.append(f"📍 {title}")
    lines.append("")
    lines.append("━" * 60)
    lines.append("")
    lines.append("📊 IMPACTO DE MERCADO:")
    lines.append("")
    lines.append(f"{direction_icon} {direction_text}")
    lines.append(f"Plazo: {timeframe_es}")
    lines.append(f"Confianza: {confidence}%")
    lines.append("")
    lines.append("━" * 60)
    lines.append("")
    lines.append("💰 ACTIVOS AFECTADOS:")
    lines.append("")

    for asset in affected_assets:
        asset_upper = asset.upper()
        icon = ASSET_ICONS.get(asset_upper, "💹")
        name = ASSET_NAMES.get(asset_upper, asset_upper)
        formatted_current = fetcher.get_formatted_price(asset_upper)
        lines.append(f"  • {icon} {name} — {formatted_current}")

    lines.append("")
    lines.append("━" * 60)
    lines.append("")
    lines.append("💡 ANÁLISIS:")
    lines.append(reasoning if reasoning else "Sin análisis disponible")
    lines.append("")
    lines.append(f"Fuentes: {source_text}")
    lines.append("")
    lines.append("━" * 60)
    lines.append("")
    lines.append(f"🎯 PUNTUACIÓN: {score}/100 | CRITICIDAD: {criticality}")
    lines.append("")
    lines.append(f"⏰ {timestamp}")

    return "\n".join(lines)


def format_telegram_alert(event: dict, analysis: dict) -> str:
    """
    Genera un mensaje compacto para Telegram en texto plano.
    El título, la fuente y el reasoning se incluyen sin truncado adicional más allá
    de los 150 caracteres del reasoning; el tamaño total es típicamente ~300-500 chars.
    """
    fetcher = AssetPriceFetcher()

    title = _translate_title(event.get("title", "Sin título"))
    score = event.get("score", event.get("impact_score", 0))
    category = event.get("category", "geopolítico").upper()
    sources = event.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    source_text = (sources[0][:40] if sources else "Desconocido")
    timestamp = _now_madrid().strftime("%d/%m/%Y %H:%M")

    direction = analysis.get("direction", "neutral")
    impact_pct = analysis.get("market_impact_percent", 0)

    if direction in ("up", "bullish", "positive", "alza"):
        impact_pct = abs(impact_pct)
        direction_icon = "📈"
        direction_label = "Subida esperada"
    elif direction in ("down", "bearish", "negative", "baja"):
        impact_pct = -abs(impact_pct)
        direction_icon = "📉"
        direction_label = "Bajada esperada"
    else:
        impact_pct = 0
        direction_icon = "➡️"
        direction_label = "Lateral"

    timeframe = analysis.get("timeframe", "desconocido")
    timeframe_es = {
        "hours": "horas",
        "days": "días",
        "hours to days": "horas a días",
        "days to weeks": "días a semanas",
        "weeks": "semanas",
        "immediate": "inmediato",
    }.get(timeframe, timeframe)

    confidence = analysis.get("confidence", 0)
    reasoning = (analysis.get("reasoning", "") or "")[:150]
    affected_assets = analysis.get("most_affected_assets", [])

    if score >= 80:
        criticality = "CRÍTICA"
        alert_icon = "🔴"
    elif score >= 60:
        criticality = "ALTA"
        alert_icon = "🟠"
    elif score >= 40:
        criticality = "MEDIA"
        alert_icon = "🟡"
    else:
        criticality = "BAJA"
        alert_icon = "🟢"

    lines = []
    lines.append(f"{alert_icon} {category} — score {score}/100")
    lines.append("")
    lines.append(f"📍 {title}")
    lines.append("")
    lines.append(f"{direction_icon} {direction_label}")

    # Primary asset line
    if affected_assets:
        asset = affected_assets[0].upper()
        icon = ASSET_ICONS.get(asset, "💹")
        name = ASSET_NAMES.get(asset, asset)
        price_str = fetcher.get_formatted_price(asset)
        lines.append(f"🎯 Activo: {icon} {name} ({price_str})")

    lines.append(f"⏳ Plazo: {timeframe_es}")

    if confidence >= 60:
        lines.append(f"🔮 Confianza: {confidence}%")

    if reasoning:
        lines.append("")
        lines.append(f"💡 {reasoning}")

    lines.append("")
    lines.append(f"📰 {source_text}")
    lines.append(f"⏰ {timestamp}")

    return "\n".join(lines)


def format_cycle_summary(events: list) -> str:
    """
    Genera un mensaje resumen compacto cuando hay múltiples eventos en un ciclo.
    Si solo hay 1 evento, el llamador debe usar format_telegram_alert en su lugar.
    Muestra máximo 5 eventos.
    """
    count = len(events)
    timestamp = _now_madrid().strftime("%d/%m/%Y %H:%M")

    lines = []
    lines.append(f"🌍 GEO-NEWSLETTER — {count} eventos detectados")
    lines.append("")

    for i, event in enumerate(events[:5], start=1):
        score = event.get("score", event.get("impact_score", 0))
        title = _translate_title(event.get("title", "Sin título"))
        analysis = event.get("analysis") or {}
        direction = analysis.get("direction", "neutral")
        impact_pct = analysis.get("market_impact_percent", 0)
        affected_assets = analysis.get("most_affected_assets", [])

        if score >= 80:
            icon = "🔴"
        elif score >= 60:
            icon = "🟠"
        elif score >= 40:
            icon = "🟡"
        else:
            icon = "🟢"

        if direction in ("up", "bullish", "positive", "alza"):
            dir_str = "↑"
            asset_str = affected_assets[0].upper() if affected_assets else ""
        elif direction in ("down", "bearish", "negative", "baja"):
            dir_str = "↓"
            asset_str = affected_assets[0].upper() if affected_assets else ""
        else:
            dir_str = "→"
            asset_str = affected_assets[0].upper() if affected_assets else ""

        asset_part = f"{asset_str} {dir_str}" if asset_str else dir_str
        title_short = title[:45]
        lines.append(f"{i}. {icon} {asset_part} | {title_short}")

    lines.append("")
    lines.append(f"⏰ {timestamp}")

    return "\n".join(lines)
