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

# ── Token usage tracking ─────────────────────────────────────────────────────
_token_usage = {"date": "", "input": 0, "output": 0, "calls": 0}


def _track_token_usage(input_tokens: int, output_tokens: int):
    """Tracks daily token usage and logs a summary each cycle."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _token_usage["date"] != today:
        if _token_usage["date"]:
            logger.info(
                f"💰 Token usage (final {_token_usage['date']}): "
                f"input={_token_usage['input']:,} output={_token_usage['output']:,} "
                f"calls={_token_usage['calls']}"
            )
        _token_usage["date"] = today
        _token_usage["input"] = 0
        _token_usage["output"] = 0
        _token_usage["calls"] = 0
    _token_usage["input"] += input_tokens
    _token_usage["output"] += output_tokens
    _token_usage["calls"] += 1


def get_daily_token_usage() -> dict:
    """Returns current day's token usage stats."""
    return {
        "date": _token_usage["date"],
        "input_tokens": _token_usage["input"],
        "output_tokens": _token_usage["output"],
        "calls": _token_usage["calls"],
    }


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
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "arn:aws:bedrock:us-east-1:713463137909:inference-profile/global.anthropic.claude-sonnet-4-6")

# ── System prompt mejorado para Claude — CRYPTO ONLY ─────────────────────────
SYSTEM_PROMPT = """Eres un analista crypto. Tu único objetivo es decidir si esta noticia moverá el precio >2% en las próximas 24 horas.

REGLAS (simples, sin excepciones):
1. Solo predice si es un HECHO CONFIRMADO — no rumor, no opinión, no análisis técnico
2. Solo predice si el evento NO ha sido ya descontado por el mercado (noticia < 6h)
3. Solo predice si la causalidad es directa y clara (hack → bajada, ETF aprobado → subida)
4. Si tienes dudas → confidence < 50
5. Usa siempre 24 horas como ventana de verificación

EVENTOS QUE GENERAN SEÑAL (confidence >= 70):
- Hack/exploit confirmado con pérdida > $10M → DOWN inmediato
- ETF aprobado/rechazado por regulador → impacto directo
- Ban o regulación concreta por gobierno importante → DOWN
- Adopción institucional confirmada (empresa real comprando) → UP
- Liquidaciones masivas en cascada (>$100M) → DOWN continúa
- Listado/deslisting en Binance/Coinbase → movimiento inmediato

DESCARTAR (confidence < 40):
- "Analista dice que BTC podría subir..."
- Descripciones de movimientos ya ocurridos
- Artículos de análisis técnico o predicciones de precio
- Rumores sin confirmación oficial
- Noticias > 6 horas de antigüedad

CALIBRACIÓN:
- 80-95: Hecho confirmado con impacto histórico demostrado
- 70-79: Evento real con causalidad directa clara
- 50-69: NO generar alerta
- < 50: Descartar

ALCANCE: Solo criptomonedas. El reasoning SIEMPRE en español.

Responde SOLO con JSON válido, sin explicaciones."""

ANALYSIS_PROMPT_TEMPLATE = """Noticia crypto:
Título: {title}
Descripción: {description}
Score: {score}/100

{market_context}

Decide: ¿moverá el precio >2% en las próximas 24 horas?

Responde con JSON exacto:
{{
  "direction": "up|down|neutral",
  "timeframe": "hours",
  "confidence": <entero 25-95>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": [<1-3 tickers, el más afectado primero>],
  "reasoning": "<UNA frase máx 120 chars EN ESPAÑOL: qué crypto, dirección, por qué>",
  "historical_learning": "sin datos históricos",
  "verification_window_hours": 24
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


def _call_claude_bedrock(prompt: str, system_prompt: str = SYSTEM_PROMPT, max_tokens: int = 1024) -> dict | None:
    """Llama a Claude a través de AWS Bedrock con prompt caching."""
    try:
        import boto3
        import json as json_lib

        bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )

        # Prompt caching: system como array con cache_control
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.4,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json_lib.dumps(request_body)
        )

        response_body = json_lib.loads(response['body'].read())
        raw_response = response_body['content'][0]['text'].strip()

        usage = response_body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        if cache_read:
            logger.info(f"🔢 Tokens (Bedrock): input={input_tokens} output={output_tokens} cache_read={cache_read} 💰 CACHED")
        else:
            logger.info(f"🔢 Tokens (Bedrock): input={input_tokens} output={output_tokens} cache_creation={cache_creation}")
        _track_token_usage(input_tokens, output_tokens)

        logger.debug(f"Claude (Bedrock) response: {raw_response}")
        return _parse_json_response(raw_response)

    except Exception as e:
        logger.error(f"Error llamando a Claude via Bedrock: {e}", exc_info=True)
        return None


def _call_claude_direct(prompt: str, system_prompt: str = SYSTEM_PROMPT, max_tokens: int = 1024) -> dict | None:
    """Llama a la API directa de Claude (Anthropic) con prompt caching."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            temperature=0.2,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        raw_response = message.content[0].text.strip()

        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        cache_read = getattr(message.usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(message.usage, "cache_creation_input_tokens", 0) or 0
        if cache_read:
            logger.info(f"🔢 Tokens (Direct): input={input_tokens} output={output_tokens} cache_read={cache_read} 💰 CACHED")
        else:
            logger.info(f"🔢 Tokens (Direct): input={input_tokens} output={output_tokens} cache_creation={cache_creation}")
        _track_token_usage(input_tokens, output_tokens)

        logger.debug(f"Claude (Direct API) response: {raw_response}")

        return _parse_json_response(raw_response)

    except Exception as e:
        logger.error(f"Error llamando a Claude API directa: {e}", exc_info=True)
        return None


def _call_claude(prompt: str, system_prompt: str = SYSTEM_PROMPT, max_tokens: int = 1024) -> dict | None:
    """
    Llama a Claude usando Bedrock o API directa según configuración.
    Si Bedrock falla, intenta con API directa como fallback.
    """
    if USE_BEDROCK:
        logger.info(f"Usando Claude via AWS Bedrock (región: {AWS_REGION})")
        result = _call_claude_bedrock(prompt, system_prompt, max_tokens)
        if result is not None:
            return result
        if ANTHROPIC_API_KEY:
            logger.warning("Bedrock falló, intentando con API directa como fallback...")
            return _call_claude_direct(prompt, system_prompt, max_tokens)
        return None
    else:
        logger.info("Usando Claude via API directa de Anthropic")
        return _call_claude_direct(prompt, system_prompt, max_tokens)


def _call_claude_raw(prompt: str, system_prompt: str = SYSTEM_PROMPT, max_tokens: int = 2048) -> str | None:
    """Like _call_claude but returns the raw text response (for batch parsing)."""
    try:
        if USE_BEDROCK:
            import boto3
            import json as json_lib

            bedrock = boto3.client(
                service_name='bedrock-runtime',
                region_name=AWS_REGION,
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0.4,
                "system": [
                    {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
                ],
                "messages": [{"role": "user", "content": prompt}]
            }
            response = bedrock.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json_lib.dumps(request_body)
            )
            response_body = json_lib.loads(response['body'].read())
            usage = response_body.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            logger.info(f"🔢 Tokens (Bedrock batch): input={input_tokens} output={output_tokens} cache_read={cache_read}")
            _track_token_usage(input_tokens, output_tokens)
            return response_body['content'][0]['text'].strip()
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                temperature=0.2,
                system=[
                    {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": prompt}]
            )
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            cache_read = getattr(message.usage, "cache_read_input_tokens", 0) or 0
            logger.info(f"🔢 Tokens (Direct batch): input={input_tokens} output={output_tokens} cache_read={cache_read}")
            _track_token_usage(input_tokens, output_tokens)
            return message.content[0].text.strip()
    except Exception as e:
        logger.error(f"Error in _call_claude_raw: {e}", exc_info=True)
        return None


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

    # RAG desactivado hasta tener >100 predicciones limpias con >60% accuracy
    # El historial actual contamina las predicciones con ejemplos negativos
    similar_events = []
    historical_context = ""

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


BATCH_PROMPT_TEMPLATE = """Analiza estas {count} noticias crypto. Para CADA una, determina si provocará un movimiento MEDIBLE en el precio.

{events_block}

Responde con un JSON array con {count} objetos, uno por noticia, EN EL MISMO ORDEN.
Cada objeto debe tener exactamente este formato:
{{
  "event_index": <número de la noticia, empezando en 1>,
  "direction": "up|down|neutral",
  "timeframe": "immediate|hours|hours to days|days|days to weeks|weeks",
  "confidence": <entero 25-95>,
  "signal_strength": "high|medium|low",
  "most_affected_assets": [<1-3 tickers>],
  "reasoning": "<UNA frase máx 150 chars EN ESPAÑOL>",
  "historical_learning": "<aprendizaje histórico o 'sin datos históricos'>",
  "verification_window_hours": <entero 1-24>
}}

Responde SOLO con el JSON array, sin explicaciones."""


def analyze_events_batch(events: List[dict]) -> List[Optional[dict]]:
    """
    Analiza múltiples eventos en una sola llamada a Claude (batching).
    Reduce el overhead del system prompt pagándolo solo 1 vez para N eventos.
    Returns a list of validated analyses (same order as input), None for failures.
    """
    if not events:
        return []

    if len(events) == 1:
        return [analyze_event_with_claude(events[0])]

    # Verificar disponibilidad
    if USE_BEDROCK:
        if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            return [None] * len(events)
    elif not ANTHROPIC_API_KEY:
        return [None] * len(events)

    # Construir bloque de eventos
    event_blocks = []
    for i, event in enumerate(events, 1):
        title = event.get("title", "")
        description = (event.get("description") or event.get("summary") or "")[:300]
        score = event.get("score", event.get("impact_score", 50))
        category = event.get("category", "")

        # RAG desactivado hasta tener historial limpio con >60% accuracy
        hist_line = ""

        # Contexto de precio reducido
        price_line = ""
        try:
            from src.services.real_price_fetcher import RealPriceFetcher
            asset = event.get("suggested_asset", "BTC")
            fetcher = RealPriceFetcher()
            ctx = fetcher.get_price_context(asset)
            if ctx and ctx.get("current", 0) > 0:
                recent = fetcher.get_recent_change(asset, hours=4)
                recent_str = f", cambio 4h: {recent:+.2f}%" if recent is not None else ""
                price_line = f"Precio {asset}: ${ctx['current']} | RSI: {ctx['rsi_14']} | 7d: {ctx['change_7d_pct']:+.1f}%{recent_str}"
        except Exception:
            pass

        block = (
            f"--- NOTICIA {i} ---\n"
            f"Título: {title}\n"
            f"Descripción: {description}\n"
            f"Categoría: {category} | Score: {score}/100\n"
        )
        if price_line:
            block += f"{price_line}\n"
        if hist_line:
            block += f"{hist_line}\n"

        event_blocks.append(block)

    events_block = "\n".join(event_blocks)
    prompt = BATCH_PROMPT_TEMPLATE.format(count=len(events), events_block=events_block)

    logger.info(f"📦 Batch analysis: {len(events)} eventos en una sola llamada")
    raw_text = _call_claude_raw(prompt, max_tokens=2048)

    results: List[Optional[dict]] = [None] * len(events)

    if raw_text is None:
        logger.warning("Batch analysis failed, falling back to individual calls")
        return [analyze_event_with_claude(e) for e in events]

    parsed = _parse_json_response_batch(raw_text)

    if parsed is None:
        logger.warning("Batch parse failed, falling back to individual calls")
        return [analyze_event_with_claude(e) for e in events]

    # Array of results
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            idx = item.get("event_index", 0) - 1
            if 0 <= idx < len(events):
                results[idx] = _validate_analysis(item)
        return results

    # Single dict returned
    if isinstance(parsed, dict):
        if "event_index" in parsed:
            idx = parsed.get("event_index", 1) - 1
            if 0 <= idx < len(events):
                results[idx] = _validate_analysis(parsed)
        else:
            results[0] = _validate_analysis(parsed)

    return results


def _parse_json_response_batch(text: str) -> list | dict | None:
    """Parses a JSON array or object from text."""
    if not text:
        return None
    # Try array first
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Fall back to single object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


class ClaudeAnalyzer:
    """Analizador de eventos usando Claude con RAG."""

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            logger.warning("ClaudeAnalyzer inicializado sin ANTHROPIC_API_KEY")

    def analyze(self, event: dict) -> Optional[dict]:
        """Analiza un evento y devuelve la predicción."""
        return analyze_event_with_claude(event)

    def analyze_batch(self, events: List[dict]) -> List[Optional[dict]]:
        """Analiza múltiples eventos en una sola llamada."""
        return analyze_events_batch(events)

    def is_available(self) -> bool:
        """Verifica si Claude está disponible (via Bedrock o API directa)."""
        if USE_BEDROCK:
            return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)
        return bool(ANTHROPIC_API_KEY)
