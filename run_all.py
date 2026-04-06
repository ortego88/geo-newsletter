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

# Configurar logging PRIMERO
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_all")

from apscheduler.schedulers.background import BackgroundScheduler
from src.services.pipeline_v2 import AnalysisPipeline
from src.services.prediction_tracker import PredictionTracker
from src.services.prediction_validator_scheduler import PredictionValidatorScheduler

# Crear directorio data si no existe (Railway tiene filesystem efímero)
os.makedirs("data", exist_ok=True)
os.makedirs("templates", exist_ok=True)

DB_PATH = "data/predictions.db"

pipeline = AnalysisPipeline(db_path=DB_PATH)
tracker = PredictionTracker(db_path=DB_PATH)
validator = PredictionValidatorScheduler(tracker=tracker, interval_minutes=60)


def _send_pipeline_alerts(events: list):
    """Envía alertas de Telegram para los eventos relevantes del ciclo."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN no configurado — alertas desactivadas")
        return

    try:
        from src.services.telegram_sender import send_telegram
        from src.services.alert_formatter import format_telegram_alert, format_cycle_summary
    except Exception as e:
        logger.error(f"Error importando módulos de alerta: {e}")
        return

    # Filter events with score >= 60 and with analysis
    alertable = [
        e for e in events
        if e.get("score", 0) >= 60 and e.get("analysis")
    ]

    if not alertable:
        logger.info("Sin eventos con score >= 60 para alertar")
        return

    logger.info(f"📨 Enviando {len(alertable)} alertas a Telegram...")

    if len(alertable) == 1:
        event = alertable[0]
        msg = format_telegram_alert(event, event["analysis"])
        send_telegram(msg)
        logger.info(f"✅ Alerta enviada: {event['title'][:60]}")
    else:
        summary = format_cycle_summary(alertable[:5])
        send_telegram(summary)
        logger.info(f"✅ Resumen enviado ({len(alertable)} eventos)")

        top = alertable[0]
        detail = format_telegram_alert(top, top["analysis"])
        send_telegram(detail)
        logger.info(f"✅ Detalle enviado: {top['title'][:60]}")


def run_pipeline_cycle():
    logger.info("=" * 60)
    logger.info(f"⏱️  CICLO DE PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    try:
        events = pipeline.run(minutes=120, min_score=30)
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
    scheduler.start()
    logger.info("✅ Scheduler iniciado (pipeline cada 10 minutos)")
    return scheduler


def start_dashboard(port: int):
    """Inicia el servidor Flask del dashboard."""
    try:
        from dashboard import app
        logger.info(f"🌐 Dashboard iniciando en puerto {port}...")
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
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
