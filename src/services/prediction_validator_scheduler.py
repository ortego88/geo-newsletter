"""
Validador de predicciones con APScheduler.
Valida predicciones pendientes cada hora usando precios reales.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from src.services.prediction_tracker import PredictionTracker
from src.services.real_price_fetcher import RealPriceFetcher

logger = logging.getLogger("prediction_validator")


class PredictionValidatorScheduler:
    def __init__(
        self,
        tracker: PredictionTracker | None = None,
        price_fetcher: RealPriceFetcher | None = None,
        interval_minutes: int = 60,
    ):
        self.tracker = tracker or PredictionTracker()
        self.price_fetcher = price_fetcher or RealPriceFetcher()
        self.interval_minutes = interval_minutes
        self._scheduler = BackgroundScheduler()

    def validate_pending_predictions(self):
        """
        Obtiene todas las predicciones pendientes y valida aquellas
        cuyo plazo (timeframe_minutes) ya ha transcurrido desde predicted_at.
        """
        pending = self.tracker.get_pending_predictions()
        if not pending:
            logger.info("Sin predicciones pendientes de validar.")
            return

        logger.info(f"Validando {len(pending)} predicciones pendientes...")
        now = datetime.utcnow()
        validated_count = 0

        for pred in pending:
            prediction_id = pred.get("id")
            predicted_at_str = pred.get("predicted_at", "")
            timeframe_minutes = pred.get("timeframe_minutes", 480)
            asset = pred.get("asset", "UNKNOWN")

            try:
                predicted_at = datetime.fromisoformat(predicted_at_str)
            except (ValueError, TypeError):
                logger.warning(f"Fecha inválida en predicción #{prediction_id}: {predicted_at_str}")
                continue

            elapsed_minutes = (now - predicted_at).total_seconds() / 60

            if elapsed_minutes < timeframe_minutes:
                logger.debug(
                    f"Predicción #{prediction_id} ({asset}): "
                    f"{elapsed_minutes:.0f}/{timeframe_minutes} min transcurridos — aún no"
                )
                continue

            # Ya pasó el plazo → validar con precio actual
            current_price = self.price_fetcher.get_price(asset)
            if current_price is None:
                logger.warning(f"No se pudo obtener precio para {asset}, usando fallback 100.0")
                current_price = 100.0

            result = self.tracker.validate_prediction(prediction_id, current_price)
            if result:
                validated_count += 1
                outcome_es = "✅ CORRECTA" if result["outcome"] == "correct" else "❌ INCORRECTA"
                logger.info(
                    f"Predicción #{prediction_id} validada: {outcome_es} | "
                    f"{asset} cambio real: {result['actual_change']:+.2f}% | "
                    f"predicho: {result['predicted_change']:+.1f}%"
                )

        if validated_count:
            stats = self.tracker.get_accuracy_stats()
            logger.info(
                f"Validación completa: {validated_count} validadas | "
                f"Precisión acumulada: {stats['accuracy_pct']}% "
                f"({stats['correct']}/{stats['total']})"
            )

    def start(self):
        """Inicia el scheduler de validación."""
        self._scheduler.add_job(
            self.validate_pending_predictions,
            "interval",
            minutes=self.interval_minutes,
            id="validate_predictions",
            next_run_time=datetime.now(),  # Ejecutar inmediatamente al inicio
        )
        self._scheduler.start()
        logger.info(
            f"Validador de predicciones iniciado (cada {self.interval_minutes} minutos)"
        )

    def stop(self):
        """Detiene el scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Validador de predicciones detenido.")
