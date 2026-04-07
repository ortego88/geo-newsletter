"""
Rastreador de predicciones.
Guarda predicciones en SQLite/PostgreSQL y las valida comparando precios.
"""

import logging
import os
from datetime import datetime

from sqlalchemy import text

from web.db_engine import get_engine
from src.services.market_config import calculate_verification_time

logger = logging.getLogger("prediction_tracker")

# Minimum price movement (in %) to consider a directional prediction valid.
# Predictions are only "correct" if the price moves at least this much in the predicted direction.
_MIN_SIGNIFICANT_MOVE = 0.15

# Known columns in the predictions table (used to build result dicts)
_PREDICTION_COLUMNS = [
    "id", "event_id", "title", "category", "asset", "direction", "impact_percent",
    "timeframe", "timeframe_minutes", "confidence", "reasoning", "price_at_prediction",
    "price_at_validation", "predicted_at", "validated_at", "outcome", "score", "source",
    "verify_at",
]


class PredictionTracker:
    def __init__(self, db_path: str = "data/predictions.db"):
        self.db_path = db_path
        # db_path is kept for backward compatibility; actual connection uses SQLAlchemy engine
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return get_engine("predictions").connect()

    def _init_db(self):
        from sqlalchemy import (
            MetaData, Table, Column, Integer, String, Text, Float, BigInteger,
        )
        engine = get_engine("predictions")
        meta = MetaData()
        Table("predictions", meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("event_id", Text, unique=True),
            Column("title", Text),
            Column("category", Text),
            Column("asset", Text),
            Column("direction", Text),
            Column("impact_percent", Float),
            Column("timeframe", Text),
            Column("timeframe_minutes", Integer),
            Column("confidence", Float),
            Column("reasoning", Text),
            Column("price_at_prediction", Float),
            Column("price_at_validation", Float),
            Column("predicted_at", Text),
            Column("validated_at", Text),
            Column("outcome", Text),
            Column("score", Float),
            Column("source", Text),
            Column("verify_at", Text),  # cuándo verificar esta predicción (Mejora 3)
        )
        # CREATE TABLE IF NOT EXISTS — idempotente, nunca borra datos
        meta.create_all(engine, checkfirst=True)
        # Add verify_at column to existing tables (migration for existing DBs)
        self._migrate_add_verify_at(engine)

    def _migrate_add_verify_at(self, engine):
        """Adds verify_at column to existing predictions tables (safe migration)."""
        try:
            with engine.connect() as conn:
                # Check if column already exists
                if engine.dialect.name == "postgresql":
                    exists = conn.execute(text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='predictions' AND column_name='verify_at'"
                    )).fetchone()
                else:
                    exists = conn.execute(text(
                        "SELECT 1 FROM pragma_table_info('predictions') WHERE name='verify_at'"
                    )).fetchone()
                if not exists:
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN verify_at TEXT"))
                    conn.commit()
                    logger.info("Migración: columna verify_at añadida a predictions")
        except Exception as e:
            logger.debug(f"verify_at migration note: {e}")

    def _timeframe_to_minutes(self, timeframe: str) -> int:
        # Capped at 3 days max to prevent stale predictions that can't be
        # validated with current prices.  Original values were much longer
        # (days_to_weeks=4320, weeks=10080) but led to predictions going stale.
        mapping = {
            "immediate": 60,
            "hours": 240,
            "hours to days": 480,
            "days": 1440,
            "days to weeks": 2880,
            "weeks": 4320,
        }
        return mapping.get(timeframe, 480)

    def save_prediction(self, event: dict, current_price: float) -> int | None:
        """
        Guarda una predicción. Devuelve el ID de la fila insertada, o None si ya existía.
        Calcula verify_at según el tipo de activo y horario de mercado (Mejoras 3 & 4).
        """
        analysis = event.get("analysis", {})
        event_id = event.get("event_id") or event.get("id") or str(hash(event.get("title", "")))
        title = event.get("title", "")
        category = event.get("category", "")
        asset = (analysis.get("most_affected_assets") or ["UNKNOWN"])[0]
        direction = analysis.get("direction", "neutral")
        impact_percent = float(analysis.get("market_impact_percent", 0))
        timeframe = analysis.get("timeframe", "hours")
        timeframe_minutes = self._timeframe_to_minutes(timeframe)
        confidence = float(analysis.get("confidence", 0))
        reasoning = analysis.get("reasoning", "")
        sources = event.get("sources", [])
        source = ", ".join(sources[:2]) if isinstance(sources, list) else str(sources)
        score = float(event.get("score", event.get("impact_score", 0)))
        predicted_at = datetime.utcnow()

        # Calcular verify_at según el tipo de activo y horario de mercado (Mejoras 3 & 4)
        try:
            verify_dt = calculate_verification_time(asset, predicted_at)
            verify_at = verify_dt.isoformat()
        except Exception:
            verify_at = None

        try:
            with self._get_conn() as conn:
                result = conn.execute(text("""
                    INSERT INTO predictions
                    (event_id, title, category, asset, direction, impact_percent,
                     timeframe, timeframe_minutes, confidence, reasoning,
                     price_at_prediction, predicted_at, outcome, score, source, verify_at)
                    VALUES (:event_id, :title, :category, :asset, :direction, :impact_percent,
                            :timeframe, :timeframe_minutes, :confidence, :reasoning,
                            :price, :predicted_at, 'pending', :score, :source, :verify_at)
                """), {
                    "event_id": event_id, "title": title, "category": category,
                    "asset": asset, "direction": direction, "impact_percent": impact_percent,
                    "timeframe": timeframe, "timeframe_minutes": timeframe_minutes,
                    "confidence": confidence, "reasoning": reasoning,
                    "price": current_price, "predicted_at": predicted_at.isoformat(),
                    "score": score, "source": source, "verify_at": verify_at,
                })
                conn.commit()
                prediction_id = result.lastrowid
                logger.info(f"Predicción guardada: ID={prediction_id} | {title[:60]}")
                return prediction_id
        except Exception as e:
            err_str = str(e)
            if "UNIQUE constraint" in err_str or "unique" in err_str.lower() or "duplicate" in err_str.lower():
                logger.debug(f"Predicción ya existente para event_id={event_id}, omitiendo.")
            else:
                logger.error(f"Error guardando predicción: {e}")
            return None

    def validate_prediction(self, prediction_id: int, current_price: float) -> dict | None:
        """
        Valida una predicción comparando el precio actual con el precio inicial.
        Devuelve dict con resultado o None si no se encontró.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                text("SELECT * FROM predictions WHERE id = :id"), {"id": prediction_id}
            ).mappings().fetchone()

        if not row:
            return None

        pred = dict(row)

        price_at = pred.get("price_at_prediction", 0)
        if not price_at or price_at == 0:
            return None

        actual_change = ((current_price - price_at) / price_at) * 100
        predicted_change = pred.get("impact_percent", 0)
        direction = pred.get("direction", "neutral")

        # Determine if the prediction was correct (with minimum movement threshold)
        if direction in ("up", "bullish", "positive", "alza"):
            correct = actual_change >= _MIN_SIGNIFICANT_MOVE
        elif direction in ("down", "bearish", "negative", "baja"):
            correct = actual_change <= -_MIN_SIGNIFICANT_MOVE
        else:  # neutral
            correct = abs(actual_change) < 1.5

        # Calcular precisión del porcentaje
        if predicted_change != 0:
            pct_accuracy = max(0, 100 - abs(actual_change - abs(predicted_change)) / abs(predicted_change) * 100)
        else:
            pct_accuracy = 100.0 if abs(actual_change) < 0.5 else 0.0

        outcome = "correct" if correct else "incorrect"
        validated_at = datetime.utcnow().isoformat()

        with self._get_conn() as conn:
            conn.execute(text("""
                UPDATE predictions
                SET price_at_validation = :price, validated_at = :validated_at, outcome = :outcome
                WHERE id = :id
            """), {"price": current_price, "validated_at": validated_at, "outcome": outcome, "id": prediction_id})
            conn.commit()

        result = {
            "prediction_id": prediction_id,
            "title": pred.get("title", ""),
            "asset": pred.get("asset", ""),
            "direction": direction,
            "predicted_change": predicted_change,
            "actual_change": round(actual_change, 2),
            "price_at_prediction": price_at,
            "price_at_validation": current_price,
            "outcome": outcome,
            "pct_accuracy": round(pct_accuracy, 1),
            "validated_at": validated_at,
        }
        logger.info(
            f"Predicción validada: ID={prediction_id} | {outcome.upper()} | "
            f"Cambio real: {actual_change:+.2f}% vs predicho: {predicted_change:+.1f}%"
        )
        return result

    def get_pending_predictions(self) -> list[dict]:
        """Devuelve todas las predicciones pendientes de validación."""
        with self._get_conn() as conn:
            rows = conn.execute(
                text("SELECT * FROM predictions WHERE outcome = 'pending'")
            ).mappings().fetchall()

        return [dict(r) for r in rows]

    def get_accuracy_stats(self) -> dict:
        """Devuelve estadísticas de precisión de predicciones."""
        with self._get_conn() as conn:
            rows = conn.execute(
                text("SELECT outcome, confidence, impact_percent FROM predictions WHERE outcome != 'pending'")
            ).fetchall()

            pending = conn.execute(
                text("SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'")
            ).fetchone()[0]

        if not rows:
            return {
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "accuracy_pct": 0.0,
                "high_confidence_accuracy": 0.0,
                "pending": pending,
            }

        total = len(rows)
        correct = sum(1 for r in rows if r[0] == "correct")
        incorrect = total - correct
        accuracy = round(correct / total * 100, 1) if total > 0 else 0.0

        # Accuracy for high-confidence predictions (>= 70%)
        high_conf = [r for r in rows if (r[1] or 0) >= 70]
        hc_correct = sum(1 for r in high_conf if r[0] == "correct")
        hc_accuracy = round(hc_correct / len(high_conf) * 100, 1) if high_conf else 0.0

        return {
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy_pct": accuracy,
            "high_confidence_accuracy": hc_accuracy,
            "pending": pending,
        }

    def get_recent_predictions(self, limit: int = 10) -> list[dict]:
        """Devuelve las N predicciones más recientes."""
        with self._get_conn() as conn:
            rows = conn.execute(
                text("SELECT * FROM predictions ORDER BY id DESC LIMIT :limit"), {"limit": limit}
            ).mappings().fetchall()

        return [dict(r) for r in rows]
