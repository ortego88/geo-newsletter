"""
run_scheduler.py — Punto de entrada principal para producción.

Ejecuta el pipeline de análisis cada 10 minutos y valida predicciones cada hora.
Incluye un servidor Flask mínimo para el health-check de Railway en $PORT.

Uso:
    python run_scheduler.py
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify

from src.services.pipeline_v2 import AnalysisPipeline
from src.services.prediction_tracker import PredictionTracker
from src.services.prediction_validator_scheduler import PredictionValidatorScheduler
from src.services.alert_formatter import format_alert
from src.services.telegram_sender import send_telegram

# Telegram's maximum message length
TELEGRAM_MAX_MESSAGE_LENGTH = 4096

# --- Configuración de logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/scheduler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("scheduler")

# --- Flask health-check server ---
health_app = Flask(__name__)


@health_app.route("/health")
@health_app.route("/")
def health():
    return jsonify({"status": "ok"}), 200


def _start_health_server():
    port = int(os.getenv("PORT", 8080))
    health_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# --- Instancias globales ---
pipeline = AnalysisPipeline(db_path="data/predictions.db")
tracker = PredictionTracker(db_path="data/predictions.db")
validator = PredictionValidatorScheduler(
    tracker=tracker,
    interval_minutes=60,
)


def run_pipeline_cycle():
    """Ejecuta un ciclo del pipeline y guarda predicciones."""
    logger.info("=" * 60)
    logger.info(f"⏱️  CICLO DE PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        events = pipeline.run(minutes=120, min_score=30)
        if not events:
            logger.info("Sin eventos relevantes en este ciclo.")
            return

        logger.info(f"\n✅ {len(events)} eventos relevantes encontrados\n")

        for event in events[:5]:
            analysis = event.get("analysis", {})
            alert_text = format_alert(event, analysis)
            print(alert_text)
            print()
            # Enviar alerta a Telegram (truncar a 4096 caracteres)
            send_telegram(alert_text[:TELEGRAM_MAX_MESSAGE_LENGTH])

        stats = tracker.get_accuracy_stats()
        logger.info(
            f"📊 Estadísticas de predicciones: "
            f"{stats['total']} total | "
            f"Precisión: {stats['accuracy_pct']}% "
            f"({stats['correct']}/{stats['total']} correctas)"
        )

    except Exception as e:
        logger.error(f"Error en ciclo de pipeline: {e}", exc_info=True)


def print_banner():
    print("=" * 72)
    print("  🌍 GEO-NEWSLETTER — SISTEMA DE ALERTAS GEOPOLÍTICAS EN TIEMPO REAL")
    print("=" * 72)
    print()
    print("  📅 Iniciado:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    print("  ⏱️  Programación:")
    print("       • Pipeline de análisis:    cada 10 minutos")
    print("       • Validación predicciones: cada 60 minutos")
    print()
    print("  💾 Base de datos: data/predictions.db")
    print("  📝 Log:           data/scheduler.log")
    print()
    print("  Presiona Ctrl+C para detener.")
    print("=" * 72)
    print()


def main():
    print_banner()

    # Iniciar servidor de health-check en hilo daemon
    health_thread = threading.Thread(target=_start_health_server, daemon=True, name="health-server")
    health_thread.start()

    # Iniciar el validador de predicciones (tiene su propio scheduler interno)
    validator.start()

    # Crear scheduler para el pipeline
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_pipeline_cycle,
        "interval",
        minutes=10,
        id="pipeline_cycle",
        next_run_time=datetime.now(),  # Ejecutar inmediatamente al inicio
    )
    scheduler.start()
    logger.info("Scheduler principal iniciado (pipeline cada 10 minutos)")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("\n🛑 Deteniendo schedulers...")
        scheduler.shutdown(wait=False)
        validator.stop()
        logger.info("✅ Sistema detenido correctamente.")
        sys.exit(0)


if __name__ == "__main__":
    main()
