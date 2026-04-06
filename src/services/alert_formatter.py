"""
Formateador de alertas para el sistema geo-newsletter.
AssetPriceFetcher intenta obtener precios reales con RealPriceFetcher
y cae al mock solo si el precio real no está disponible.
"""

import logging
from datetime import datetime

from src.services.real_price_fetcher import RealPriceFetcher

try:
    from src.services.translator import TitleTranslator
except Exception:
    TitleTranslator = None

logger = logging.getLogger("alert_formatter")

# --- Precios mock de fallback ---
MOCK_PRICES = {
    "BTC": 62450.0,
    "ETH": 3280.0,
    "XRP": 0.52,
    "SOL": 145.0,
    "ADA": 0.45,
    "BNB": 580.0,
    "DOGE": 0.12,
    "WTI_OIL": 85.50,
    "BRENT": 91.20,
    "WTI": 85.50,
    "GOLD": 2350.0,
    "SILVER": 28.50,
    "NATURAL_GAS": 2.85,
    "COPPER": 4.20,
    "SPX": 5210.0,
    "SP500": 5210.0,
    "INDU": 38500.0,
    "CCMP": 16400.0,
    "NASDAQ": 16400.0,
    "FTSE": 7800.0,
    "DAX": 17500.0,
    "AAPL": 185.0,
    "GOOGL": 175.0,
    "MSFT": 415.0,
    "AMZN": 192.0,
    "TSLA": 175.0,
    "NVDA": 870.0,
    "US10Y": 4.35,
    "US2Y": 4.85,
    "BONDS": 4.35,
}

# --- Iconos por tipo de activo ---
ASSET_ICONS = {
    "BTC": "🪙",
    "ETH": "🔷",
    "XRP": "💧",
    "SOL": "☀️",
    "ADA": "🔵",
    "BNB": "🟡",
    "DOGE": "🐶",
    "WTI_OIL": "🛢️ ",
    "BRENT": "⚫",
    "WTI": "🛢️ ",
    "GOLD": "🥇",
    "SILVER": "🥈",
    "NATURAL_GAS": "🔥",
    "COPPER": "🟤",
    "SPX": "📈",
    "SP500": "📈",
    "INDU": "🏭",
    "CCMP": "💻",
    "NASDAQ": "💻",
    "FTSE": "🇬🇧",
    "DAX": "🇩🇪",
    "AAPL": "🍎",
    "GOOGL": "🔍",
    "MSFT": "🪟",
    "AMZN": "📦",
    "TSLA": "🚗",
    "NVDA": "🖥️",
    "US10Y": "📊",
    "US2Y": "📊",
    "BONDS": "📊",
}

# --- Nombres legibles en español ---
ASSET_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "XRP": "Ripple",
    "SOL": "Solana",
    "ADA": "Cardano",
    "BNB": "Binance Coin",
    "DOGE": "Dogecoin",
    "WTI_OIL": "WTI Oil",
    "BRENT": "Brent Oil",
    "WTI": "WTI Oil",
    "GOLD": "Oro",
    "SILVER": "Plata",
    "NATURAL_GAS": "Gas Natural",
    "COPPER": "Cobre",
    "SPX": "S&P 500",
    "SP500": "S&P 500",
    "INDU": "Dow Jones",
    "CCMP": "Nasdaq",
    "NASDAQ": "Nasdaq",
    "FTSE": "FTSE 100",
    "DAX": "DAX",
    "AAPL": "Apple",
    "GOOGL": "Google",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "TSLA": "Tesla",
    "NVDA": "NVIDIA",
    "US10Y": "Bono Tesoro 10Y",
    "US2Y": "Bono Tesoro 2Y",
    "BONDS": "Bonos USA",
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
}


def translate_reasoning(text: str) -> str:
    """Traducción básica inglés→español para el campo reasoning."""
    if not text:
        return text
    result = text
    for en, es in _EN_ES.items():
        result = result.replace(en, es).replace(en.capitalize(), es.capitalize())
    return result[:300]


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
        if asset_upper in ("SPX", "SP500", "INDU", "CCMP", "NASDAQ", "FTSE", "DAX"):
            return f"{price:,.0f}"
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

    title = event.get("title", "Sin título")
    # Traducir el título al español si hay un translator disponible
    if TitleTranslator is not None:
        try:
            title = TitleTranslator.translate(title)
        except Exception as e:
            logger.debug(f"Error traduciendo título: {e}")
    score = event.get("score", event.get("impact_score", 0))
    category = event.get("category", "geopolítico").upper()
    sources = event.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    source_text = ", ".join(sources[:3]) if sources else "Desconocido"
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")

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
    lines.append(f"Cambio esperado: {'+' if impact_pct > 0 else ''}{impact_pct}%")
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
        current_price = fetcher.get_price(asset_upper)
        projected = current_price * (1 + impact_pct / 100)
        formatted_current = fetcher.get_formatted_price(asset_upper)
        formatted_projected = f"{projected:,.0f}" if projected >= 100 else f"{projected:.2f}"
        lines.append(f"  • {icon} {name}")
        lines.append(f"    Ahora: {formatted_current} → {formatted_projected} ({'+' if impact_pct > 0 else ''}{impact_pct}%)")

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

    title = event.get("title", "Sin título")
    score = event.get("score", event.get("impact_score", 0))
    category = event.get("category", "geopolítico").upper()
    sources = event.get("sources", [])
    if isinstance(sources, str):
        sources = [sources]
    source_text = (sources[0][:40] if sources else "Desconocido")
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")

    direction = analysis.get("direction", "neutral")
    impact_pct = analysis.get("market_impact_percent", 0)

    if direction in ("up", "bullish", "positive", "alza"):
        impact_pct = abs(impact_pct)
        direction_icon = "📈"
        direction_label = f"Subida esperada: +{impact_pct}%"
    elif direction in ("down", "bearish", "negative", "baja"):
        impact_pct = -abs(impact_pct)
        direction_icon = "📉"
        direction_label = f"Bajada esperada: {impact_pct}%"
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
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")

    lines = []
    lines.append(f"🌍 GEO-NEWSLETTER — {count} eventos detectados")
    lines.append("")

    for i, event in enumerate(events[:5], start=1):
        score = event.get("score", event.get("impact_score", 0))
        title = event.get("title", "Sin título")
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
            dir_str = f"+{abs(impact_pct)}%"
            asset_str = affected_assets[0].upper() if affected_assets else ""
        elif direction in ("down", "bearish", "negative", "baja"):
            dir_str = f"-{abs(impact_pct)}%"
            asset_str = affected_assets[0].upper() if affected_assets else ""
        else:
            dir_str = "→0%"
            asset_str = affected_assets[0].upper() if affected_assets else ""

        asset_part = f"{asset_str} {dir_str}" if asset_str else dir_str
        title_short = title[:45]
        lines.append(f"{i}. {icon} {asset_part} | {title_short}")

    lines.append("")
    lines.append(f"⏰ {timestamp}")

    return "\n".join(lines)
