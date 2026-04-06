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
SYSTEM_PROMPT = """You are an expert quantitative financial analyst specializing in geopolitical event impact on markets.

ASSET ASSIGNMENT RULES (strict priority order):
1. News about a specific COMPANY (Apple, JPMorgan, Tesla, Nvidia, etc.) → use that company's ticker FIRST, then the relevant index
   - JPMorgan/Jamie Dimon/banks → ["JPM", "SPX", "US10Y"]
   - Apple/iPhone → ["AAPL", "NASDAQ"]
   - Tesla/Elon Musk (re: Tesla) → ["TSLA", "NASDAQ"]
   - Nvidia/AI chips → ["NVDA", "NASDAQ"]
   - Oil majors (ExxonMobil, Shell, BP) → ["XOM", "WTI", "BRENT"]

2. News about COMMODITIES:
   - Oil/crude/OPEC/refinery/petroleum/pipeline → ["WTI", "BRENT", "XOM"]
   - Gold/safe haven/fear → ["GOLD", "SILVER"]
   - Natural gas/LNG → ["NATURAL_GAS", "WTI"]
   - Agricultural → ["WHEAT", "CORN"]

3. News about CRYPTO:
   - Bitcoin/BTC/crypto broadly → ["BTC", "ETH"]
   - Ethereum/DeFi specifically → ["ETH", "BTC"]
   - NEVER assign BTC to stock market, bond or macro news

4. News about MACRO / CENTRAL BANKS:
   - Fed/interest rates/inflation → ["US10Y", "SPX", "GOLD"]
   - Treasury yields/bonds → ["US10Y", "SPX"]
   - Recession/GDP/unemployment → ["SPX", "US10Y", "GOLD"]

5. News about GEOPOLITICS / MILITARY:
   - News about Iran/Middle East tensions/war → ["WTI", "BRENT", "GOLD"] (oil FIRST because Iran is a major producer)
   - News about Russia/Ukraine conflict → ["NATURAL_GAS", "GOLD", "WHEAT"]
   - News mentioning "market volatility" as secondary effect → use the PRIMARY subject's assets, not GOLD
   - News with "optimism", "peace", "ceasefire" in oil-producing regions → ["WTI", "BRENT"] direction=down
   - If title contains analyst opinion words (Says, According to, Warns, Forecasts) → use confidence 50-65
   - War/conflict in oil-producing region → ["WTI", "BRENT", "GOLD"]
   - War/conflict NOT oil-related → ["GOLD", "SPX"]
   - Strait/chokepoint disruption → ["WTI", "BRENT", "NATURAL_GAS"]
   - Sanctions/tariffs/trade war → ["SPX", "NASDAQ", "US10Y"]

6. News about STOCK INDICES broadly:
   - Global markets/Wall Street/S&P → ["SPX", "NASDAQ"]
   - European markets → ["DAX", "FTSE", "IBEX"]

IMPACT CALIBRATION (market_impact_percent):
- CEO letter/statement/outlook → ±1 to ±3%
- Central bank meeting/decision → ±1 to ±4%
- Earnings miss/beat → ±3 to ±8%
- Trade deal/tariff announcement → ±2 to ±5%
- Military attack on oil infrastructure → ±5 to ±12%
- Major war escalation → ±3 to ±8%
- Chokepoint/strait disruption → ±5 to ±15%
- Geopolitical tension (no direct impact) → ±1 to ±3%
- Default: ±2 to ±5%
- NEVER use round numbers like exactly 10, 15, -10, -15

CONFIDENCE CALIBRATION (0-100):
- 85-95: Direct, unambiguous impact. Confirmed event (e.g. "OPEC cuts production by 1M barrels")
- 70-84: Clear impact but some uncertainty about magnitude
- 50-69: Indirect impact or event is a warning/prediction/analysis (e.g. CEO letter)
- 30-49: Speculative, indirect or contradictory signals
- Use 55-65 for opinion pieces, CEO letters, analyst forecasts

ALLOWED SYMBOLS ONLY: BTC, ETH, XRP, SOL, WTI, BRENT, GOLD, SILVER, NATURAL_GAS, SPX, NASDAQ, DAX, FTSE, IBEX, AAPL, MSFT, NVDA, AMZN, TSLA, META, JPM, XOM, US10Y, WHEAT, CORN

Respond ONLY with valid JSON, no explanations."""

ANALYSIS_PROMPT_TEMPLATE = """Analyze this market/geopolitical event and determine its financial impact:

Title: {title}
Description: {description}
Category: {category}
Severity score: {score}/100

Instructions:
- If the title contains attribution words like "Says", "According to", "Warns" — this is an analyst opinion, cap confidence at 65
- Identify the PRIMARY subject: is it about a company, commodity, macro policy, or geopolitical event?
- Assign assets based on the PRIMARY subject (not secondary effects)
- Use realistic impact percentages (most events are ±1-5%, not ±10-15%)
- Set confidence based on how direct and confirmed the impact is

Respond with this exact JSON:
{{
  "direction": "up|down|neutral",
  "market_impact_percent": <realistic number, avoid round numbers like 10 or 15>,
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <calibrated 0-100, most events 50-75>,
  "most_affected_assets": [<2-3 symbols, primary subject first>],
  "reasoning": "<one sentence max 150 chars explaining PRIMARY subject and direction>"
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
    _MAX_IMPACT = 15.0
    _MAX_MODERATE_IMPACT = 8.0  # cap for events with score < 80
    _MODERATE_SCORE_THRESHOLD = 80
    _LOW_IMPACT_THRESHOLD = 3.0
    _HIGH_CONFIDENCE_THRESHOLD = 75.0
    _CAPPED_CONFIDENCE = 70.0

    impact = float(data.get("market_impact_percent", 2))
    score = data.get("_event_score", 50)  # passed through if available
    impact = max(-_MAX_IMPACT, min(_MAX_IMPACT, impact))
    # Prevent over-inflated impacts for moderate events
    if abs(impact) > _MAX_MODERATE_IMPACT and score < _MODERATE_SCORE_THRESHOLD:
        impact = _MAX_MODERATE_IMPACT if impact > 0 else -_MAX_MODERATE_IMPACT

    direction = data.get("direction", "neutral")
    if direction not in ("up", "down", "neutral"):
        direction = "neutral"
    # Auto-fix direction/impact sign mismatch
    if direction == "up" and impact < 0:
        impact = abs(impact)
    elif direction == "down" and impact > 0:
        impact = -abs(impact)

    timeframe = data.get("timeframe", "hours")
    valid_timeframes = ("immediate", "hours", "hours to days", "days", "days to weeks", "weeks")
    if timeframe not in valid_timeframes:
        timeframe = "hours"

    confidence = float(data.get("confidence", 50))
    confidence = max(0, min(100, confidence))
    # Cap confidence for indirect events (impact < 3%)
    if abs(impact) < _LOW_IMPACT_THRESHOLD and confidence > _HIGH_CONFIDENCE_THRESHOLD:
        confidence = _CAPPED_CONFIDENCE

    assets = data.get("most_affected_assets", [])
    if not isinstance(assets, list):
        assets = []
    assets = [str(a).upper() for a in assets[:3]]  # max 3, not 4

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
    _BASE_IMPACT = 2.0
    _MAX_MULTIPLIER_IMPACT = 6.0
    _HIT_MULTIPLIER = 1.5
    _MAX_FALLBACK_CONFIDENCE = 60
    _BASE_CONFIDENCE = 30
    _SCORE_DIVISOR = 6

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
        impact = -(_BASE_IMPACT + min(_MAX_MULTIPLIER_IMPACT, bear_hits * _HIT_MULTIPLIER))
    elif bull_hits > bear_hits:
        direction = "up"
        impact = _BASE_IMPACT + min(_MAX_MULTIPLIER_IMPACT, bull_hits * _HIT_MULTIPLIER)
    else:
        direction = "up" if score > 70 else "neutral"
        impact = 2.0 if score > 70 else 1.0

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
        "confidence": min(_MAX_FALLBACK_CONFIDENCE, _BASE_CONFIDENCE + score // _SCORE_DIVISOR),
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
        result["_event_score"] = score  # inject score for validation
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
