"""
gpt_analyzer.py — Analizador de eventos con IA.
Soporta OpenAI (producción) y Ollama (desarrollo local).
Configurable via variables de entorno:
  OPENAI_API_KEY  → activa OpenAI
  OPENAI_MODEL    → modelo a usar (por defecto: gpt-4o-mini)
  OLLAMA_HOST     → host de Ollama (por defecto: http://localhost:11434)
  OLLAMA_MODEL    → modelo Ollama (por defecto: llama3.2)
"""
import json
import logging
import os
import re

logger = logging.getLogger("gpt")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Prompt del sistema para análisis de eventos
SYSTEM_PROMPT = """Eres un analista financiero experto especializado en el impacto de eventos geopolíticos en mercados financieros.
Tu tarea es analizar noticias y determinar su impacto en los mercados.

REGLAS CRÍTICAS SOBRE ACTIVOS:
- Noticias sobre bonos del tesoro/treasury yields → activos: ["US10Y", "SPX", "GOLD"]
- Noticias sobre petróleo/energía → activos: ["WTI", "BRENT", "XOM"]
- Noticias sobre criptomonedas → activos: ["BTC", "ETH"]
- Noticias sobre índices/bolsa general → activos: ["SPX", "NASDAQ", "DAX"]
- Noticias sobre empresas tech → activos: ["NASDAQ", "AAPL", "MSFT", "NVDA"]
- Noticias sobre geopolítica/guerra → activos: ["GOLD", "WTI", "SPX"]
- Noticias sobre inflación/fed → activos: ["GOLD", "SPX", "US10Y"]
- Noticias sobre commodities agrícolas → activos: ["WHEAT", "CORN"]
- NUNCA asignes BTC a noticias sobre bonos, treasury, yields, acciones tradicionales o índices bursátiles
- NUNCA asignes más de 4 activos
- Usa SOLO estos símbolos: BTC, ETH, XRP, SOL, WTI, BRENT, GOLD, SILVER, NATURAL_GAS, SPX, NASDAQ, DAX, FTSE, IBEX, AAPL, MSFT, NVDA, AMZN, TSLA, META, JPM, XOM, US10Y

Responde ÚNICAMENTE con JSON válido, sin explicaciones adicionales."""

ANALYSIS_PROMPT_TEMPLATE = """Analiza este evento de mercado/geopolítico:

Título: {title}
Descripción: {description}
Categoría: {category}
Puntuación de severidad: {score}/100

Responde con este JSON exacto:
{{
  "direction": "up|down|neutral",
  "market_impact_percent": <número entre -20 y 20>,
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <número entre 0 y 100>,
  "most_affected_assets": [<lista de 2-4 símbolos del listado permitido>],
  "reasoning": "<explicación breve en inglés de max 200 caracteres>"
}}"""


def _call_openai(prompt: str) -> dict | None:
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        return _parse_json_response(raw)
    except Exception as e:
        logger.error(f"Error OpenAI: {e}")
        return None


def _call_ollama(prompt: str) -> dict | None:
    try:
        import requests
        ollama_url = f"{OLLAMA_HOST}/api/chat"
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 400},
        }
        resp = requests.post(ollama_url, json=payload, timeout=30)
        if resp.status_code == 404:
            # Fallback to legacy /api/generate endpoint
            logger.info("Ollama /api/chat not available, falling back to /api/generate")
            generate_url = f"{OLLAMA_HOST}/api/generate"
            full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            payload_gen = {
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 400},
            }
            resp = requests.post(generate_url, json=payload_gen, timeout=30)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
        else:
            resp.raise_for_status()
            raw = resp.json().get("message", {}).get("content", "")
        return _parse_json_response(raw)
    except Exception as e:
        logger.warning(f"Error llamando a Ollama: {e}")
        return None


def _parse_json_response(text: str) -> dict | None:
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
    """Valida y normaliza el análisis devuelto por el modelo de IA."""
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
    assets = [str(a).upper() for a in assets[:4]]

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
    """Análisis de fallback basado en palabras clave cuando ningún modelo de IA está disponible."""
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
        assets = ["WTI", "BRENT", "NATURAL_GAS"]
    elif "crypto" in category:
        assets = ["BTC", "ETH", "XRP"]
    elif "bond" in category or "treasury" in category or "yield" in category:
        assets = ["US10Y", "SPX", "GOLD"]
    else:
        assets = ["SPX", "GOLD", "US10Y"]

    return {
        "market_impact_percent": round(impact, 1),
        "direction": direction,
        "timeframe": "hours to days",
        "confidence": min(70, 40 + score // 5),
        "most_affected_assets": assets,
        "reasoning": "Análisis automático basado en scoring de taxonomía. Impacto moderado esperado según el tipo de evento y zona geográfica.",
    }


def analyze_event(event: dict) -> dict:
    """
    Analiza un evento y devuelve el análisis estructurado.
    Usa OpenAI si OPENAI_API_KEY está configurado; si no, usa Ollama como fallback.
    Si ambos fallan, usa análisis por palabras clave.
    """
    title = event.get("title", "")
    description = event.get("description") or event.get("summary") or ""
    score = event.get("score", event.get("impact_score", 50))
    category = event.get("category", "")

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        title=title,
        description=description[:300],
        score=score,
        category=category,
    )

    result = None
    if OPENAI_API_KEY:
        logger.info("Analizando evento con OpenAI...")
        result = _call_openai(prompt)
    else:
        logger.info("Analizando evento con Ollama...")
        result = _call_ollama(prompt)

    if result:
        return _validate_analysis(result)

    logger.warning("Modelo de IA no disponible, usando análisis de fallback")
    return _fallback_analysis(event)


class EventAnalyzer:
    def __init__(self, use_ollama: bool = True):
        self.use_ollama = use_ollama

    def analyze(self, event: dict) -> dict:
        """
        Analiza un evento y devuelve el análisis estructurado.
        Delega a analyze_event() que soporta OpenAI y Ollama.
        """
        return analyze_event(event)
