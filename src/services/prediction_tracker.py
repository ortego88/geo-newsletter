"""
Rastreador de predicciones.
Guarda predicciones en SQLite y las valida comparando precios.
"""

import sqlite3
import logging
import os
from datetime import datetime

logger = logging.getLogger("prediction_tracker")

# Minimum price movement (in %) to consider a directional prediction valid.
# Predictions are only "correct" if the price moves at least this much in the predicted direction.
_MIN_SIGNIFICANT_MOVE = 0.15


class PredictionTracker:
    def __init__(self, db_path: str = "data/predictions.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    title TEXT,
                    category TEXT,
                    asset TEXT,
                    direction TEXT,
                    impact_percent REAL,
                    timeframe TEXT,
                    timeframe_minutes INTEGER,
                    confidence REAL,
                    reasoning TEXT,
                    price_at_prediction REAL,
                    price_at_validation REAL,
                    predicted_at TEXT,
                    validated_at TEXT,
                    outcome TEXT,
                    score REAL,
                    source TEXT
                )
            """)
            conn.commit()

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
        predicted_at = datetime.utcnow().isoformat()

        try:
            with self._get_conn() as conn:
                cursor = conn.execute("""
                    INSERT INTO predictions
                    (event_id, title, category, asset, direction, impact_percent,
                     timeframe, timeframe_minutes, confidence, reasoning,
                     price_at_prediction, predicted_at, outcome, score, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """, (
                    event_id, title, category, asset, direction, impact_percent,
                    timeframe, timeframe_minutes, confidence, reasoning,
                    current_price, predicted_at, score, source
                ))
                conn.commit()
                prediction_id = cursor.lastrowid
                logger.info(f"Predicción guardada: ID={prediction_id} | {title[:60]}")
                return prediction_id
        except sqlite3.IntegrityError:
            logger.debug(f"Predicción ya existente para event_id={event_id}, omitiendo.")
            return None
        except Exception as e:
            logger.error(f"Error guardando predicción: {e}")
            return None

    def validate_prediction(self, prediction_id: int, current_price: float) -> dict | None:
        """
        Valida una predicción comparando el precio actual con el precio inicial.
        Devuelve dict con resultado o None si no se encontró.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
            ).fetchone()
            cols = [d[1] for d in conn.execute("PRAGMA table_info(predictions)").fetchall()]

        if not row:
            return None

        pred = dict(zip(cols, row))

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
            conn.execute("""
                UPDATE predictions
                SET price_at_validation = ?, validated_at = ?, outcome = ?
                WHERE id = ?
            """, (current_price, validated_at, outcome, prediction_id))
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
                "SELECT * FROM predictions WHERE outcome = 'pending'"
            ).fetchall()
            cols = [d[1] for d in conn.execute("PRAGMA table_info(predictions)").fetchall()]

        return [dict(zip(cols, row)) for row in rows]

    def get_accuracy_stats(self) -> dict:
        """Devuelve estadísticas de precisión de predicciones."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT outcome, confidence, impact_percent FROM predictions WHERE outcome != 'pending'"
            ).fetchall()

        if not rows:
            return {
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "accuracy_pct": 0.0,
                "high_confidence_accuracy": 0.0,
                "pending": 0,
            }

        total = len(rows)
        correct = sum(1 for r in rows if r[0] == "correct")
        incorrect = total - correct
        accuracy = round(correct / total * 100, 1) if total > 0 else 0.0

        # Accuracy for high-confidence predictions (>= 70%)
        high_conf = [r for r in rows if (r[1] or 0) >= 70]
        hc_correct = sum(1 for r in high_conf if r[0] == "correct")
        hc_accuracy = round(hc_correct / len(high_conf) * 100, 1) if high_conf else 0.0

        # Count pending predictions
        with self._get_conn() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'"
            ).fetchone()[0]

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
                "SELECT * FROM predictions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            cols = [d[1] for d in conn.execute("PRAGMA table_info(predictions)").fetchall()]

        return [dict(zip(cols, row)) for row in rows]
