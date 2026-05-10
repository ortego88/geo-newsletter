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
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

# Configuración para AWS Bedrock
USE_BEDROCK = os.getenv("USE_BEDROCK", "false").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
# Modelos disponibles en Bedrock (mayo 2026)
# Claude 3.5 Haiku - modelo compatible con on-demand throughput
# Para Claude 4.X necesitas configurar inference profiles en AWS
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-haiku-20241022-v1:0")

# ── System prompt mejorado para Claude ────────────────────────────────────────
SYSTEM_PROMPT = """Eres un analista cuantitativo experto en mercados financieros españoles (IBEX 35), ETFs y criptomonedas.

CAPACIDAD ÚNICA: Tienes acceso a eventos históricos similares y sus outcomes reales. Usa este contexto para calibrar tus predicciones.

IMPORTANTE: El campo "reasoning" DEBE escribirse siempre en español castellano. Todos los demás campos JSON mantienen su formato especificado.

ALCANCE: Solo analiza noticias sobre empresas IBEX 35, ETFs y criptomonedas.

REGLAS DE ASIGNACIÓN DE ACTIVOS (orden de prioridad estricto):
1. Noticia sobre una EMPRESA ESPECÍFICA del IBEX 35 → usar el ticker de esa empresa PRIMERO
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
   [... resto de empresas IBEX 35 ...]

2. Noticia sobre IBEX 35 en general (sin empresa específica) → ["IBEX35"]
3. ETFs específicos → usar el ticker del ETF
4. Criptomonedas → BTC/ETH como primarios

REGLAS DE DIRECCIÓN — CRÍTICO:
- Usa "up" o "down" en casi todos los casos
- Reserva "neutral" SOLO para:
  * Noticias puramente procedimentales sin impacto de mercado
  * Eventos donde efectos opuestos se cancelan perfectamente Y puedes explicar por qué

CALIBRACIÓN DE CONFIDENCE — USA EL RANGO COMPLETO 25–95:
- 80-95: Evento directo, confirmado, inequívoco (resultados publicados, decisión regulatoria tomada)
- 65-79: Vínculo causal fuerte, múltiples fuentes corroboradas
- 50-64: Vínculo moderado — evento real pero reacción de mercado incierta
- 35-49: Opinión de analista, previsión, retórica política, rumor de una sola fuente
- 25-34: Especulativo, señales contradictorias, conexión muy indirecta

APRENDIZAJE DE HISTORIA: Cuando recibas eventos similares pasados con sus outcomes:
- Si eventos similares tuvieron alta tasa de acierto → aumenta confidence +5-10 puntos
- Si eventos similares fallaron frecuentemente → reduce confidence -10-15 puntos
- Si no hay patrón claro → mantén calibración base

FILTROS DE CALIDAD — REDUCE CONFIDENCE CUANDO:
- El título usa verbos de atribución: "Dice", "Según", "Advierte", "Afirma" → cap en 55
- La fuente es opinion o editorial → cap en 50
- El evento ya está ampliamente descontado (ej: decisión de tasas esperada) → cap en 60
- Noticia sobre tendencia macro general sin catalizador específico → cap en 55

SÍMBOLOS PERMITIDOS:
- IBEX 35: IBEX35, ACS, ACX, AENA, ALM, AMS, ANA, BBVA, BKT, CABK, CLNX, COL, ELE, ENG,
           FDR, FER, GRF, IAG, IBE, IDR, ITX, LOG, MAP, MEL, MRL, MTS, NTGY, PHM,
           RED, REP, ROVI, SAB, SAN, SGRE, TEF
- ETFs: SPY, QQQ, GLD, SLV, IWM, EWZ, EEM, VIX, ARKK, TLT, XLF, XLE, DIA
- Crypto: BTC, ETH, XRP, SOL, BNB, ADA, DOGE, DOT, AVAX, MATIC, LINK, UNI,
          LTC, ATOM, XLM, ALGO, FIL, NEAR, ARB, OP

Responde SOLO con JSON válido, sin explicaciones."""

ANALYSIS_PROMPT_TEMPLATE = """Analiza este evento de mercado y determina su impacto financiero en IBEX 35, ETFs o criptomonedas:

EVENTO ACTUAL:
Título: {title}
Descripción: {description}
Categoría: {category}
Score de severidad: {score}/100

{historical_context}

{market_context}

ANÁLISIS PASO A PASO (piensa cada punto antes de responder):
1. ¿QUIÉN es el sujeto de esta noticia? (empresa específica / índice / crypto / macro)
2. ¿QUÉ ocurrió? (hecho confirmado / opinión de analista / rumor / previsión)
3. ¿CUÁL es la reacción de mercado más probable a corto plazo? (up / down / neutral — evita neutral salvo justificación)
4. ¿QUÉ TAN SEGURO estás? (25-95, usa rango completo, consulta reglas de calibración)
5. ¿CUÁNDO verificar? Estima cuántas HORAS después de esta alerta debería ocurrir el movimiento esperado:
   - Eventos de impacto INMEDIATO (datos económicos, decisiones de tasas, earnings): 2-4 horas
   - Noticias de impacto A CORTO PLAZO (sanciones, acuerdos geopolíticos): 4-8 horas
   - Eventos de tendencia A LARGO PLAZO (cambios regulatorios, restructuraciones): 12-24 horas
6. ¿HAY EVENTOS SIMILARES EN LA HISTORIA? Si sí, ¿qué enseñan sobre la dirección y confidence correctas?

VERIFICACIÓN DE CALIDAD antes de finalizar:
- ¿La noticia se basa en un hecho confirmado o solo en opinión de alguien? (opinión → confidence ≤55)
- ¿El título usa "Dice", "Advierte", "Según"? (→ confidence ≤55)
- ¿Esta noticia ya es ampliamente conocida o está descontada? (→ confidence ≤60)
- ¿Un trader profesional actuaría con esta noticia? (no → confidence ≤45)
- ¿Los eventos históricos similares tuvieron buen accuracy? (sí → +5-10 confidence; no → -10-15 confidence)

Responde con este JSON exacto:
{{
  "direction": "up|down|neutral",
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <entero 25-95, calibrado por reglas anteriores>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": [<2-3 símbolos de ALLOWED SYMBOLS, sujeto principal primero>],
  "reasoning": "<UNA frase máx 150 chars EN ESPAÑOL explicando activo principal, dirección y por qué>",
  "historical_learning": "<Si usaste eventos históricos, explica brevemente qué aprendiste de ellos>",
  "verification_window_hours": <entero 2-24 estimando HORAS después de esta alerta para verificar>
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

    # Validar verification_window_hours
    try:
        verification_window_hours = int(data.get("verification_window_hours", 6))
        verification_window_hours = max(2, min(24, verification_window_hours))
    except (ValueError, TypeError):
        verification_window_hours = 6

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
        asset = event.get("suggested_asset", "BTC")
        ctx = RealPriceFetcher().get_price_context(asset)

        if ctx and ctx.get("current", 0) > 0:
            rsi = ctx["rsi_14"]
            rsi_label = (
                "sobrecomprado >70" if rsi > 70
                else ("sobrevendido <30" if rsi < 30 else "neutral")
            )

            market_context_section = (
                f"CONTEXTO TÉCNICO DE MERCADO PARA {asset}:\n"
                f"- Precio actual: {ctx['current']}\n"
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
