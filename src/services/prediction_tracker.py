"""
Rastreador de predicciones.
Guarda predicciones en PostgreSQL y las valida comparando precios.

Validación basada en umbral ±1% en ventana de 24h:
- Si el precio se mueve >=1% en la dirección predicha → CORRECT
- Si se mueve >=1% en la dirección opuesta → INCORRECT
- Si tras 24h no alcanza ±1% → NEUTRAL (no penaliza accuracy)
"""

import logging
import math
import os
from datetime import datetime, timedelta

from sqlalchemy import text

from web.db_engine import get_engine
from src.services.market_config import calculate_verification_time

logger = logging.getLogger("prediction_tracker")

# Umbral de movimiento significativo para validar predicciones.
# Si en las 24h siguientes el precio se mueve >= 1% en la dirección predicha → CORRECT
# Si se mueve >= 1% en la dirección opuesta → INCORRECT
# Si no alcanza 1% en ninguna dirección al finalizar las 24h → NEUTRAL
_THRESHOLD_PCT = 2.0  # 2% — simétrico y honesto: exige movimiento real
_INCORRECT_THRESHOLD_PCT = 2.0  # 2% — mismo umbral en dirección contraria

# Ventana de evaluación en horas
_EVALUATION_WINDOW_HOURS = 24


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
            Column("verify_at", Text),  # cuándo verificar esta predicción
            Column("source_url", Text),  # URL de la noticia original
            Column("verification_window_hours", Integer),  # recomendado por Claude
        )
        # CREATE TABLE IF NOT EXISTS — idempotente, nunca borra datos
        meta.create_all(engine, checkfirst=True)
        # Add verify_at column to existing tables (migration for existing DBs)
        self._migrate_add_verify_at(engine)
        # Add source_url column to existing tables (migration for existing DBs)
        self._migrate_add_source_url(engine)
        # Add verification_window_hours column to existing tables
        self._migrate_add_verification_window(engine)

    def _migrate_add_verify_at(self, engine):
        """Adds verify_at column to existing predictions tables (safe migration)."""
        try:
            with engine.connect() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE LOWER(table_name)='predictions' AND LOWER(column_name)='verify_at'"
                )).fetchone()
                if not exists:
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN verify_at TEXT"))
                    conn.commit()
                    logger.info("Migración: columna verify_at añadida a predictions")
        except Exception as e:
            logger.debug(f"verify_at migration note: {e}")

    def _migrate_add_source_url(self, engine):
        """Adds source_url column to existing predictions tables (safe migration)."""
        try:
            with engine.connect() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE LOWER(table_name)='predictions' AND LOWER(column_name)='source_url'"
                )).fetchone()
                if not exists:
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN source_url TEXT"))
                    conn.commit()
                    logger.info("Migración: columna source_url añadida a predictions")
        except Exception as e:
            logger.debug(f"source_url migration note: {e}")

    def _migrate_add_verification_window(self, engine):
        """Adds verification_window_hours column to existing predictions tables (safe migration)."""
        try:
            with engine.connect() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE LOWER(table_name)='predictions' AND LOWER(column_name)='verification_window_hours'"
                )).fetchone()
                if not exists:
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN verification_window_hours INTEGER"))
                    conn.commit()
                    logger.info("Migración: columna verification_window_hours añadida a predictions")
        except Exception as e:
            logger.debug(f"verification_window_hours migration note: {e}")
        self._migrate_add_alerted(engine)

    def _migrate_add_alerted(self, engine):
        """Adds alerted column — marks predictions that were actually sent to Telegram."""
        try:
            with engine.connect() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE LOWER(table_name)='predictions' AND LOWER(column_name)='alerted'"
                )).fetchone()
                if not exists:
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN alerted INTEGER DEFAULT 0"))
                    conn.commit()
                    logger.info("Migración: columna alerted añadida a predictions")
        except Exception as e:
            logger.debug(f"alerted migration note: {e}")

    def mark_as_alerted(self, prediction_id: int):
        """Marks a prediction as having been sent to Telegram."""
        try:
            with self._get_conn() as conn:
                conn.execute(text(
                    "UPDATE predictions SET alerted = 1 WHERE id = :pid"
                ), {"pid": prediction_id})
                conn.commit()
        except Exception as e:
            logger.warning(f"Error marking prediction {prediction_id} as alerted: {e}")

    def _timeframe_to_minutes(self, timeframe: str) -> int:
        # Capped at 3 days max to prevent stale predictions that can't be
        # validated with current prices.
        mapping = {
            "immediate": 60,
            "hours": 240,
            "hours to days": 480,
            "days": 1440,
            "days to weeks": 2880,
            "weeks": 4320,
        }
        return mapping.get(timeframe, 480)

    def _has_recent_prediction(self, asset: str, hours: float = 1) -> bool:
        """Comprueba si ya existe una predicción pendiente reciente para este activo."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(text("""
                SELECT id FROM predictions
                WHERE asset = :asset
                AND outcome = 'pending'
                AND predicted_at >= :cutoff
                ORDER BY id DESC LIMIT 1
            """), {"asset": asset, "cutoff": cutoff}).fetchone()
        return row is not None

    def _close_opposite_pending(self, asset: str, new_direction: str, current_price: float):
        """
        When a new signal arrives in opposite direction, close any pending prediction
        for the same asset. This implements the 'close on counter-signal' window rule.
        """
        opposite_dir = "down" if new_direction in ("up", "bullish", "positive", "alza") else "up"
        try:
            with self._get_conn() as conn:
                rows = conn.execute(text("""
                    SELECT id, direction, price_at_prediction,
                           COALESCE(price_at_validation, 0) as best_so_far
                    FROM predictions
                    WHERE asset = :asset AND outcome = 'pending'
                      AND direction IN ('up','bullish','positive','alza','down','bearish','negative','baja')
                """), {"asset": asset}).fetchall()

            for row in rows:
                pred_id, pred_dir, p_in, best_so_far = row
                is_opposite = (
                    pred_dir in ("up", "bullish", "positive", "alza") and
                    opposite_dir == "up"
                ) or (
                    pred_dir in ("down", "bearish", "negative", "baja") and
                    opposite_dir == "down"
                )
                if not is_opposite or not p_in or p_in <= 0:
                    continue

                # Use the best price tracked so far (or current if no best yet)
                best = best_so_far if best_so_far > 0 else current_price
                best_change = (best - p_in) / p_in * 100

                if pred_dir in ("up", "bullish", "positive", "alza"):
                    outcome = "correct" if best_change >= _THRESHOLD_PCT else "incorrect"
                else:
                    outcome = "correct" if best_change <= -_THRESHOLD_PCT else "incorrect"

                with self._get_conn() as conn:
                    conn.execute(text("""
                        UPDATE predictions
                        SET outcome = :outcome,
                            price_at_validation = :price,
                            validated_at = :now
                        WHERE id = :id
                    """), {
                        "outcome": outcome,
                        "price": best,
                        "now": datetime.utcnow().isoformat(),
                        "id": pred_id,
                    })
                    conn.commit()
                logger.info(
                    f"🔄 Predicción #{pred_id} {asset} {pred_dir} cerrada por señal contraria "
                    f"({new_direction}) → {outcome} (mejor: {best_change:+.1f}%)"
                )
        except Exception as e:
            logger.warning(f"Error closing opposite prediction for {asset}: {e}")

    def _has_contradictory_prediction(self, asset: str, direction: str) -> bool:
        """Blocks opposite-direction signals within 4h of a recent prediction."""
        cutoff = (datetime.utcnow() - timedelta(hours=4)).isoformat()
        opposite = "down" if direction in ("up", "bullish", "positive", "alza") else "up"
        with self._get_conn() as conn:
            row = conn.execute(text("""
                SELECT id, direction FROM predictions
                WHERE asset = :asset
                AND predicted_at >= :cutoff
                ORDER BY id DESC LIMIT 1
            """), {"asset": asset, "cutoff": cutoff}).fetchone()
        if not row:
            return False
        last_direction = row[1] or ""
        if direction != last_direction and last_direction in ("up", "down"):
            logger.info(
                f"🚫 Señal contradictoria bloqueada: {asset} {direction} vs reciente {last_direction}"
            )
            return True
        return False

    def save_prediction(self, event: dict, current_price: float) -> int | None:
        """
        Guarda una predicción. Devuelve el ID de la fila insertada, o None si ya existía
        o si ya existe una predicción pendiente reciente para el mismo activo.
        """
        analysis = event.get("analysis", {})
        event_id = event.get("event_id") or event.get("id") or str(hash(event.get("title", "")))
        title = event.get("title", "")
        category = event.get("category", "")
        asset = (analysis.get("most_affected_assets") or ["UNKNOWN"])[0]

        direction = analysis.get("direction", "neutral")
        if direction == "neutral":
            logger.info(f"⏭️ Predicción neutral descartada para {asset}: no genera valor")
            return None

        # Cooldown de 3h entre predicciones del mismo activo
        if self._has_recent_prediction(asset, hours=3):
            logger.info(f"⏭️ Predicción omitida para {asset}: ya existe predicción reciente (<3h)")
            return None

        # If there's an opposite pending prediction, close it first (counter-signal)
        self._close_opposite_pending(asset, direction, current_price)

        impact_percent = float(analysis.get("market_impact_percent", 0))
        timeframe = analysis.get("timeframe", "hours")
        timeframe_minutes = self._timeframe_to_minutes(timeframe)
        confidence = float(analysis.get("confidence", 0))
        reasoning = analysis.get("reasoning", "")
        sources = event.get("sources", [])
        source = ", ".join(sources[:2]) if isinstance(sources, list) else str(sources)
        score = float(event.get("score", event.get("impact_score", 0)))
        source_url = event.get("url") or event.get("link") or ""
        predicted_at = datetime.utcnow()

        # Usar verification_window_hours recomendado por Claude (si está disponible)
        verification_window_hours = analysis.get("verification_window_hours")
        if not verification_window_hours:
            from src.services.market_config import get_verification_window
            verification_window_hours = get_verification_window(asset)

        # Calcular verify_at usando la ventana de verificación recomendada
        try:
            verify_dt = predicted_at + timedelta(hours=verification_window_hours)
            verify_at = verify_dt.isoformat()
        except Exception:
            verify_at = None

        # Derive signal_type from source for analytics
        raw_source = event.get("source", "")
        if "microstructure" in raw_source:
            if "whale" in raw_source:
                signal_type = "whale_trade"
            elif "funding" in raw_source:
                signal_type = "funding_rate"
            elif "liquidation" in raw_source:
                signal_type = "liquidation"
            else:
                signal_type = "microstructure"
        elif raw_source in ("price_signal", "Price Monitor"):
            signal_type = "price_signal"
        else:
            signal_type = "news"

        try:
            with self._get_conn() as conn:
                result = conn.execute(text("""
                    INSERT INTO predictions
                    (event_id, title, category, asset, direction, impact_percent,
                     timeframe, timeframe_minutes, confidence, reasoning,
                     price_at_prediction, predicted_at, outcome, score, source, verify_at,
                     source_url, verification_window_hours, signal_type)
                    VALUES (:event_id, :title, :category, :asset, :direction, :impact_percent,
                            :timeframe, :timeframe_minutes, :confidence, :reasoning,
                            :price, :predicted_at, 'pending', :score, :source, :verify_at,
                            :source_url, :verification_window_hours, :signal_type)
                    RETURNING id
                """), {
                    "event_id": event_id, "title": title, "category": category,
                    "asset": asset, "direction": direction, "impact_percent": impact_percent,
                    "timeframe": timeframe, "timeframe_minutes": timeframe_minutes,
                    "confidence": confidence, "reasoning": reasoning,
                    "price": current_price, "predicted_at": predicted_at.isoformat(),
                    "score": score, "source": source, "verify_at": verify_at,
                    "source_url": source_url, "verification_window_hours": verification_window_hours,
                    "signal_type": signal_type,
                })
                conn.commit()
                prediction_id = result.fetchone()[0]
                logger.info(f"Predicción guardada: ID={prediction_id} | {title[:60]} | verificar en {verification_window_hours}h")
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
        Valida una predicción basándose en el máximo movimiento favorable durante 24h.

        Lógica: el valor de la alerta es la OPORTUNIDAD que generó, no el precio final.
        Si predices UP y el precio llega a +20% en algún momento, la alerta fue valiosa
        aunque cierre en -3%. El usuario tuvo 20% de ventana para actuar.

        - Ventana no expirada → track max_price en campo price_at_validation para UP
                                  track min_price en campo price_at_validation para DOWN
        - Al expirar 24h:
          - Para UP: si max alcanzado >= +2% sobre precio entrada → CORRECT
          - Para DOWN: si min alcanzado <= -2% sobre precio entrada → CORRECT
          - Si no se alcanzó el umbral en ningún momento → INCORRECT
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

        direction = pred.get("direction", "neutral")

        predicted_at_str = pred.get("predicted_at", "")
        try:
            predicted_at = datetime.fromisoformat(predicted_at_str)
        except (ValueError, TypeError):
            predicted_at = datetime.utcnow() - timedelta(hours=_EVALUATION_WINDOW_HOURS + 1)

        window_expired = (datetime.utcnow() - predicted_at).total_seconds() >= _EVALUATION_WINDOW_HOURS * 3600
        actual_change_pct = ((current_price - price_at) / price_at) * 100

        # Track best price seen so far in price_at_validation field
        # For UP: track the maximum (best case for buyer)
        # For DOWN: track the minimum (best case for seller)
        prev_best = pred.get("price_at_validation") or 0

        if direction in ("up", "bullish", "positive", "alza"):
            # Update best (maximum) price seen
            best_price = max(current_price, prev_best) if prev_best > 0 else current_price
            best_change_pct = ((best_price - price_at) / price_at) * 100

            if not window_expired:
                # Still within window — update best price seen but don't finalize
                if best_price > (prev_best or 0):
                    with self._get_conn() as conn:
                        conn.execute(text(
                            "UPDATE predictions SET price_at_validation = :price WHERE id = :id"
                        ), {"price": best_price, "id": prediction_id})
                        conn.commit()
                return None

            # Window expired — evaluate based on best price achieved
            if best_change_pct >= _THRESHOLD_PCT:
                outcome = "correct"
            else:
                outcome = "incorrect"

        elif direction in ("down", "bearish", "negative", "baja"):
            # Update best (minimum) price seen
            best_price = min(current_price, prev_best) if prev_best > 0 else current_price
            best_change_pct = ((best_price - price_at) / price_at) * 100

            if not window_expired:
                if best_price < (prev_best or float('inf')):
                    with self._get_conn() as conn:
                        conn.execute(text(
                            "UPDATE predictions SET price_at_validation = :price WHERE id = :id"
                        ), {"price": best_price, "id": prediction_id})
                        conn.commit()
                return None

            # Window expired — evaluate based on best (lowest) price achieved
            if best_change_pct <= -_THRESHOLD_PCT:
                outcome = "correct"
            else:
                outcome = "incorrect"

        else:  # neutral
            if not window_expired:
                return None
            outcome = "neutral"
            best_price = current_price
            actual_change_pct = ((best_price - price_at) / price_at) * 100

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
            "actual_change": round(actual_change_pct, 2),
            "price_at_prediction": price_at,
            "price_at_validation": current_price,
            "outcome": outcome,
            "validated_at": validated_at,
        }

        outcome_icon = "✅" if outcome == "correct" else ("⚪" if outcome == "neutral" else "❌")
        logger.info(
            f"Predicción validada: ID={prediction_id} | {outcome_icon} {outcome.upper()} | "
            f"Dirección predicha: {direction} | "
            f"Cambio real: {actual_change_pct:+.3f}% | Umbral: ±{_THRESHOLD_PCT}% | "
            f"Ventana {'expirada' if window_expired else 'activa'}"
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
        """
        Devuelve estadísticas de precisión de predicciones.

        IMPORTANTE: Las predicciones con outcome='neutral' NO se incluyen en el
        cálculo de accuracy (ni como correctas ni como incorrectas).
        Solo se cuentan 'correct' e 'incorrect' para la tasa de aciertos.
        Esto evita que predicciones con movimientos insignificantes penalicen la métrica.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                text("""
                    SELECT outcome, confidence, impact_percent
                    FROM predictions
                    WHERE outcome NOT IN ('pending', 'neutral')
                """)
            ).fetchall()

            pending = conn.execute(
                text("SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'")
            ).fetchone()[0]

            neutral = conn.execute(
                text("SELECT COUNT(*) FROM predictions WHERE outcome = 'neutral'")
            ).fetchone()[0]

        if not rows:
            return {
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "accuracy_pct": 0.0,
                "high_confidence_accuracy": 0.0,
                "pending": pending,
                "neutral": neutral,
            }

        total = len(rows)
        correct = sum(1 for r in rows if r[0] == "correct")
        incorrect = total - correct
        accuracy = round(correct / total * 100, 1) if total > 0 else 0.0

        # Accuracy para predicciones de alta confianza (>= 70%)
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
            "neutral": neutral,
        }

    def get_recent_predictions(self, limit: int = 10) -> list[dict]:
        """Devuelve las N predicciones más recientes."""
        with self._get_conn() as conn:
            rows = conn.execute(
                text("SELECT * FROM predictions ORDER BY id DESC LIMIT :limit"), {"limit": limit}
            ).mappings().fetchall()

        return [dict(r) for r in rows]

    def get_predictions_paginated(self, period: str = "24h", page: int = 1, page_size: int = 20) -> dict:
        """
        Devuelve predicciones paginadas con filtro por período.
        period: '24h' | '7d' | '30d' | 'all'
        """
        cutoff_map = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }

        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        if period in cutoff_map:
            cutoff = (datetime.utcnow() - cutoff_map[period]).isoformat()
            where_clause = "WHERE predicted_at >= :cutoff"
            params_count = {"cutoff": cutoff}
            params_rows = {"cutoff": cutoff, "page_size": page_size, "offset": offset}
        else:
            where_clause = ""
            params_count = {}
            params_rows = {"page_size": page_size, "offset": offset}

        with self._get_conn() as conn:
            total = conn.execute(
                text(f"SELECT COUNT(*) FROM predictions {where_clause}"),
                params_count,
            ).fetchone()[0]

            rows = conn.execute(
                text(
                    f"SELECT * FROM predictions {where_clause} "
                    "ORDER BY id DESC LIMIT :page_size OFFSET :offset"
                ),
                params_rows,
            ).mappings().fetchall()

        total_pages = max(1, math.ceil(total / page_size))
        return {
            "predictions": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
