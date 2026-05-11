"""
Traductor para el sistema geo-newsletter.
- DeepL API: traducción de blog posts (ES → EN) y textos largos.
- MyMemory: traducción de títulos cortos (EN → ES).
- Fallback: diccionario de términos financieros/geopolíticos.

Requiere: DEEPL_API_KEY para traducción de blog (Free tier: 500K chars/mes).
"""

import logging
import os
import re
import urllib.parse

import requests as _requests

logger = logging.getLogger("translator")

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"


def translate_text(text: str, target_lang: str = "EN", source_lang: str = "ES") -> str | None:
    """
    Traduce texto usando DeepL API.
    target_lang: "EN", "ES", "FR", etc.
    Devuelve el texto traducido o None si falla.
    """
    if not DEEPL_API_KEY:
        logger.debug("DEEPL_API_KEY no configurada")
        return None

    if not text or not text.strip():
        return text

    try:
        resp = _requests.post(
            DEEPL_API_URL,
            data={
                "auth_key": DEEPL_API_KEY,
                "text": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "tag_handling": "html",
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        translations = result.get("translations", [])
        if translations:
            return translations[0]["text"]
    except Exception as e:
        logger.error(f"Error DeepL: {e}")

    return None


def translate_blog_post(title: str, excerpt: str, content: str) -> dict:
    """
    Traduce un artículo completo del blog (ES → EN).
    Devuelve dict con title_en, excerpt_en, content_en.
    """
    title_en = translate_text(title, target_lang="EN") or ""
    excerpt_en = translate_text(excerpt, target_lang="EN") or ""
    content_en = translate_text(content, target_lang="EN") or ""

    if title_en:
        logger.info(f"Blog traducido con DeepL: '{title[:50]}' → '{title_en[:50]}'")

    return {
        "title_en": title_en,
        "excerpt_en": excerpt_en,
        "content_en": content_en,
    }

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

# Pre-compilar patrones para mejorar rendimiento en _fallback_translate
_FALLBACK_PATTERNS = [
    (re.compile(re.escape(en), re.IGNORECASE), es)
    for en, es in _FALLBACK_DICT.items()
]


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
            encoded = urllib.parse.quote(title)
            url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair=en|es"
            resp = _requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated:
                return translated
        except Exception as e:
            logger.debug(f"MyMemory API error para título: {e}")

        return TitleTranslator._fallback_translate(title)

    @staticmethod
    def _fallback_translate(title: str) -> str:
        """Traducción por diccionario de términos comunes usando patrones pre-compilados."""
        result = title
        for pattern, es in _FALLBACK_PATTERNS:
            result = pattern.sub(es, result)
        return result
