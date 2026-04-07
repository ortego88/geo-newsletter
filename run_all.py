"""
run_all.py — Punto de entrada para producción en Railway.
Lanza el scheduler en un thread y Flask dashboard en el proceso principal.

Variables de entorno requeridas:
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

# Crear directorio data si no existe (Railway tiene filesystem efímero)
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

if not os.path.exists("data/app.db"):
    logger.warning(
        "⚠️  AVISO: data/app.db no existe. Si estás en Railway, configura un Persistent Volume "
        "en /app/data para no perder usuarios entre deploys. Ver PERSISTENT_STORAGE.md para instrucciones."
    )

from apscheduler.schedulers.background import BackgroundScheduler
from src.services.pipeline_v2 import AnalysisPipeline
from src.services.prediction_tracker import PredictionTracker
from src.services.prediction_validator_scheduler import PredictionValidatorScheduler
from web.app import create_app

flask_app = create_app()

DB_PATH = "data/predictions.db"

pipeline = AnalysisPipeline(db_path=DB_PATH)
tracker = PredictionTracker(db_path=DB_PATH)
validator = PredictionValidatorScheduler(tracker=tracker, interval_minutes=60)


def _send_pipeline_alerts(events: list):
    """
    Envía alertas individuales de Telegram para cada evento relevante del ciclo.
    - Resuelve conflictos de dirección antes de alertar.
    - Solo envía alertas para activos suscritos (TELEGRAM_ALERT_ASSETS).
    - Una alerta por evento (sin resumen/digest).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN no configurado — alertas desactivadas")
        return

    try:
        from src.services.telegram_sender import send_telegram, get_subscribed_assets
        from src.services.alert_formatter import format_telegram_alert
        from src.services.signal_resolver import resolve_signals
    except Exception as e:
        logger.error(f"Error importando módulos de alerta: {e}")
        return

    # Step 1: filter alertable events (score >= 60 with analysis)
    alertable = [
        e for e in events
        if e.get("score", 0) >= 60 and e.get("analysis")
    ]

    if not alertable:
        logger.info("Sin eventos con score >= 60 para alertar")
        return

    # Step 2: resolve conflicting signals for same asset
    resolved = resolve_signals(alertable)
    logger.info(f"📊 Señales resueltas: {len(alertable)} → {len(resolved)} eventos")

    # Step 3: filter by subscribed assets
    subscribed = get_subscribed_assets()
    if subscribed:
        filtered = []
        for event in resolved:
            analysis = event.get("analysis", {})
            assets = {a.upper() for a in analysis.get("most_affected_assets", [])}
            if assets & subscribed:  # include event if ANY of its affected assets matches the subscription list
                filtered.append(event)
        if not filtered:
            logger.info(f"Sin eventos para activos suscritos: {subscribed}")
            return
        resolved = filtered
        logger.info(f"📌 Filtrado por suscripción ({subscribed}): {len(resolved)} eventos")

    # Step 4: send one alert per event (no summary)
    logger.info(f"📨 Enviando {len(resolved)} alertas individuales a Telegram...")
    sent = 0
    for event in resolved:
        msg = format_telegram_alert(event, event["analysis"])
        if send_telegram(msg):
            sent += 1
            conflict_tag = " [conflicto resuelto]" if event.get("_conflict_resolved") else ""
            logger.info(f"✅ Alerta enviada{conflict_tag}: {event.get('title','')[:60]}")

    logger.info(f"📤 Total enviadas: {sent}/{len(resolved)}")

    # Enviar también por WhatsApp si está configurado
    try:
        from src.services.whatsapp_sender import send_whatsapp, is_whatsapp_configured
        if is_whatsapp_configured():
            for event in resolved:
                msg = format_telegram_alert(event, event["analysis"])
                send_whatsapp(msg)
    except Exception as e:
        logger.warning(f"Error en envío WhatsApp: {e}")


def run_pipeline_cycle():
    logger.info("=" * 60)
    logger.info(f"⏱️  CICLO DE PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    try:
        events = pipeline.run(minutes=360, min_score=30)
        if not events:
            logger.info("Sin eventos relevantes en este ciclo.")
            return
        logger.info(f"✅ {len(events)} eventos relevantes encontrados")
        stats = tracker.get_accuracy_stats()
        logger.info(
            f"📊 Precisión: {stats['accuracy_pct']}% ({stats['correct']}/{stats['total']} correctas)"
        )

        # Send Telegram alerts
        _send_pipeline_alerts(events)

    except Exception as e:
        logger.error(f"Error en ciclo de pipeline: {e}", exc_info=True)


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
    scheduler.start()
    logger.info("✅ Scheduler iniciado (pipeline cada 10 minutos, resumen semanal domingos 10:00 AM)")
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
    logger.info("  🌍 GEO-NEWSLETTER — PRODUCCIÓN (Railway)")
    logger.info("=" * 60)
    logger.info(f"  Dashboard: http://0.0.0.0:{port}")
    logger.info(f"  OpenAI: {'✅ configurado' if os.getenv('OPENAI_API_KEY') else '⚠️  NO configurado (usando Ollama)'}")
    logger.info("=" * 60)

    # Iniciar scheduler en background thread
    scheduler = start_scheduler()

    # Iniciar Flask en el thread principal (Railway necesita que el proceso principal escuche en PORT)
    start_dashboard(port)
