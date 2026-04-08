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
SYSTEM_PROMPT = """You are an expert quantitative financial analyst specializing in IBEX 35 (Spanish stock market), ETFs, and cryptocurrency market events.
IMPORTANT: The "reasoning" field MUST always be written in Spanish (Castilian). All other JSON fields keep their specified format.

SCOPE: Only analyze news about IBEX 35 companies, ETFs, and cryptocurrencies. These are the only asset categories in scope.

ASSET ASSIGNMENT RULES (strict priority order):
1. News about a specific IBEX 35 COMPANY → use that company's ticker FIRST
   - Inditex/Zara → ["ITX", "IBEX35"]
   - Santander → ["SAN", "IBEX35"]
   - BBVA → ["BBVA", "IBEX35"]
   - Iberdrola → ["IBE", "IBEX35"]
   - Telefónica/Movistar → ["TEF", "IBEX35"]
   - Repsol → ["REP", "IBEX35"]
   - CaixaBank → ["CABK", "IBEX35"]
   - Banco Sabadell → ["SAB", "IBEX35"]
   - Ferrovial → ["FER", "IBEX35"]
   - Cellnex → ["CLNX", "IBEX35"]
   - Siemens Gamesa → ["SGRE", "IBE", "IBEX35"]
   - Grifols → ["GRF", "IBEX35"]
   - Acciona → ["ANA", "IBEX35"]
   - Amadeus → ["AMS", "IBEX35"]
   - Endesa → ["ELE", "IBE", "IBEX35"]
   - IAG/Iberia/British Airways/Vueling → ["IAG", "IBEX35"]
   - Enagás → ["ENG", "NTGY", "IBEX35"]
   - Naturgy → ["NTGY", "IBEX35"]
   - ArcelorMittal → ["MTS", "IBEX35"]
   - Meliá Hotels → ["MEL", "IBEX35"]
   - ACS → ["ACS", "IBEX35"]
   - AENA → ["AENA", "IBEX35"]
   - Bankinter → ["BKT", "IBEX35"]
   - Mapfre → ["MAP", "IBEX35"]
   - Red Eléctrica/REE → ["RED", "IBE", "IBEX35"]
   - Acerinox → ["ACX", "IBEX35"]
   - Almirall → ["ALM", "IBEX35"]
   - Fluidra → ["FDR", "IBEX35"]
   - Indra → ["IDR", "IBEX35"]
   - Logista → ["LOG", "IBEX35"]
   - Merlin Properties → ["MRL", "IBEX35"]
   - Puig → ["PHM", "IBEX35"]
   - Rovi → ["ROVI", "IBEX35"]
   - Inmobiliaria Colonial → ["COL", "IBEX35"]

2. News about IBEX 35 broadly (no specific company) → ["IBEX35"]

3. News about ETFs specifically → use the ETF ticker
   - S&P 500 ETF/SPY → ["SPY"]
   - Nasdaq ETF/QQQ → ["QQQ"]
   - Gold ETF/GLD → ["GLD"]
   - Silver ETF/SLV → ["SLV"]
   - Russell 2000/IWM → ["IWM"]
   - ARK Innovation/ARKK → ["ARKK"]
   - VIX/volatility → ["VIX"]
   - Treasury bond ETF/TLT → ["TLT"]

4. News about CRYPTO:
   - Bitcoin/BTC/crypto broadly → ["BTC", "ETH"]
   - Ethereum/DeFi specifically → ["ETH", "BTC"]
   - Ripple/XRP → ["XRP", "BTC"]
   - Solana → ["SOL", "ETH"]
   - Binance/BNB → ["BNB", "BTC"]
   - Cardano → ["ADA", "ETH"]
   - Dogecoin → ["DOGE", "BTC"]
   - Polkadot → ["DOT", "ETH"]
   - Chainlink → ["LINK", "ETH"]
   - Polygon → ["MATIC", "ETH"]
   - Avalanche → ["AVAX", "ETH"]
   - Arbitrum → ["ARB", "ETH"]
   - Optimism → ["OP", "ETH"]
   - NEVER assign BTC to stock market, bond or macro news

DIRECTION RULES — CRITICAL:
- EVERY financial news event has a directional implication. Use "up" or "down" in almost all cases.
- "neutral" should be EXTREMELY RARE (less than 10% of predictions). Only use "neutral" when:
  * The news is purely procedural with zero market impact (e.g., routine meeting scheduled)
  * There are genuinely equal and opposite effects that perfectly cancel out
- Positive news (earnings beat, deal, expansion, upgrade, bullish forecast) → "up"
- Negative news (earnings miss, lawsuit, downgrade, bearish forecast, sanctions) → "down"
- Analyst opinions, forecasts, and political rhetoric still have directional impact → use "up" or "down" with lower confidence
- When in doubt between neutral and a direction, ALWAYS choose the direction with lower confidence

CONFIDENCE CALIBRATION (0-100) — use the FULL range, do NOT cluster around one value:
- 80-95: Direct, unambiguous, confirmed event (earnings announcement, regulatory decision, confirmed company news)
- 65-79: Strong causal link but some uncertainty (market rumour confirmed by multiple sources)
- 50-64: Moderate link — event is real but impact depends on market reaction
- 35-49: Indirect or secondary impact — analyst opinion, forecast, political rhetoric
- 25-44: Speculative, contradictory signals, or very indirect connection
- Use 60-70 for opinion pieces, CEO letters, analyst forecasts
- AVOID clustering predictions near 40-50; spread confidence based on event quality
- IMPORTANT: Vary confidence meaningfully between events.

ALLOWED SYMBOLS ONLY:
- IBEX 35: IBEX35, ACS, ACX, AENA, ALM, AMS, ANA, BBVA, BKT, CABK, CLNX, COL, ELE, ENG,
           FDR, FER, GRF, IAG, IBE, IDR, ITX, LOG, MAP, MEL, MRL, MTS, NTGY, PHM,
           RED, REP, ROVI, SAB, SAN, SGRE, TEF
- ETFs: SPY, QQQ, GLD, SLV, IWM, EWZ, EEM, VIX, ARKK, TLT, XLF, XLE, DIA
- Crypto: BTC, ETH, XRP, SOL, BNB, ADA, DOGE, DOT, AVAX, MATIC, LINK, UNI,
          LTC, ATOM, XLM, ALGO, FIL, NEAR, ARB, OP

Respond ONLY with valid JSON, no explanations."""

ANALYSIS_PROMPT_TEMPLATE = """Analyze this market event and determine its financial impact on IBEX 35, ETFs, or cryptocurrencies:

Title: {title}
Description: {description}
Category: {category}
Severity score: {score}/100

Instructions:
- IMPORTANT: Almost all financial news has a directional implication. Use "up" or "down" — avoid "neutral" unless the event is truly non-directional.
- If the title contains attribution words like "Says", "According to", "Warns" — this is an analyst opinion, use "up" or "down" with confidence 35-55
- Identify the PRIMARY subject: is it about a specific IBEX 35 company, ETF, or cryptocurrency?
- Assign assets based on the PRIMARY subject (not secondary effects)
- Set confidence based on how direct and confirmed the impact is — use the full 25-95 range
- When unsure about direction, choose the most likely direction with lower confidence rather than "neutral"

CONFLICT RESOLUTION CONTEXT:
When multiple news articles about the same asset point in opposite directions, your analysis will be used to determine which signal is more credible. To help the system choose correctly:

1. WEIGHT BY EVIDENCE QUALITY:
   - Confirmed facts (earnings released, regulatory decision made) > Analyst opinions > Speculation
   - Multiple corroborating sources > Single source
   - Primary news (company announcement) > Secondary commentary (analyst reaction)

2. WEIGHT BY MARKET CONTEXT:
   - Consider the broader macro environment when assigning direction
   - For crypto: regulatory news and institutional adoption have stronger impact than retail sentiment
   - For IBEX35: ECB decisions, earnings surprises, and M&A are high-conviction events
   - Technical analysis references in news (support/resistance) have LOW predictive value → reduce confidence

3. CONFIDENCE CALIBRATION FOR CONFLICTING SIGNALS:
   - If this news DIRECTLY contradicts a major established trend → confidence 35-50 (contrarian, higher risk)
   - If this news CONFIRMS an established trend → confidence 65-80 (trend continuation)
   - Opinion/forecast articles during clear market trends → confidence 40-55

Respond with this exact JSON:
{{
  "direction": "up|down|neutral",
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <calibrated 0-100; direct confirmed events 70-85, indirect/opinions 55-70, speculative 35-55>,
  "signal_strength": "<high|medium|low>",
  "most_affected_assets": [<2-3 symbols from ALLOWED SYMBOLS, primary subject first>],
  "reasoning": "<UNA frase max 150 chars EN ESPAÑOL explicando el activo principal y la dirección>"
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
    direction = data.get("direction", "neutral")
    if direction not in ("up", "down", "neutral"):
        direction = "neutral"

    timeframe = data.get("timeframe", "hours")
    valid_timeframes = ("immediate", "hours", "hours to days", "days", "days to weeks", "weeks")
    if timeframe not in valid_timeframes:
        timeframe = "hours"

    confidence = float(data.get("confidence", 50))
    confidence = max(0, min(100, confidence))

    signal_strength = data.get("signal_strength", "medium")
    if signal_strength not in ("high", "medium", "low"):
        signal_strength = "medium"

    assets = data.get("most_affected_assets", [])
    if not isinstance(assets, list):
        assets = []
    assets = [str(a).upper() for a in assets[:3]]  # max 3

    reasoning = str(data.get("reasoning", ""))[:300]

    return {
        "market_impact_percent": 0,  # dirección únicamente; el % real se calcula desde precios
        "direction": direction,
        "timeframe": timeframe,
        "confidence": round(confidence),
        "signal_strength": signal_strength,
        "most_affected_assets": assets,
        "reasoning": reasoning,
    }


def _fallback_analysis(event: dict) -> dict:
    """Análisis de fallback basado en palabras clave cuando ningún modelo de IA está disponible."""
    _MAX_FALLBACK_CONFIDENCE = 60
    _BASE_CONFIDENCE = 30
    _SCORE_DIVISOR = 6

    title = (event.get("title") or "").lower()
    desc = (event.get("description") or event.get("summary") or "").lower()
    text = f"{title} {desc}"
    score = event.get("score", 50)
    category = event.get("category", "").lower()

    # Señales alcistas (español e inglés)
    bullish_words = [
        "ceasefire", "peace", "deal", "agreement", "boost", "rise", "increase",
        "record high", "rally", "surge", "upgrade", "outperform", "bullish",
        "recovery", "growth", "profit", "gains", "soars", "jumps", "climbs",
        "sube", "subida", "récord", "acuerdo", "beneficios", "alza", "ganancias",
        "mejora", "supera", "crece", "crecimiento", "positivo", "récord histórico",
        "impulso", "repunta", "recuperación", "avanza", "dispara",
    ]
    # Señales bajistas (español e inglés)
    bearish_words = [
        "war", "attack", "sanction", "conflict", "disruption", "threat", "crisis",
        "collapse", "crash", "plunge", "downgrade", "bearish", "selloff", "sell-off",
        "decline", "loss", "losses", "drops", "falls", "tumbles", "slumps",
        "baja", "bajada", "caída", "pérdidas", "multa", "desplome", "retrocede",
        "pierde", "riesgo", "recesión", "negativo", "hunde", "cae", "rebaja",
        "deterioro", "castigo", "sanción", "quiebra", "impago",
    ]

    bull_positions = {w: text.find(w) for w in bullish_words if w in text}
    bear_positions = {w: text.find(w) for w in bearish_words if w in text}
    bull_hits = len(bull_positions)
    bear_hits = len(bear_positions)

    if bear_hits > bull_hits:
        direction = "down"
    elif bull_hits > bear_hits:
        direction = "up"
    elif bull_hits == bear_hits and bull_hits > 0:
        # Tie with hits on both sides — pick based on which appears first (headline bias)
        first_bull = min(bull_positions.values(), default=9999)
        first_bear = min(bear_positions.values(), default=9999)
        direction = "down" if first_bear < first_bull else "up"
    else:
        # No keyword hits at all — use score to infer direction
        direction = "up" if score > 55 else "down"

    # Activos por categoría (solo IBEX35/ETF/Crypto)
    suggested = event.get("suggested_asset", "")
    if suggested:
        assets = [suggested]
    elif "crypto" in category or "ibex35" in category:
        assets = ["BTC", "ETH"] if "crypto" in category else ["IBEX35"]
    elif "etf" in category:
        assets = ["SPY"]
    else:
        assets = ["IBEX35"]

    return {
        "market_impact_percent": 0,  # solo dirección
        "direction": direction,
        "timeframe": "hours to days",
        "confidence": min(_MAX_FALLBACK_CONFIDENCE, _BASE_CONFIDENCE + score // _SCORE_DIVISOR),
        "most_affected_assets": assets,
        "reasoning": "Análisis automático basado en scoring de taxonomía. Impacto moderado esperado según el tipo de evento.",
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
