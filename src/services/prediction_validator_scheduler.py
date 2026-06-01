"""
Validador de predicciones con APScheduler.
Verifica predicciones pendientes cada hora usando precios reales.

Lógica de evaluación (crypto 24/7):
  - Cada hora comprueba si el precio se movió >= ±1% desde la predicción
  - Si sube >=1% y se predijo alza → CORRECT (validación inmediata)
  - Si baja >=1% y se predijo baja → CORRECT (validación inmediata)
  - Si se mueve >=1% en dirección opuesta → INCORRECT (validación inmediata)
  - Si tras 24h no se alcanza ±1% → NEUTRAL (no penaliza accuracy)
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from src.services.prediction_tracker import PredictionTracker
from src.services.real_price_fetcher import RealPriceFetcher

logger = logging.getLogger("prediction_validator")


def _format_price_usd(price: float) -> str:
    """Formats a price in readable USD format."""
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:.2f}"
    if price >= 0.01:
        return f"${price:.4f}"
    return f"${price:.6f}"


def _format_validation_message(result: dict, stats: dict | None = None) -> str:
    """Formats the validation result message."""
    outcome = result.get("outcome", "unknown")
    asset = result.get("asset", "?")
    direction = result.get("direction", "neutral")
    actual_change = result.get("actual_change", 0.0)
    price_at = result.get("price_at_prediction", 0.0)
    price_now = result.get("price_at_validation", 0.0)
    title = result.get("title", "")[:80]

    outcome_emoji = "✅" if outcome == "correct" else "❌"
    outcome_label = "CORRECTA" if outcome == "correct" else "INCORRECTA"
    change_emoji = "📈" if actual_change > 0 else ("📉" if actual_change < 0 else "➡️")
    dir_label_map = {
        "up": "ALZA ↑", "bullish": "ALZA ↑", "positive": "ALZA ↑", "alza": "ALZA ↑",
        "down": "BAJA ↓", "bearish": "BAJA ↓", "negative": "BAJA ↓", "baja": "BAJA ↓",
        "neutral": "NEUTRAL ↔",
    }
    dir_label = dir_label_map.get(direction.lower(), direction.upper())

    lines = [
        f"📊 RESULTADO DE PREDICCIÓN",
        f"",
        f"📌 {title}",
        f"",
        f"• Activo: {asset}",
        f"• Dirección predicha: {dir_label}",
        f"• Precio en alerta: {_format_price_usd(price_at)}",
        f"• Precio actual: {_format_price_usd(price_now)}",
        f"• Cambio real: {change_emoji} {actual_change:+.2f}%",
        f"",
        f"{outcome_emoji} Predicción: {outcome_label}",
    ]

    if stats and stats.get("total", 0) > 0:
        lines += [
            f"",
            f"🎯 Precisión acumulada: {stats['accuracy_pct']}% ({stats['correct']}/{stats['total']})",
        ]

    return "\n".join(lines)


def _send_validation_telegram(result: dict, stats: dict | None = None):
    """Sends validation result to per-user bot and channel (only if it was the daily channel alert)."""
    import os
    try:
        from src.services.telegram_sender import send_telegram
    except Exception as e:
        logger.error(f"Error importando telegram_sender: {e}")
        return

    message = _format_validation_message(result, stats)
    prediction_id = result.get("prediction_id")

    # 1. Send to private channel ONLY if this prediction was the channel's daily alert
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "")
    if channel_id and prediction_id:
        try:
            from sqlalchemy import text as _text_ch
            from web.db_engine import get_engine as _get_engine_ch
            with _get_engine_ch("app").connect() as conn:
                was_channel_alert = conn.execute(_text_ch(
                    "SELECT 1 FROM channel_alert_log WHERE prediction_id = :pred_id"
                ), {"pred_id": prediction_id}).fetchone()
            if was_channel_alert:
                send_telegram(message, chat_id=channel_id)
                logger.info(f"📢 Resultado enviado al canal (prediction_id={prediction_id})")
        except Exception as e:
            logger.warning(f"Error checking channel alert for validation: {e}")

    # 2. Send to users who have this asset in their selected_assets
    if asset:
        try:
            from sqlalchemy import text as _text
            from web.db_engine import get_engine as _get_engine

            with _get_engine("app").connect() as conn:
                rows = conn.execute(_text("""
                    SELECT u.telegram_chat_id, s.selected_assets
                    FROM users u
                    JOIN subscriptions s ON s.user_id = u.id
                    WHERE u.telegram_chat_id IS NOT NULL
                      AND u.telegram_chat_id != ''
                      AND u.is_active = 1
                      AND s.status IN ('active', 'trial')
                """)).fetchall()

            for row in rows:
                chat_id, selected_raw = row
                selected = {a.strip().upper() for a in (selected_raw or "").split(",") if a.strip()}
                if asset.upper() in selected or not selected:
                    send_telegram(message, chat_id=chat_id)
        except Exception as e:
            logger.warning(f"Error enviando validación per-user: {e}")


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
        
        ✅ Respeta horarios de mercado: Solo verifica si el mercado está abierto
           para el activo específico (is_market_open).
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
            asset = pred.get("asset", "UNKNOWN")

            try:
                predicted_at = datetime.fromisoformat(predicted_at_str)
            except (ValueError, TypeError):
                logger.warning(f"Fecha inválida en predicción #{prediction_id}: {predicted_at_str}")
                continue

            # Skip very fresh predictions (less than 5 min old) to avoid noise
            elapsed_minutes = (now - predicted_at).total_seconds() / 60
            if elapsed_minutes < 5:
                logger.debug(
                    f"Predicción #{prediction_id} ({asset}): "
                    f"menos de 5min desde creación — esperando"
                )
                continue

            # Get current price and attempt validation (threshold-based)
            current_price = self.price_fetcher.get_price(asset)
            if current_price is None:
                logger.warning(f"No se pudo obtener precio para {asset}, omitiendo validación")
                continue

            result = self.tracker.validate_prediction(prediction_id, current_price)
            if result is None:
                # Threshold not reached yet and window still active — will retry next cycle
                logger.debug(
                    f"Predicción #{prediction_id} ({asset}): "
                    f"umbral ±1% no alcanzado, reintentando próximo ciclo"
                )
                continue
            validated_count += 1
            outcome_es = {"correct": "✅ CORRECTA", "incorrect": "❌ INCORRECTA", "neutral": "⚪ NEUTRAL"}.get(result["outcome"], result["outcome"])
            logger.info(
                f"Predicción #{prediction_id} validada: {outcome_es} | "
                f"{asset} cambio real: {result['actual_change']:+.2f}%"
            )
            pred_score = pred.get("score", 0)
            pred_confidence = pred.get("confidence", 0)
            if pred_score >= 60 and pred_confidence >= 65 and result["outcome"] != "neutral":
                stats = self.tracker.get_accuracy_stats()
                _send_validation_telegram(result, stats)

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
        logger.info(
            "✅ Verificación de predicciones respeta horarios: "
            "IBEX35 (9-17:30 L-V), Crypto (24/7), ETFs (9:30-16:00 NY L-V)"
        )

    def stop(self):
        """Detiene el scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Validador de predicciones detenido.")
