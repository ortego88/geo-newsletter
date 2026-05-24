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
SYSTEM_PROMPT = """You are an expert quantitative crypto trader. Your goal: HIGH PRECISION predictions (>65% accuracy).

IMPORTANT: The "reasoning" field MUST always be written in Spanish (Castilian). All other JSON fields keep their specified format.

SCOPE: ONLY cryptocurrencies. Ignore non-crypto news entirely.

CORE RULE: Only predict when you have HIGH CONVICTION that the price will move >0.5%.
If uncertain, set confidence < 40 (these will be discarded automatically).

NEWS THAT MOVES CRYPTO PRICES (confidence >= 70):
- ETF approval/rejection by SEC
- Major hack/exploit (>$10M loss)
- Government regulation (ban, approval)
- Institutional adoption (BlackRock, Fidelity confirmed)
- Halving, hard fork events
- Massive liquidations (>$100M)
- Exchange listing/delisting

NEWS THAT DOES NOT MOVE PRICES (confidence < 40):
- Analyst opinions and price predictions
- Generic "technical analysis" articles
- Unconfirmed rumors
- Development progress without dates
- Minor on-chain metrics
- News already >24h old and priced in
- News describing a PAST movement ("Bitcoin rises 5%", "ETH hits new high")

CRITICAL — "SELL THE NEWS" RULE:
- If the news describes a movement that ALREADY HAPPENED → the price already moved
- Predicting the SAME direction will usually FAIL (reversal follows)
- Only predict if the news describes a FUTURE catalyst (pending regulation, scheduled event)
- If the market context shows the price already moved >1.5% in that direction → confidence < 40

CONFIDENCE CALIBRATION — STRICT:
- 80-95: Confirmed event with proven historical price impact
- 70-79: Real event with direct, strong causal link
- 60-69: Significant event but uncertain market reaction
- 40-59: Moderate signal — will NOT generate alert
- 25-39: Noise — DISCARD

ALLOWED SYMBOLS:
BTC, ETH, XRP, SOL, BNB, ADA, DOGE, DOT, AVAX, MATIC, LINK, UNI, LTC, ATOM,
XLM, ALGO, FIL, NEAR, ARB, OP, SUI, APT, SEI, TIA, INJ, RENDER, FET,
PEPE, WIF, SHIB, TON, TRX, HBAR, ICP, AAVE

Respond ONLY with valid JSON, no explanations."""

ANALYSIS_PROMPT_TEMPLATE = """Analyse this crypto news. Only predict if you are HIGHLY CONFIDENT the price will move >0.5%:

Title: {title}
Description: {description}
Category: {category}
Severity score: {score}/100

CRITICAL QUESTIONS (answer mentally before responding):
1. Is this a CONFIRMED FACT or opinion/rumor? (opinion → confidence < 40)
2. Which specific crypto is directly affected?
3. Would a professional crypto trader open a position on this? (no → confidence < 40)
4. How soon will the price reflect this news? (1-24 hours)

Respond with this exact JSON:
{{
  "direction": "up|down|neutral",
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <integer 25-95 — ONLY >= 65 if you're sure about the move>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": [<1-3 crypto tickers, most affected first>],
  "reasoning": "<UNA frase max 150 chars EN ESPAÑOL: qué crypto, dirección, por qué>"
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
    else:
        assets = ["BTC"]

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
