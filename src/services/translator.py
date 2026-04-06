"""
Traductor de títulos para el sistema geo-newsletter.
Usa la API gratuita de MyMemory para traducir inglés → español.
Cae a un diccionario de términos financieros/geopolíticos si la API falla.
"""

import logging
import urllib.parse

logger = logging.getLogger("translator")

# Diccionario de términos comunes financieros/geopolíticos en→es
_FALLBACK_DICT = {
    "ceasefire": "alto el fuego",
    "peace talks": "conversaciones de paz",
    "oil prices": "precios del petróleo",
    "crude oil": "petróleo crudo",
    "natural gas": "gas natural",
    "stock market": "bolsa de valores",
    "financial markets": "mercados financieros",
    "interest rate": "tasa de interés",
    "inflation": "inflación",
    "recession": "recesión",
    "sanctions": "sanciones",
    "trade war": "guerra comercial",
    "tariff": "arancel",
    "conflict": "conflicto",
    "military": "militar",
    "missile": "misil",
    "attack": "ataque",
    "war": "guerra",
    "invasion": "invasión",
    "troops": "tropas",
    "nuclear": "nuclear",
    "geopolitical": "geopolítico",
    "diplomatic": "diplomático",
    "tension": "tensión",
    "deadline": "plazo límite",
    "looms": "se avecina",
    "keeps markets on edge": "mantiene los mercados en vilo",
    "markets on edge": "mercados en vilo",
    "record premium": "prima récord",
    "record high": "máximo histórico",
    "oil supply": "suministro de petróleo",
    "energy crisis": "crisis energética",
    "fertilizer": "fertilizante",
    "tender": "licitación",
    "investors": "inversores",
    "uncertainty": "incertidumbre",
    "disruption": "disrupción",
    "demand": "demanda",
    "supply": "suministro",
    "buyers": "compradores",
    "sellers": "vendedores",
    "premium": "prima",
    "futures": "futuros",
    "commodities": "materias primas",
    "currencies": "divisas",
    "bonds": "bonos",
    "yields": "rendimientos",
    "rally": "rally",
    "selloff": "venta masiva",
    "volatility": "volatilidad",
    "hedge": "cobertura",
    "data center": "centro de datos",
    "boom": "auge",
    "stress test": "prueba de estrés",
    "insurers": "aseguradoras",
    "rise": "sube",
    "fall": "cae",
    "surge": "disparo",
    "plunge": "desplome",
    "jumps": "salta",
    "drops": "cae",
    "climbs": "sube",
    "slips": "cede",
    "signals": "señales",
    "deal": "acuerdo",
    "agreement": "acuerdo",
    "summit": "cumbre",
    "sanctions relief": "alivio de sanciones",
    "Iran": "Irán",
    "Iraq": "Irak",
    "Saudi Arabia": "Arabia Saudí",
    "Russia": "Rusia",
    "China": "China",
    "India": "India",
    "United States": "Estados Unidos",
    "Europe": "Europa",
    "Middle East": "Oriente Medio",
    "Persian Gulf": "Golfo Pérsico",
    "Trump": "Trump",
}


class TitleTranslator:
    """Traduce títulos de noticias de inglés a español."""

    @staticmethod
    def translate(title: str) -> str:
        """
        Traduce un título usando la API gratuita de MyMemory.
        Si falla, usa traducción por diccionario.
        """
        if not title:
            return title

        try:
            import requests
            encoded = urllib.parse.quote(title)
            url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|es"
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and translated.upper() != title.upper():
                return translated
        except Exception as e:
            logger.debug(f"MyMemory API error para título: {e}")

        return TitleTranslator._fallback_translate(title)

    @staticmethod
    def _fallback_translate(title: str) -> str:
        """Traducción por diccionario de términos comunes."""
        result = title
        for en, es in _FALLBACK_DICT.items():
            # Reemplazar ignorando mayúsculas/minúsculas pero conservando estructura
            import re
            result = re.sub(re.escape(en), es, result, flags=re.IGNORECASE)
        return result
