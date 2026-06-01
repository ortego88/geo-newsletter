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


MOCK_PRICES = {
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
    "SUI": 1.2,
    "APT": 8.0,
    "SEI": 0.35,
    "TIA": 6.0,
    "INJ": 22.0,
    "RENDER": 7.5,
    "FET": 1.5,
    "PEPE": 0.000012,
    "WIF": 2.5,
    "SHIB": 0.000022,
    "TON": 6.5,
    "TRX": 0.12,
    "HBAR": 0.08,
    "ICP": 12.0,
    "AAVE": 90.0,
}

# --- Iconos por activo crypto ---
ASSET_ICONS = {
    # Top 20
    "BTC": "🪙", "ETH": "🔷", "XRP": "💧", "SOL": "☀️", "BNB": "🟡",
    "ADA": "🔵", "DOGE": "🐶", "TRX": "🔴", "TON": "💎", "LINK": "🔗",
    "AVAX": "🔺", "SHIB": "🐕", "DOT": "⚫", "SUI": "💎", "LTC": "🥈",
    "HBAR": "⬡", "UNI": "🦄", "ATOM": "⚛️", "XLM": "⭐", "NEAR": "🌐",
    # Layer 2 & Infra
    "ARB": "🔵", "OP": "🔴", "MATIC": "🟣", "ICP": "🌐", "FIL": "📁",
    "IMX": "🎮", "STX": "🟠", "MNT": "🟢",
    # DeFi
    "AAVE": "👻", "MKR": "🏛️", "CRV": "🌀", "LDO": "🧊", "DYDX": "📊",
    "SNX": "💠", "PENDLE": "⏳", "JUPITER": "🪐",
    # AI & Data
    "FET": "🤖", "RENDER": "🎨", "INJ": "💉", "TAO": "🧠", "ONDO": "🏦",
    "AIOZ": "📡",
    # Gaming & Metaverse
    "AXS": "🎮", "SAND": "🏖️", "MANA": "🌍", "GALA": "🎲", "ENJ": "⚔️",
    # New L1s
    "APT": "🟢", "SEI": "🌊", "TIA": "🟣", "KAS": "⛏️", "ALGO": "🔷",
    # Memecoins
    "PEPE": "🐸", "WIF": "🐕", "FLOKI": "🐺", "BONK": "🦴",
    # Exchange tokens
    "CRO": "🔵", "OKB": "🟡", "GT": "🚪",
    # Otros
    "VET": "✅", "THETA": "🎬", "FTM": "👻", "EOS": "🔮", "RUNE": "⚡", "GRT": "📈",
}

# --- Nombres legibles ---
ASSET_NAMES = {
    # Top 20
    "BTC": "Bitcoin", "ETH": "Ethereum", "XRP": "Ripple", "SOL": "Solana",
    "BNB": "Binance Coin", "ADA": "Cardano", "DOGE": "Dogecoin", "TRX": "Tron",
    "TON": "Toncoin", "LINK": "Chainlink", "AVAX": "Avalanche", "SHIB": "Shiba Inu",
    "DOT": "Polkadot", "SUI": "Sui", "LTC": "Litecoin", "HBAR": "Hedera",
    "UNI": "Uniswap", "ATOM": "Cosmos", "XLM": "Stellar", "NEAR": "NEAR Protocol",
    # Layer 2 & Infra
    "ARB": "Arbitrum", "OP": "Optimism", "MATIC": "Polygon",
    "ICP": "Internet Computer", "FIL": "Filecoin", "IMX": "Immutable",
    "STX": "Stacks", "MNT": "Mantle",
    # DeFi
    "AAVE": "Aave", "MKR": "Maker", "CRV": "Curve", "LDO": "Lido DAO",
    "DYDX": "dYdX", "SNX": "Synthetix", "PENDLE": "Pendle", "JUPITER": "Jupiter",
    # AI & Data
    "FET": "Fetch.ai", "RENDER": "Render", "INJ": "Injective",
    "TAO": "Bittensor", "ONDO": "Ondo Finance", "AIOZ": "AIOZ Network",
    # Gaming & Metaverse
    "AXS": "Axie Infinity", "SAND": "The Sandbox", "MANA": "Decentraland",
    "GALA": "Gala", "ENJ": "Enjin Coin",
    # New L1s
    "APT": "Aptos", "SEI": "Sei", "TIA": "Celestia", "KAS": "Kaspa", "ALGO": "Algorand",
    # Memecoins
    "PEPE": "Pepe", "WIF": "Dogwifhat", "FLOKI": "Floki", "BONK": "Bonk",
    # Exchange tokens
    "CRO": "Cronos", "OKB": "OKB", "GT": "Gate Token",
    # Otros
    "VET": "VeChain", "THETA": "Theta", "FTM": "Fantom",
    "EOS": "EOS", "RUNE": "THORChain", "GRT": "The Graph",
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
        if price >= 1000:
            return f"${price:,.0f}"
        if price >= 1:
            return f"${price:.2f}"
        if price >= 0.01:
            return f"${price:.4f}"
        return f"${price:.6f}"


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


def format_telegram_alert(event: dict, analysis: dict, language: str = "es") -> str:
    """
    Genera un mensaje compacto para Telegram en texto plano.
    Soporta español (es) e inglés (en).
    """
    fetcher = AssetPriceFetcher()
    is_en = language == "en"

    title = event.get("title", "No title" if is_en else "Sin título")
    if not is_en:
        title = _translate_title(title)
    score = event.get("score", event.get("impact_score", 0))
    category = event.get("category", "geopolitical" if is_en else "geopolítico").upper()
    sources = event.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    source_text = (sources[0][:40] if sources else ("Unknown" if is_en else "Desconocido"))
    timestamp = _now_madrid().strftime("%d/%m/%Y %H:%M")

    direction = analysis.get("direction", "neutral")
    impact_pct = analysis.get("market_impact_percent", 0)

    if direction in ("up", "bullish", "positive", "alza"):
        impact_pct = abs(impact_pct)
        direction_label = "Expected rise" if is_en else "Subida esperada"
    elif direction in ("down", "bearish", "negative", "baja"):
        impact_pct = -abs(impact_pct)
        direction_label = "Expected drop" if is_en else "Bajada esperada"
    else:
        impact_pct = 0
        direction_label = "Sideways" if is_en else "Lateral"

    timeframe = analysis.get("timeframe", "unknown" if is_en else "desconocido")
    if is_en:
        timeframe_label = {
            "hours": "hours",
            "days": "days",
            "hours to days": "hours to days",
            "days to weeks": "days to weeks",
            "weeks": "weeks",
            "immediate": "immediate",
        }.get(timeframe, timeframe)
    else:
        timeframe_label = {
            "hours": "horas",
            "days": "días",
            "hours to days": "horas a días",
            "days to weeks": "días a semanas",
            "weeks": "semanas",
            "immediate": "inmediato",
        }.get(timeframe, timeframe)

    confidence = analysis.get("confidence", 0)
    reasoning_raw = (analysis.get("reasoning", "") or "")
    # Truncar reasoning en frase completa (último punto antes de 150 chars)
    if len(reasoning_raw) > 150:
        # Buscar último punto antes de 150 chars
        last_period = reasoning_raw[:150].rfind('. ')
        if last_period > 50:  # Si hay un punto razonable, cortar ahí
            reasoning = reasoning_raw[:last_period + 1]
        else:
            # Si no hay punto, buscar último espacio
            last_space = reasoning_raw[:150].rfind(' ')
            if last_space > 50:
                reasoning = reasoning_raw[:last_space] + "..."
            else:
                reasoning = reasoning_raw[:150] + "..."
    else:
        reasoning = reasoning_raw
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
    lines.append(f"{direction_label}")

    # Primary asset line
    if affected_assets:
        asset = affected_assets[0].upper()
        icon = ASSET_ICONS.get(asset, "💹")
        name = ASSET_NAMES.get(asset, asset)
        price_str = fetcher.get_formatted_price(asset)
        asset_label = "Asset" if is_en else "Activo"
        lines.append(f"{asset_label}: {name} ({price_str})")

    timeframe_word = "Timeframe" if is_en else "Plazo"
    lines.append(f"{timeframe_word}: {timeframe_label}")

    if confidence >= 60:
        conf_label = "Confidence" if is_en else "Confianza"
        lines.append(f"{conf_label}: {confidence}%")

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
    lines.append(f"🌍 Trianio — {count} eventos detectados")
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
