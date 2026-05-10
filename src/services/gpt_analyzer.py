"""
gpt_analyzer.py — Analizador de eventos con IA.
Soporta OpenAI (producción) y Ollama (desarrollo local).

CAMBIOS v2 (mejoras de accuracy):
- System prompt más estricto: fuerza a usar "up"/"down" con más criterio y menos "neutral".
- Nuevas reglas de contexto de mercado integradas en el prompt de análisis.
- Mejora del fallback: usa el score y una heurística de posición de keywords
  (las palabras al inicio del título tienen más peso que al final).
- Se añade instrucción explícita para ignorar ruido (opiniones de analistas sin datos,
  rumores no confirmados) y rebajar la confidence a <45 en esos casos.
- market_impact_percent ya no se usa para dirección (solo dirección cualitativa),
  se simplifica a 0 siempre desde este módulo.
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

# ── System prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert quantitative financial analyst specialising in IBEX 35 (Spanish stock market), ETFs, and cryptocurrency market events.
IMPORTANT: The "reasoning" field MUST always be written in Spanish (Castilian). All other JSON fields keep their specified format.

SCOPE: Only analyse news about IBEX 35 companies, ETFs, and cryptocurrencies.

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
3. ETFs specifically → use the ETF ticker
4. Crypto news → BTC/ETH as primary

DIRECTION RULES — CRITICAL:
- Use "up" or "down" in almost all cases. Reserve "neutral" ONLY for:
  * Purely procedural news with zero market impact
  * Events where opposite effects perfectly cancel out AND you can explain why

CONFIDENCE CALIBRATION — USE THE FULL 25–95 RANGE:
- 80-95: Direct, confirmed, unambiguous event (earnings released, regulatory decision taken)
- 65-79: Strong causal link, multiple corroborating sources
- 50-64: Moderate link — event is real but market reaction uncertain
- 35-49: Analyst opinion, forecast, political rhetoric, single-source rumour
- 25-34: Speculative, contradictory signals, very indirect connection

QUALITY FILTERS — REDUCE CONFIDENCE WHEN:
- The news title uses attribution verbs: "Says", "According to", "Warns", "Claims" → cap at 55
- The source is an opinion piece or editorial → cap at 50
- The event is already widely priced in (e.g., widely expected rate decision) → cap at 60
- The news is about a general macro trend with no specific catalyst → cap at 55

ALLOWED SYMBOLS ONLY:
- IBEX 35: IBEX35, ACS, ACX, AENA, ALM, AMS, ANA, BBVA, BKT, CABK, CLNX, COL, ELE, ENG,
           FDR, FER, GRF, IAG, IBE, IDR, ITX, LOG, MAP, MEL, MRL, MTS, NTGY, PHM,
           RED, REP, ROVI, SAB, SAN, SGRE, TEF
- ETFs: SPY, QQQ, GLD, SLV, IWM, EWZ, EEM, VIX, ARKK, TLT, XLF, XLE, DIA
- Crypto: BTC, ETH, XRP, SOL, BNB, ADA, DOGE, DOT, AVAX, MATIC, LINK, UNI,
          LTC, ATOM, XLM, ALGO, FIL, NEAR, ARB, OP

Respond ONLY with valid JSON, no explanations."""

ANALYSIS_PROMPT_TEMPLATE = """Analyse this market event and determine its financial impact on IBEX 35, ETFs, or cryptocurrencies:

Title: {title}
Description: {description}
Category: {category}
Severity score: {score}/100

STEP-BY-STEP ANALYSIS (think through each point before responding):
1. WHO is this news about? (specific company / index / crypto / macro)
2. WHAT happened? (confirmed fact / analyst opinion / rumour / forecast)
3. WHAT is the most likely short-term market reaction? (up / down / neutral — avoid neutral unless justified)
4. HOW certain are you? (0-100, use full range, see calibration rules)

QUALITY CHECK before finalising:
- Is the news based on a confirmed fact or just someone's opinion? (opinion → confidence ≤55)
- Is the title using "Says", "Warns", "According to"? (→ confidence ≤55)
- Is this news already widely known or priced in? (→ confidence ≤60)
- Would a professional trader act on this news? (no → confidence ≤45)

Respond with this exact JSON:
{{
  "direction": "up|down|neutral",
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <integer 25-95, calibrated per rules above>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": [<2-3 symbols from ALLOWED SYMBOLS, primary subject first>],
  "reasoning": "<UNA frase max 150 chars EN ESPAÑOL explicando activo principal, dirección y por qué>"
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
            temperature=0.1,  # Reducido de 0.2 a 0.1 para respuestas más consistentes
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
            "options": {"temperature": 0.1, "num_predict": 400},  # temperatura reducida
        }
        resp = requests.post(ollama_url, json=payload, timeout=30)
        if resp.status_code == 404:
            logger.info("Ollama /api/chat not available, falling back to /api/generate")
            generate_url = f"{OLLAMA_HOST}/api/generate"
            full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
            payload_gen = {
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 400},
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
    confidence = max(25, min(95, confidence))  # forzar rango 25-95

    signal_strength = data.get("signal_strength", "medium")
    if signal_strength not in ("high", "medium", "low"):
        signal_strength = "medium"

    assets = data.get("most_affected_assets", [])
    if not isinstance(assets, list):
        assets = []
    assets = [str(a).upper() for a in assets[:3]]

    reasoning = str(data.get("reasoning", ""))[:300]

    return {
        "market_impact_percent": 0,
        "direction": direction,
        "timeframe": timeframe,
        "confidence": round(confidence),
        "signal_strength": signal_strength,
        "most_affected_assets": assets,
        "reasoning": reasoning,
    }


def _fallback_analysis(event: dict) -> dict:
    """
    Análisis de fallback mejorado cuando ningún modelo de IA está disponible.

    Mejoras v2:
    - Peso por posición: keywords al inicio del título tienen más peso (headline bias).
    - Umbral de confidence más bajo para evitar falsos positivos.
    - Lógica de empate mejorada: considera el contexto del score.
    """
    _MAX_FALLBACK_CONFIDENCE = 55   # Reducido de 60 — el fallback es menos fiable que la IA
    _BASE_CONFIDENCE = 30
    _SCORE_DIVISOR = 8              # Antes 6 — crecimiento más gradual

    title = (event.get("title") or "").lower()
    desc = (event.get("description") or event.get("summary") or "").lower()
    score = event.get("score", 50)
    category = event.get("category", "").lower()

    # ── Keywords alcistas (ES + EN) ──────────────────────────────────────────
    bullish_words = [
        "ceasefire", "peace", "deal", "agreement", "boost", "rise", "increase",
        "record high", "rally", "surge", "upgrade", "outperform", "bullish",
        "recovery", "growth", "profit", "gains", "soars", "jumps", "climbs",
        "sube", "subida", "récord", "acuerdo", "beneficios", "alza", "ganancias",
        "mejora", "supera", "crece", "crecimiento", "positivo", "récord histórico",
        "impulso", "repunta", "recuperación", "avanza", "dispara", "compra",
        "aprobación", "autorización", "alianza", "fusión", "adquisición",
    ]

    # ── Keywords bajistas (ES + EN) ──────────────────────────────────────────
    bearish_words = [
        "war", "attack", "sanction", "conflict", "disruption", "threat", "crisis",
        "collapse", "crash", "plunge", "downgrade", "bearish", "selloff", "sell-off",
        "decline", "loss", "losses", "drops", "falls", "tumbles", "slumps",
        "baja", "bajada", "caída", "pérdidas", "multa", "desplome", "retrocede",
        "pierde", "riesgo", "recesión", "negativo", "hunde", "cae", "rebaja",
        "deterioro", "castigo", "sanción", "quiebra", "impago", "demanda judicial",
        "investigación", "fraude", "escándalo",
    ]

    # Buscar posición de cada keyword en el título (headline bias)
    # Una keyword al inicio del título tiene más peso (posición 0 = peso máximo)
    title_len = max(len(title), 1)

    bull_score_total = 0.0
    bear_score_total = 0.0

    for w in bullish_words:
        pos = title.find(w)
        if pos >= 0:
            # Peso inversamente proporcional a la posición (inicio = más peso)
            weight = 1.0 + (1.0 - pos / title_len)
            bull_score_total += weight
        elif w in desc:
            bull_score_total += 0.5  # keywords en descripción tienen menos peso

    for w in bearish_words:
        pos = title.find(w)
        if pos >= 0:
            weight = 1.0 + (1.0 - pos / title_len)
            bear_score_total += weight
        elif w in desc:
            bear_score_total += 0.5

    if bear_score_total > bull_score_total:
        direction = "down"
    elif bull_score_total > bear_score_total:
        direction = "up"
    else:
        # Empate: usar el score para desempatar (scores altos suelen venir
        # de noticias con mayor impacto, que tienden a ser bajistas para activos de riesgo)
        direction = "up" if score > 60 else "down"

    suggested = event.get("suggested_asset", "")
    if suggested:
        assets = [suggested]
    elif "crypto" in category:
        assets = ["BTC", "ETH"]
    elif "ibex35" in category or "mercados" in category:
        assets = ["IBEX35"]
    elif "etf" in category:
        assets = ["SPY"]
    else:
        assets = ["IBEX35"]

    confidence_value = min(
        _MAX_FALLBACK_CONFIDENCE,
        _BASE_CONFIDENCE + score // _SCORE_DIVISOR
    )

    return {
        "market_impact_percent": 0,
        "direction": direction,
        "timeframe": "hours to days",
        "confidence": confidence_value,
        "signal_strength": "low",  # el fallback siempre es baja confianza
        "most_affected_assets": assets,
        "reasoning": "Análisis automático de fallback (IA no disponible). Impacto moderado según taxonomía.",
    }


def analyze_event(event: dict) -> dict:
    """
    Analiza un evento y devuelve el análisis estructurado.

    ORDEN DE PRIORIDAD (v3 - migrado a Claude):
    1. Claude (Anthropic) - si ANTHROPIC_API_KEY está configurado [MEJOR ACCURACY]
    2. OpenAI - si OPENAI_API_KEY está configurado [FALLBACK]
    3. Ollama - si está disponible [FALLBACK LOCAL]
    4. Análisis por keywords [ÚLTIMO RECURSO]

    Claude es ahora la opción prioritaria por su mejor razonamiento causal
    y capacidad de aprender de eventos históricos similares.
    """
    # 1. INTENTAR CON CLAUDE PRIMERO (mejor accuracy)
    try:
        from src.services.claude_analyzer import analyze_event_with_claude, ClaudeAnalyzer

        # Verificar si Claude está disponible (via Bedrock O API directa)
        analyzer = ClaudeAnalyzer()
        if analyzer.is_available():
            logger.info("🚀 Analizando evento con Claude (Anthropic) + RAG...")
            result = analyze_event_with_claude(event)
            if result:
                logger.info("✅ Análisis completado con Claude")
                return result
            logger.warning("Claude no pudo analizar el evento, intentando fallback...")
        else:
            logger.debug("Claude no está configurado (ni Bedrock ni API directa), usando fallback")
    except Exception as e:
        logger.warning(f"Error con Claude: {e}, intentando fallback...")
        import traceback
        logger.debug(traceback.format_exc())

    # 2. FALLBACK A OPENAI
    title = event.get("title", "")
    description = event.get("description") or event.get("summary") or ""
    score = event.get("score", event.get("impact_score", 50))
    category = event.get("category", "")

    # Enriquecer el prompt con contexto técnico de precio
    market_context_section = ""
    try:
        from src.services.real_price_fetcher import RealPriceFetcher
        asset = event.get("suggested_asset", "BTC")
        ctx = RealPriceFetcher().get_price_context(asset)
        if ctx and ctx.get("current", 0) > 0:
            rsi = ctx["rsi_14"]
            rsi_label = (
                "sobrecomprado >70 — sé más cauto con señales alcistas"
                if rsi > 70
                else ("sobrevendido <30 — sé más cauto con señales bajistas" if rsi < 30 else "neutral")
            )
            market_context_section = (
                f"\n\nCONTEXTO TÉCNICO DE MERCADO PARA {asset}:\n"
                f"- Precio actual: {ctx['current']}\n"
                f"- Cambio 7 días: {ctx['change_7d_pct']:+.1f}% (media 7d: {ctx['avg_7d']})\n"
                f"- Cambio 30 días: {ctx['change_30d_pct']:+.1f}% (media 30d: {ctx['avg_30d']})\n"
                f"- RSI(14): {rsi} — {rsi_label}\n"
                f"- Tendencia técnica: {ctx['trend']}\n\n"
                "Usa este contexto para calibrar: si el activo ya está en tendencia fuerte "
                "en la misma dirección que tu predicción, aumenta confidence ligeramente. "
                "Si va en contra de la tendencia, reduce confidence."
            )
    except Exception as e:
        logger.debug(f"get_price_context no disponible: {e}")

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        title=title,
        description=description[:400],
        score=score,
        category=category,
    ) + market_context_section

    result = None
    if OPENAI_API_KEY:
        logger.info("Analizando evento con OpenAI (fallback)...")
        result = _call_openai(prompt)
    else:
        logger.info("Analizando evento con Ollama (fallback)...")
        result = _call_ollama(prompt)

    if result:
        return _validate_analysis(result)

    logger.warning("Modelo de IA no disponible, usando análisis de fallback mejorado")
    return _fallback_analysis(event)


class EventAnalyzer:
    def __init__(self, use_ollama: bool = True):
        self.use_ollama = use_ollama

    def analyze(self, event: dict) -> dict:
        return analyze_event(event)
