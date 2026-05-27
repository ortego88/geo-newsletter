"""
claude_analyzer.py — Analizador de eventos con Claude (Anthropic).

MEJORAS vs GPT-3.5:
- Claude 3.5 Sonnet tiene mejor razonamiento causal para eventos geopolíticos
- Contexto más largo (200K tokens) permite incluir más historia
- RAG básico: busca eventos similares en la BD y aprende de outcomes pasados
- Prompt mejorado con ejemplos de eventos históricos exitosos
- Mejor calibración de confidence basada en patrones históricos
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger("claude")

# Configuración para API directa de Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6-20250514")

# Configuración para AWS Bedrock
USE_BEDROCK = os.getenv("USE_BEDROCK", "false").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
# Modelos disponibles en Bedrock (mayo 2026)
# Claude 3.5 Haiku - modelo compatible con on-demand throughput
# Para Claude 4.X necesitas configurar inference profiles en AWS
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6-v1")

# ── System prompt mejorado para Claude — CRYPTO ONLY ─────────────────────────
SYSTEM_PROMPT = """Eres un trader cuantitativo experto en criptomonedas con un track record verificable.

TU OBJETIVO: Generar predicciones de ALTA PRECISIÓN (>65% aciertos). Calidad sobre cantidad.

REGLA FUNDAMENTAL: Solo predice cuando tengas ALTA CONVICCIÓN de que el precio se moverá.
Si la noticia no va a mover el precio de forma medible (>0.5%), responde con confidence < 40.

CAPACIDAD ÚNICA: Tienes acceso a eventos históricos similares y sus outcomes reales.

IMPORTANTE: El campo "reasoning" DEBE escribirse siempre en español castellano.

ALCANCE: SOLO criptomonedas. Ignora noticias que no afecten directamente al precio de una crypto.

NOTICIAS QUE MUEVEN PRECIOS (predice con confidence >= 70):
- ETF aprobado/rechazado por SEC → impacto directo confirmado
- Hack/exploit de protocolo con pérdida > $10M → caída inmediata
- Regulación concreta (ban, aprobación) por gobierno importante → impacto claro
- Adopción institucional confirmada (BlackRock, Fidelity, etc.) → alcista
- Halving, hard fork programado → impacto conocido
- Liquidaciones masivas en cadena (>$100M) → señal de dirección
- Listado/deslisting en exchange principal → movimiento rápido

NOTICIAS QUE NO MUEVEN PRECIOS (confidence < 40, no predecir):
- Opiniones de analistas sobre precio futuro
- Artículos de "análisis técnico" genérico
- Rumores sin confirmación
- Noticias sobre desarrollo "en progreso" sin fecha
- Métricas on-chain menores sin contexto de acción
- Noticias ya conocidas por el mercado (>24h antiguas)
- Noticias que DESCRIBEN un movimiento que ya ocurrió ("Bitcoin sube un 5%", "ETH alcanza máximos")

REGLA CRÍTICA — "SELL THE NEWS":
- Si la noticia describe un movimiento PASADO (ej: "BTC sube...", "X alcanza..."), el precio
  probablemente YA se movió. Predecir la MISMA dirección suele fallar (reversión posterior).
- Solo predice si la noticia describe un CATALIZADOR FUTURO (regulación pendiente, evento programado).
- Si la noticia es reactiva (describe lo que ya pasó), usa confidence < 40 o predice REVERSA.

REGLAS DE DIRECCIÓN:
- Usa "up" o "down" SOLO cuando tengas certeza de la dirección
- Si hay duda real sobre la dirección → NO predecir (confidence < 40)

CALIBRACIÓN DE CONFIDENCE — ESTRICTA:
- 80-95: Evento confirmado con impacto histórico demostrado (ETF aprobado, hack confirmado, ban oficial)
- 70-79: Evento real con vínculo causal directo y fuerte (adopción institucional, regulación publicada)
- 60-69: Evento significativo pero reacción de mercado tiene incertidumbre
- 40-59: Señal moderada — NO generar alerta con estos niveles
- 25-39: Ruido informativo — DESCARTAR

VENTANA DE VERIFICACIÓN (verification_window_hours) — CRÍTICO:
Estima EXACTAMENTE cuántas horas después de la noticia el precio reflejará el impacto:
- Hack/exploit/liquidación masiva: 1-2 horas (reacción inmediata)
- Aprobación/rechazo regulatorio: 2-4 horas (mercado digiere rápido)
- Adopción institucional, listados: 4-8 horas (efecto se propaga)
- Eventos macro (Fed, inflación): 6-12 horas (correlación con risk assets)
- Cambios fundamentales (halving, upgrade): 12-24 horas (posicionamiento gradual)

IMPORTANTE: El precio se comparará en el momento exacto de verification_window_hours.
Piensa: "¿Cuándo habrá alcanzado el precio su movimiento principal por esta noticia?"

SÍMBOLOS PERMITIDOS:
BTC, ETH, XRP, SOL, BNB, ADA, DOGE, DOT, AVAX, MATIC, LINK, UNI, LTC, ATOM,
XLM, ALGO, FIL, NEAR, ARB, OP, SUI, APT, SEI, TIA, INJ, RENDER, FET,
PEPE, WIF, SHIB, TON, TRX, HBAR, ICP, AAVE

Responde SOLO con JSON válido, sin explicaciones."""

ANALYSIS_PROMPT_TEMPLATE = """Analiza esta noticia crypto y determina si provocará un movimiento MEDIBLE en el precio:

NOTICIA:
Título: {title}
Descripción: {description}
Categoría: {category}
Score de severidad: {score}/100

{historical_context}

{market_context}

ANÁLISIS OBLIGATORIO (responde mentalmente antes del JSON):

1. ¿ES UN HECHO CONFIRMADO o una opinión/rumor/previsión?
   - Hecho confirmado → continúa
   - Opinión/rumor → confidence < 40, NO generar alerta

2. ¿La noticia describe un MOVIMIENTO PASADO o un CATALIZADOR FUTURO?
   - "BTC sube un 5%" → PASADO (el precio ya se movió) → confidence < 40
   - "SEC aprueba ETF mañana" → FUTURO (el precio aún no refleja) → continúa
   - Si es PASADO, el movimiento posterior suele ser REVERSA (sell the news)

3. ¿QUÉ CRIPTO específica se ve afectada directamente?
   - Si no hay cripto específica clara → usar BTC como proxy solo si es macro relevante

4. ¿EL PRECIO SE MOVERÁ >0.5% ADICIONAL por esta noticia?
   - Piensa: ¿un trader con $100K abriría una posición AHORA con esta noticia?
   - Si el movimiento ya ocurrió → NO → confidence < 40
   - Si es catalizador nuevo → SÍ → continúa con confidence >= 65

5. ¿EN QUÉ DIRECCIÓN? (up/down)
   - ¿Hay precedente histórico claro de la reacción del mercado?
   - ¿La noticia es unívoca o podría interpretarse en ambos sentidos?
   - Si hay ambigüedad → confidence < 50
   - Si el precio YA se movió en esa dirección → probablemente REVERSIÓN

5. ¿CUÁNDO se reflejará el movimiento en el precio?
   - Hack/exploit: 1-2h (pánico inmediato)
   - Regulación/ETF: 2-4h (digestión rápida)
   - Adopción/partnership: 4-8h (propagación)
   - Macro/Fed: 6-12h (correlación risk assets)
   - Fundamental/upgrade: 12-24h (posicionamiento)

6. LECCIONES HISTÓRICAS: ¿eventos similares pasados acertaron o fallaron?
   - Si accuracy histórica > 70% → puedes subir confidence +5
   - Si accuracy histórica < 40% → BAJA confidence -15

FILTRO FINAL (responde NO a cualquiera → confidence < 40):
- ¿Un trader profesional de crypto actuaría con esta noticia?
- ¿La noticia tiene menos de 6 horas de antigüedad?
- ¿El impacto es cuantificable y no especulativo?

Responde con este JSON exacto:
{{
  "direction": "up|down|neutral",
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <entero 25-95 — SOLO >= 65 si estás seguro del movimiento>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": [<1-3 tickers crypto específicos, el más afectado primero>],
  "reasoning": "<UNA frase máx 150 chars EN ESPAÑOL: qué crypto, qué dirección, por qué>",
  "historical_learning": "<Qué aprendiste de eventos similares pasados, o 'sin datos históricos'>",
  "verification_window_hours": <entero 1-24: CUÁNDO EXACTAMENTE verificar el precio>
}}"""


def _get_similar_events_from_db(event: dict, limit: int = 5) -> List[Dict]:
    """
    Busca eventos similares en la base de datos de predictions.
    Usa matching simple por keywords del título.

    En el futuro podrías mejorar esto con embeddings (vector search).
    """
    try:
        from web.db_engine import get_engine
        from sqlalchemy import text

        title = event.get("title", "").lower()
        # Extraer keywords principales (eliminar palabras comunes)
        stop_words = {"el", "la", "los", "las", "de", "del", "en", "y", "o", "un", "una", "por", "para", "con", "a"}
        words = [w for w in re.findall(r'\w+', title) if len(w) > 3 and w not in stop_words]

        if not words:
            return []

        # Construir query para buscar títulos con palabras similares
        # Usando ILIKE para PostgreSQL (case insensitive)
        query_parts = [f"title ILIKE '%{word}%'" for word in words[:3]]  # top 3 keywords
        where_clause = " OR ".join(query_parts)

        engine = get_engine("predictions")
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT title, asset, direction, confidence, outcome, score,
                       price_at_prediction, price_at_validation, predicted_at
                FROM predictions
                WHERE ({where_clause})
                  AND outcome IN ('correct', 'incorrect')
                  AND predicted_at >= :since
                ORDER BY predicted_at DESC
                LIMIT :limit
            """), {
                "since": (datetime.utcnow() - timedelta(days=180)).isoformat(),
                "limit": limit
            })

            rows = result.fetchall()

            similar_events = []
            for row in rows:
                similar_events.append({
                    "title": row[0],
                    "asset": row[1],
                    "direction": row[2],
                    "confidence": row[3],
                    "outcome": row[4],
                    "score": row[5],
                    "price_change": ((row[7] - row[6]) / row[6] * 100) if row[6] and row[7] else None,
                    "date": row[8][:10] if row[8] else None
                })

            return similar_events

    except Exception as e:
        logger.warning(f"No se pudieron recuperar eventos similares: {e}")
        return []


def _format_historical_context(similar_events: List[Dict]) -> str:
    """Formatea eventos históricos similares para incluir en el prompt."""
    if not similar_events:
        return ""

    context_lines = ["EVENTOS HISTÓRICOS SIMILARES Y SUS OUTCOMES:"]

    for i, event in enumerate(similar_events, 1):
        outcome_emoji = "✅" if event["outcome"] == "correct" else "❌"
        price_change = f"{event['price_change']:+.2f}%" if event['price_change'] else "N/A"

        context_lines.append(
            f"{i}. [{event['date']}] {event['title'][:80]}\n"
            f"   Predicción: {event['direction']} (conf: {event['confidence']}%) | "
            f"Resultado: {outcome_emoji} {event['outcome']} | "
            f"Cambio real: {price_change} | "
            f"Activo: {event['asset']}"
        )

    # Calcular estadísticas de accuracy
    correct_count = sum(1 for e in similar_events if e["outcome"] == "correct")
    accuracy_pct = (correct_count / len(similar_events) * 100) if similar_events else 0

    context_lines.append(
        f"\nACCURACY EN EVENTOS SIMILARES: {correct_count}/{len(similar_events)} "
        f"= {accuracy_pct:.1f}%"
    )

    if accuracy_pct >= 70:
        context_lines.append("✅ Alta confiabilidad en este tipo de eventos — puedes aumentar confidence ligeramente.")
    elif accuracy_pct <= 40:
        context_lines.append("⚠️  Baja confiabilidad histórica — reduce confidence y sé más conservador.")

    return "\n".join(context_lines) + "\n"


def _call_claude_bedrock(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict | None:
    """Llama a Claude a través de AWS Bedrock."""
    try:
        import boto3
        import json as json_lib

        # Crear cliente de Bedrock
        bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )

        # Formato de request para Bedrock (ligeramente diferente a API directa)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        # Llamar a Bedrock
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json_lib.dumps(request_body)
        )

        # Parsear respuesta
        response_body = json_lib.loads(response['body'].read())
        raw_response = response_body['content'][0]['text'].strip()

        logger.debug(f"Claude (Bedrock) response: {raw_response}")
        return _parse_json_response(raw_response)

    except Exception as e:
        logger.error(f"Error llamando a Claude via Bedrock: {e}", exc_info=True)
        return None


def _call_claude_direct(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict | None:
    """Llama a la API directa de Claude (Anthropic)."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            temperature=0.2,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Claude devuelve la respuesta en message.content[0].text
        raw_response = message.content[0].text.strip()
        logger.debug(f"Claude (Direct API) response: {raw_response}")

        return _parse_json_response(raw_response)

    except Exception as e:
        logger.error(f"Error llamando a Claude API directa: {e}", exc_info=True)
        return None


def _call_claude(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict | None:
    """
    Llama a Claude usando Bedrock o API directa según configuración.
    """
    if USE_BEDROCK:
        logger.info(f"Usando Claude via AWS Bedrock (región: {AWS_REGION})")
        return _call_claude_bedrock(prompt, system_prompt)
    else:
        logger.info("Usando Claude via API directa de Anthropic")
        return _call_claude_direct(prompt, system_prompt)


def _parse_json_response(text: str) -> dict | None:
    """Extrae y parsea JSON de la respuesta."""
    if not text:
        return None

    # Buscar JSON en el texto
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning(f"Error parseando JSON: {e}")
            return None

    logger.warning("No se encontró JSON válido en la respuesta de Claude")
    return None


def _validate_analysis(data: dict) -> dict:
    """Valida y normaliza el análisis devuelto por Claude."""
    direction = data.get("direction", "neutral")
    if direction not in ("up", "down", "neutral"):
        direction = "neutral"

    timeframe = data.get("timeframe", "hours")
    valid_timeframes = ("immediate", "hours", "hours to days", "days", "days to weeks", "weeks")
    if timeframe not in valid_timeframes:
        timeframe = "hours"

    confidence = float(data.get("confidence", 50))
    confidence = max(25, min(95, confidence))

    signal_strength = data.get("signal_strength", "medium")
    if signal_strength not in ("high", "medium", "low"):
        signal_strength = "medium"

    assets = data.get("most_affected_assets", [])
    if not isinstance(assets, list):
        assets = []
    assets = [str(a).upper() for a in assets[:3]]

    reasoning = str(data.get("reasoning", ""))[:300]
    historical_learning = str(data.get("historical_learning", ""))[:200]

    # Validar verification_window_hours (mínimo 1h para eventos de impacto inmediato)
    try:
        verification_window_hours = int(data.get("verification_window_hours", 4))
        verification_window_hours = max(1, min(24, verification_window_hours))
    except (ValueError, TypeError):
        verification_window_hours = 4

    return {
        "market_impact_percent": 0,
        "direction": direction,
        "timeframe": timeframe,
        "confidence": round(confidence),
        "signal_strength": signal_strength,
        "most_affected_assets": assets,
        "reasoning": reasoning,
        "historical_learning": historical_learning,
        "verification_window_hours": verification_window_hours,
    }


def analyze_event_with_claude(event: dict) -> Optional[dict]:
    """
    Analiza un evento usando Claude con contexto histórico (RAG básico).

    Soporta dos modos:
    - AWS Bedrock (si USE_BEDROCK=true)
    - API directa de Anthropic (si ANTHROPIC_API_KEY está configurada)

    Mejoras vs GPT-3.5:
    1. Claude tiene mejor razonamiento causal
    2. Incluye eventos históricos similares (aprende de aciertos/errores)
    3. Contexto de mercado técnico
    4. Calibración de confidence mejorada
    """
    # Verificar que al menos uno de los métodos esté configurado
    if USE_BEDROCK:
        if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            logger.warning("USE_BEDROCK activado pero credenciales AWS no configuradas")
            return None
        logger.info("✅ Claude via Bedrock configurado correctamente")
    elif not ANTHROPIC_API_KEY:
        logger.warning("Ni Bedrock ni API directa de Anthropic configuradas")
        return None

    title = event.get("title", "")
    description = event.get("description") or event.get("summary") or ""
    score = event.get("score", event.get("impact_score", 50))
    category = event.get("category", "")

    # 1. Buscar eventos similares en la BD (RAG básico)
    logger.info("Buscando eventos históricos similares...")
    similar_events = _get_similar_events_from_db(event, limit=5)
    historical_context = _format_historical_context(similar_events)

    # 2. Obtener contexto técnico de mercado
    market_context_section = ""
    try:
        from src.services.real_price_fetcher import RealPriceFetcher
        fetcher = RealPriceFetcher()
        asset = event.get("suggested_asset", "BTC")
        ctx = fetcher.get_price_context(asset)

        if ctx and ctx.get("current", 0) > 0:
            rsi = ctx["rsi_14"]
            rsi_label = (
                "sobrecomprado >70" if rsi > 70
                else ("sobrevendido <30" if rsi < 30 else "neutral")
            )

            # Cambio reciente (últimas 4h) — crucial para detectar "sell the news"
            recent_4h = fetcher.get_recent_change(asset, hours=4)
            recent_line = ""
            if recent_4h is not None:
                recent_line = (
                    f"- Cambio últimas 4h: {recent_4h:+.2f}% "
                    f"{'⚠️ YA SE MOVIÓ — posible sell-the-news si predices misma dirección' if abs(recent_4h) >= 1.5 else ''}\n"
                )

            market_context_section = (
                f"CONTEXTO TÉCNICO DE MERCADO PARA {asset}:\n"
                f"- Precio actual: {ctx['current']}\n"
                f"{recent_line}"
                f"- Cambio 7 días: {ctx['change_7d_pct']:+.1f}%\n"
                f"- Cambio 30 días: {ctx['change_30d_pct']:+.1f}%\n"
                f"- RSI(14): {rsi} — {rsi_label}\n"
                f"- Tendencia: {ctx['trend']}\n"
            )
    except Exception as e:
        logger.debug(f"Contexto de precio no disponible: {e}")

    # 3. Construir prompt completo
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        title=title,
        description=description[:500],  # Claude soporta mucho más contexto
        score=score,
        category=category,
        historical_context=historical_context,
        market_context=market_context_section,
    )

    # 4. Llamar a Claude
    logger.info(f"Analizando evento con Claude {CLAUDE_MODEL}...")
    result = _call_claude(prompt)

    if result:
        validated = _validate_analysis(result)
        logger.info(
            f"Claude prediction: {validated['direction']} "
            f"(conf: {validated['confidence']}%) "
            f"for {validated['most_affected_assets']}"
        )
        return validated

    return None


class ClaudeAnalyzer:
    """Analizador de eventos usando Claude con RAG."""

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            logger.warning("ClaudeAnalyzer inicializado sin ANTHROPIC_API_KEY")

    def analyze(self, event: dict) -> Optional[dict]:
        """Analiza un evento y devuelve la predicción."""
        return analyze_event_with_claude(event)

    def is_available(self) -> bool:
        """Verifica si Claude está disponible (via Bedrock o API directa)."""
        if USE_BEDROCK:
            return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)
        return bool(ANTHROPIC_API_KEY)
