"""
run_all.py — Punto de entrada para producción en Railway.
Lanza el scheduler en un thread y Flask dashboard en el proceso principal.

Variables de entorno requeridas:
  DATABASE_URL    — conexión PostgreSQL (obligatorio en todos los entornos)
  OPENAI_API_KEY  — clave de OpenAI
  PORT            — puerto para el dashboard (Railway lo asigna automáticamente)
  DASHBOARD_PORT  — alternativa, por defecto 8080
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime

# Crear directorio data si no existe (para logs y caché de deduplicación)
os.makedirs("data", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Configurar logging con salida a stdout Y a fichero
file_handler = logging.FileHandler("data/scheduler.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), file_handler],
)
logger = logging.getLogger("run_all")

# Comprobar configuración de BD — DATABASE_URL es obligatorio
_db_url = os.getenv("DATABASE_URL", "").strip()
if not _db_url:
    logger.error(
        "❌ FATAL: DATABASE_URL no configurada. "
        "PostgreSQL es obligatorio en todos los entornos. "
        "Configura DATABASE_URL=postgresql://user:password@host:5432/dbname"
    )
    sys.exit(1)
logger.info("✅ DATABASE_URL detectada — usando PostgreSQL (datos persistentes entre deploys)")

from apscheduler.schedulers.background import BackgroundScheduler
from src.services.pipeline_v2 import AnalysisPipeline
from src.services.prediction_tracker import PredictionTracker
from src.services.prediction_validator_scheduler import PredictionValidatorScheduler
from web.app import create_app

flask_app = create_app()

DB_PATH = "data/predictions.db"

pipeline = AnalysisPipeline(db_path=DB_PATH)
tracker = PredictionTracker(db_path=DB_PATH)
validator = PredictionValidatorScheduler(tracker=tracker, interval_minutes=5)


def _get_event_assets(event: dict) -> set:
    """Returns the set of uppercase asset symbols for a pipeline event."""
    return {a.upper() for a in event.get("analysis", {}).get("most_affected_assets", [])}


def _send_per_user_alerts(events: list, format_fn, send_fn) -> int:
    """
    Envía alertas de Telegram personalizadas a cada usuario activo que tenga
    configurado su telegram_chat_id y cuyos activos suscritos coincidan con
    alguno de los eventos. Registra cada envío exitoso en alert_log.
    
    ✅ Las alertas se envían 24/7 sin restricción de horarios.
    Los horarios de mercado solo afectan a la verificación posterior de predicciones.
    """
    try:
        from sqlalchemy import text as _text
        from web.db_engine import get_engine as _get_engine
        from web.models import PLANS
    except Exception as e:
        logger.error(f"Error importando dependencias para alertas per-usuario: {e}")
        return

    try:
        with _get_engine("app").connect() as conn:
            rows = conn.execute(_text("""
                SELECT u.id, u.telegram_chat_id, s.plan, s.status, s.selected_assets, u.language
                FROM users u
                JOIN subscriptions s ON s.user_id = u.id
                WHERE u.telegram_chat_id IS NOT NULL
                  AND u.telegram_chat_id != ''
                  AND u.is_active = 1
                  AND s.status IN ('active', 'trial')
                ORDER BY u.id
            """)).fetchall()
    except Exception as e:
        logger.warning(f"No se pudo consultar usuarios para alertas: {e}")
        return

    if not rows:
        logger.info("Sin usuarios con Telegram configurado para alertas per-usuario")
        return

    now_iso = datetime.utcnow().isoformat()

    user_sent = 0
    for row in rows:
        user_id, chat_id, plan, status, selected_assets_raw, user_language = row
        user_language = user_language or "es"
        selected = {a.strip().upper() for a in (selected_assets_raw or "").split(",") if a.strip()}
        if not selected:
            continue

        plan_cfg = PLANS.get(plan, PLANS["basic"])
        max_daily = plan_cfg.get("max_daily_alerts", 5)

        # Check daily alert count for this user
        if max_daily != -1:
            try:
                day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                with _get_engine("app").connect() as conn:
                    daily_count = conn.execute(_text(
                        "SELECT COUNT(*) FROM alert_log WHERE user_id=:uid AND sent_at >= :day_start"
                    ), {"uid": user_id, "day_start": day_start}).fetchone()[0]
            except Exception:
                daily_count = 0
        else:
            daily_count = 0

        for event in events:
            if max_daily != -1 and daily_count >= max_daily:
                break

            event_assets = _get_event_assets(event)
            if not (event_assets & selected):
                continue

            msg = format_fn(event, event["analysis"], language=user_language)
            if send_fn(msg, chat_id=chat_id):
                user_sent += 1
                daily_count += 1
                asset_sent = next(iter(event_assets & selected), "")
                direction = event.get("analysis", {}).get("direction", "")
                score = int(event.get("score", 0))
                try:
                    with _get_engine("app").connect() as conn:
                        conn.execute(_text(
                            "INSERT INTO alert_log (user_id, asset, direction, score, sent_at) "
                            "VALUES (:uid, :asset, :dir, :score, :sent_at)"
                        ), {"uid": user_id, "asset": asset_sent, "dir": direction,
                            "score": score, "sent_at": now_iso})
                        conn.commit()
                except Exception as log_err:
                    logger.warning(f"No se pudo registrar en alert_log (user {user_id}): {log_err}")

    logger.info(f"📬 Alertas per-usuario enviadas: {user_sent} (a {len(rows)} usuarios con Telegram)")
    return user_sent


def _send_pipeline_alerts(events: list):
    """
    Envía alertas individuales de Telegram para cada evento relevante del ciclo.
    - Envía al canal global (TELEGRAM_CHAT_ID) si está configurado.
    - Envía también a cada usuario con telegram_chat_id y activos suscritos coincidentes.
    - Registra cada envío en la tabla alert_log.
    - Los conflictos de señal ya fueron resueltos por pipeline.run() (Paso 7).
    
    ✅ IMPORTANTE: Las alertas se envían 24/7 sin restricción de horarios.
    No se usa is_market_open() aquí. Solo se filtra por score >= 60.
    Los horarios de mercado solo afectan a la verificación posterior de predicciones
    en PredictionValidatorScheduler.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN no configurado — alertas desactivadas")
        return

    try:
        from src.services.telegram_sender import send_telegram, get_subscribed_assets
        from src.services.alert_formatter import format_telegram_alert
    except Exception as e:
        logger.error(f"Error importando módulos de alerta: {e}")
        return

    # Step 1: filter alertable events (score >= 60, confidence >= 70)
    resolved = [
        e for e in events
        if e.get("score", 0) >= 60
        and e.get("analysis")
        and e.get("analysis", {}).get("confidence", 0) >= 70
    ]

    if not resolved:
        logger.info("Sin eventos con score >= 60 y confidence >= 70 para alertar")
        return

    # Only send alerts for events that were saved in the predictions DB.
    saved_predictions = [e for e in resolved if e.get("prediction_id")]
    if not saved_predictions:
        logger.info("Ninguna predicción guardada en DB para alertar")
        return

    # Step 1b: Apply historical accuracy filter
    try:
        from src.services.prediction_filter import should_send_alert
        filtered = []
        for event in saved_predictions:
            should_send, reason = should_send_alert(event)
            if should_send:
                filtered.append(event)
            else:
                logger.info(f"   🚫 Filtrada por histórico: {reason} | {event.get('title', '')[:50]}")
        if len(filtered) < len(saved_predictions):
            logger.info(f"📊 Filtro histórico: {len(saved_predictions)}→{len(filtered)} alertas")
        saved_predictions = filtered
    except Exception as e:
        logger.warning(f"Error en filtro histórico (enviando todas): {e}")

    if not saved_predictions:
        logger.info("Todas las alertas filtradas por histórico de accuracy")
        return

    logger.info(f"📊 {len(saved_predictions)} eventos listos para alertar")

    # Step 2: send per-user alerts based on telegram_chat_id + selected_assets
    # (the public channel only gets 1 BTC alert/day via send_daily_channel_alert + daily summary)
    alerted_prediction_ids = set()
    user_sent = _send_per_user_alerts(saved_predictions, format_telegram_alert, send_telegram)
    for event in saved_predictions:
        alerted_prediction_ids.add(event.get("prediction_id"))

    # Step 2b: send FCM push notifications to plan topics
    try:
        from src.services.firebase_push import send_alert_to_topics
        for event in saved_predictions:
            send_alert_to_topics(event, event.get("analysis", {}))
    except Exception as e:
        logger.debug(f"FCM push skipped: {e}")

    # Step 3: mark sent predictions as alerted (for historical filter accuracy)
    for pid in alerted_prediction_ids:
        if pid:
            tracker.mark_as_alerted(pid)

    logger.info(f"📤 Total alertas per-usuario enviadas en este ciclo: {user_sent}")


def run_pipeline_cycle():
    logger.info("=" * 60)
    logger.info(f"⏱️  CICLO DE PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    try:
        events = pipeline.run(minutes=180, min_score=45)
        if not events:
            events = []
            logger.info("Sin eventos de noticias en este ciclo.")

        # Check for price-based signals (large movements) — these are injected
        # back into the pipeline as synthetic articles for Claude to analyze
        try:
            from src.services.price_signals import check_price_signals
            price_events = check_price_signals()
            if price_events:
                from src.services.claude_analyzer import analyze_events_batch
                from src.services.real_price_fetcher import get_price
                logger.info(f"📊 {len(price_events)} señales de precio → analizando con Claude...")
                batch_results = analyze_events_batch(price_events)
                for pe, analysis in zip(price_events, batch_results):
                    if analysis is None or analysis.get("confidence", 0) < 70:
                        continue
                    pe["analysis"] = analysis
                    assets = analysis.get("most_affected_assets", [])
                    asset = assets[0] if assets else pe.get("suggested_asset", "")
                    price_now = get_price(asset) or 0.0
                    if price_now <= 0:
                        continue
                    pred_id = tracker.save_prediction(pe, price_now)
                    if pred_id:
                        pe["prediction_id"] = pred_id
                        events.append(pe)
                logger.info(f"📊 {sum(1 for e in price_events if e.get('prediction_id'))} señales de precio guardadas tras análisis Claude")
        except Exception as e:
            logger.warning(f"Error en price_signals: {e}")

        if not events:
            return
        logger.info(f"✅ {len(events)} eventos relevantes encontrados")
        stats = tracker.get_accuracy_stats()
        logger.info(
            f"📊 Precisión: {stats['accuracy_pct']}% ({stats['correct']}/{stats['total']} correctas)"
        )

        # Send Telegram alerts
        _send_pipeline_alerts(events)

        # Send first BTC alert of the day to channel (immediate, max 1/day)
        try:
            from src.services.channel_alert import send_daily_channel_alert
            send_daily_channel_alert(events)
        except Exception as e:
            logger.warning(f"Error en alerta de canal: {e}")

    except Exception as e:
        logger.error(f"Error en ciclo de pipeline: {e}", exc_info=True)
    finally:
        try:
            from src.services.claude_analyzer import get_daily_token_usage
            usage = get_daily_token_usage()
            if usage["calls"] > 0:
                logger.info(
                    f"💰 Tokens hoy ({usage['date']}): "
                    f"input={usage['input_tokens']:,} output={usage['output_tokens']:,} "
                    f"calls={usage['calls']}"
                )
        except Exception:
            pass


def start_scheduler():
    validator.start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_pipeline_cycle,
        "interval",
        minutes=10,
        id="pipeline_cycle",
        next_run_time=datetime.now(),
    )
    # Weekly digest: every Sunday at 10:00 AM (Madrid time) for Premium/Pro users
    from src.services.weekly_digest import send_weekly_digest
    scheduler.add_job(
        lambda: send_weekly_digest(DB_PATH, os.getenv("APP_DB_PATH", "data/app.db")),
        "cron",
        day_of_week="sun",
        hour=10,
        minute=0,
        timezone="Europe/Madrid",
        id="weekly_digest",
    )
    # Newsletter: every Sunday at 11:00 AM (Madrid time) for all subscribers
    from src.services.newsletter_sender import send_weekly_newsletter
    scheduler.add_job(
        send_weekly_newsletter,
        "cron",
        day_of_week="sun",
        hour=11,
        minute=0,
        timezone="Europe/Madrid",
        id="weekly_newsletter",
    )
    # Daily blog post: every day at 9:00 AM (Madrid time)
    def publish_daily_blog_post():
        try:
            import subprocess
            result = subprocess.run(
                ["python3", "create_daily_blog_post.py"],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                logger.info("✅ Artículo de blog publicado correctamente")
            else:
                logger.warning(f"⚠️ Error publicando artículo: {result.stderr}")
        except Exception as e:
            logger.error(f"❌ Error en job de blog diario: {e}")

    scheduler.add_job(
        publish_daily_blog_post,
        "cron",
        hour=9,
        minute=0,
        timezone="Europe/Madrid",
        id="daily_blog_post",
    )
    # Daily channel summary: 10:00 Madrid — yesterday's prediction results
    def send_channel_summary():
        try:
            from src.services.channel_alert import send_daily_summary
            send_daily_summary()
        except Exception as e:
            logger.warning(f"Error enviando resumen diario al canal: {e}")

    scheduler.add_job(
        send_channel_summary,
        "cron",
        hour=10,
        minute=0,
        timezone="Europe/Madrid",
        id="daily_channel_summary",
    )
    # Channel membership sync: every hour, kick expired subscribers
    def sync_channel():
        try:
            from src.services.channel_members import sync_channel_members
            sync_channel_members()
        except Exception as e:
            logger.warning(f"Error en sync de canal: {e}")

    scheduler.add_job(
        sync_channel,
        "interval",
        hours=1,
        id="channel_sync",
    )
    scheduler.start()
    logger.info("✅ Scheduler iniciado (pipeline cada 10 min, canal sync cada 1h, blog diario 9:00 AM)")
    logger.info("✅ Alertas: canal (1ª BTC del día) + resumen 10:00 + bot individual (personalizadas)")
    logger.info("✅ Verificación: respeta horarios de mercado (Crypto 24/7)")
    return scheduler


def start_dashboard(port: int):
    """Inicia el servidor Flask del dashboard."""
    try:
        debug_mode = os.getenv("FLASK_ENV", "production") == "development" or os.getenv("DEBUG", "").lower() in ("1", "true")
        logger.info(f"🌐 Dashboard iniciando en puerto {port}{'  [modo desarrollo — hot-reload activo]' if debug_mode else ''}...")
        flask_app.run(host="0.0.0.0", port=port, debug=debug_mode, threaded=True, use_reloader=debug_mode)
    except Exception as e:
        logger.error(f"Error iniciando dashboard: {e}", exc_info=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))

    logger.info("=" * 60)
    logger.info("  🌍 Trianio — PRODUCCIÓN (Railway)")
    logger.info("=" * 60)
    logger.info(f"  Dashboard: http://0.0.0.0:{port}")
    logger.info(f"  OpenAI: {'✅ configurado' if os.getenv('OPENAI_API_KEY') else '⚠️  NO configurado (usando Ollama)'}")
    logger.info("=" * 60)

    # Iniciar scheduler en background thread
    scheduler = start_scheduler()

    # Iniciar Flask en el thread principal (Railway necesita que el proceso principal escuche en PORT)
    start_dashboard(port)
