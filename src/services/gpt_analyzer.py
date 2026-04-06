"""
Analizador de eventos con Ollama (LLaMA2 local).
Devuelve JSON con: market_impact_percent, direction, timeframe, confidence,
most_affected_assets, reasoning.
"""

import json
import logging
import re

logger = logging.getLogger("gpt")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama2"

ANALYSIS_PROMPT = """Eres un analista de mercados financieros especializado en geopolítica.
Analiza el siguiente evento y devuelve ÚNICAMENTE un JSON válido con esta estructura exacta:

{{
  "market_impact_percent": <número entre -20 y 20>,
  "direction": "<up|down|neutral>",
  "timeframe": "<immediate|hours|hours to days|days|days to weeks|weeks>",
  "confidence": <número entre 0 y 100>,
  "most_affected_assets": ["<ASSET1>", "<ASSET2>", "<ASSET3>"],
  "reasoning": "<explicación en español de máximo 300 caracteres>"
}}

Activos válidos: BTC, ETH, XRP, SOL, WTI_OIL, BRENT, BRENT_OIL, GOLD, SILVER, NATURAL_GAS, SPX, INDU, CCMP, FTSE, DAX, AAPL, GOOGL, MSFT

Evento: {title}
Descripción: {description}
Puntuación de severidad: {score}/100
Categoría: {category}

Responde SOLO con el JSON, sin texto adicional."""


def _call_ollama(prompt: str) -> str | None:
    try:
        import requests
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 400},
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.warning(f"Error llamando a Ollama: {e}")
        return None


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _validate_analysis(data: dict) -> dict:
    """Valida y normaliza el análisis devuelto por Ollama."""
    impact = float(data.get("market_impact_percent", 5))
    impact = max(-20, min(20, impact))

    direction = data.get("direction", "neutral")
    if direction not in ("up", "down", "neutral"):
        direction = "neutral"

    timeframe = data.get("timeframe", "hours")
    valid_timeframes = ("immediate", "hours", "hours to days", "days", "days to weeks", "weeks")
    if timeframe not in valid_timeframes:
        timeframe = "hours"

    confidence = float(data.get("confidence", 50))
    confidence = max(0, min(100, confidence))

    assets = data.get("most_affected_assets", [])
    if not isinstance(assets, list):
        assets = []
    assets = [str(a).upper() for a in assets[:5]]

    reasoning = str(data.get("reasoning", ""))[:300]

    return {
        "market_impact_percent": round(impact, 1),
        "direction": direction,
        "timeframe": timeframe,
        "confidence": round(confidence),
        "most_affected_assets": assets,
        "reasoning": reasoning,
    }


def _fallback_analysis(event: dict) -> dict:
    """Análisis de fallback basado en palabras clave cuando Ollama no está disponible."""
    title = (event.get("title") or "").lower()
    desc = (event.get("description") or event.get("summary") or "").lower()
    text = f"{title} {desc}"
    score = event.get("score", 50)
    category = event.get("category", "").lower()

    # Señales alcistas
    bullish_words = ["ceasefire", "peace", "deal", "agreement", "boost", "rise", "increase", "record high"]
    # Señales bajistas
    bearish_words = ["war", "attack", "sanction", "conflict", "disruption", "threat", "crisis", "collapse"]

    bull_hits = sum(1 for w in bullish_words if w in text)
    bear_hits = sum(1 for w in bearish_words if w in text)

    if bear_hits > bull_hits:
        direction = "down"
        impact = -min(15, 5 + bear_hits * 2)
    elif bull_hits > bear_hits:
        direction = "up"
        impact = min(15, 5 + bull_hits * 2)
    else:
        direction = "up" if score > 70 else "neutral"
        impact = 5.0 if score > 70 else 2.0

    # Activos por categoría
    if "energy" in category or "oil" in category:
        assets = ["WTI_OIL", "BRENT", "NATURAL_GAS"]
    elif "crypto" in category:
        assets = ["BTC", "ETH", "XRP"]
    else:
        assets = ["SPX", "GOLD", "BTC"]

    return {
        "market_impact_percent": round(impact, 1),
        "direction": direction,
        "timeframe": "hours to days",
        "confidence": min(70, 40 + score // 5),
        "most_affected_assets": assets,
        "reasoning": "Análisis automático basado en scoring de taxonomía. Impacto moderado esperado según el tipo de evento y zona geográfica.",
    }


class EventAnalyzer:
    def __init__(self, use_ollama: bool = True):
        self.use_ollama = use_ollama

    def analyze(self, event: dict) -> dict:
        """
        Analiza un evento y devuelve el análisis estructurado.
        Usa Ollama si está disponible; cae a análisis por palabras clave.
        """
        logger.info("Analizando evento con Ollama...")

        title = event.get("title", "")
        description = event.get("description") or event.get("summary") or ""
        score = event.get("score", event.get("impact_score", 50))
        category = event.get("category", "")

        if self.use_ollama:
            prompt = ANALYSIS_PROMPT.format(
                title=title,
                description=description[:300],
                score=score,
                category=category,
            )
            raw_response = _call_ollama(prompt)
            if raw_response:
                parsed = _extract_json(raw_response)
                if parsed:
                    return _validate_analysis(parsed)
                logger.warning("No se pudo parsear la respuesta JSON de Ollama, usando fallback")
            else:
                logger.warning("Ollama no disponible, usando análisis de fallback")

        return _fallback_analysis(event)
