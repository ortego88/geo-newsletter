"""
Rastreador de predicciones.
Guarda predicciones en PostgreSQL y las valida comparando precios.

Validación binaria con umbral dinámico por capitalización:
- BTC/ETH: CORRECT si alcanza ≥1% en dirección predicha dentro de 24h
- Top 10 (SOL, BNB, XRP, ADA...): CORRECT si alcanza ≥1.5%
- Mid/small caps: CORRECT si alcanza ≥2%
- INCORRECT: no alcanza umbral, o ventana expira
- Cierre anticipado: si llega señal contraria, se cierra con el precio del momento

No existe "neutral" — el sistema debe estar seguro antes de alertar.
"""

import logging
import math
import os
from datetime import datetime, timedelta

from sqlalchemy import text

from web.db_engine import get_engine
from src.services.market_config import calculate_verification_time

logger = logging.getLogger("prediction_tracker")

# Umbral dinámico por capitalización — large caps se mueven menos pero con más convicción
_TIER1_THRESHOLD = 1.0   # BTC, ETH — rara vez mueven 2% sin catalizador
_TIER2_THRESHOLD = 1.5   # SOL, BNB, XRP, ADA, DOGE — top 10
_DEFAULT_THRESHOLD = 2.0 # mid/small caps — necesitan más movimiento para ser significativo

_TIER1_ASSETS = {"BTC", "ETH"}
_TIER2_ASSETS = {"SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "TON", "TRX"}

def _get_threshold_for_asset(asset: str) -> float:
    """Returns the validation threshold for an asset based on market cap tier."""
    a = asset.upper()
    if a in _TIER1_ASSETS:
        return _TIER1_THRESHOLD
    if a in _TIER2_ASSETS:
        return _TIER2_THRESHOLD
    return _DEFAULT_THRESHOLD

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
        self._migrate_add_signal_factors(engine)

    def _migrate_add_signal_factors(self, engine):
        """Adds signal_factors column — stores A/B testing metadata as JSON."""
        try:
            with engine.connect() as conn:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE LOWER(table_name)='predictions' AND LOWER(column_name)='signal_factors'"
                )).fetchone()
                if not exists:
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN signal_factors TEXT"))
                    conn.commit()
                    logger.info("Migración: columna signal_factors añadida a predictions")
        except Exception as e:
            logger.debug(f"signal_factors migration note: {e}")

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

    def _count_daily_predictions(self, asset: str) -> int:
        """Counts how many alerted predictions exist for this asset today."""
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(text("""
                SELECT COUNT(*) FROM predictions
                WHERE asset = :asset
                AND alerted = 1
                AND predicted_at >= :day_start
            """), {"asset": asset, "day_start": day_start}).fetchone()
        return row[0] if row else 0

    def _has_same_direction_pending(self, asset: str, direction: str) -> bool:
        """Checks if there's already a pending prediction for this asset in the same direction."""
        is_up = direction in ("up", "bullish", "positive", "alza")
        up_dirs = "('up','bullish','positive','alza')"
        down_dirs = "('down','bearish','negative','baja')"
        dir_filter = up_dirs if is_up else down_dirs
        with self._get_conn() as conn:
            row = conn.execute(text(f"""
                SELECT id FROM predictions
                WHERE asset = :asset
                AND outcome = 'pending'
                AND direction IN {dir_filter}
                LIMIT 1
            """), {"asset": asset}).fetchone()
        return row is not None

    def _close_opposite_pending(self, asset: str, new_direction: str, current_price: float):
        """
        When a new signal arrives in opposite direction, close any pending prediction
        for the same asset immediately. Correct only if the best tracked price already
        reached ≥2% in the predicted direction; otherwise incorrect.
        """
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
                if not p_in or p_in <= 0:
                    continue

                # Check if this prediction's direction is opposite to the new signal
                pred_is_up = pred_dir in ("up", "bullish", "positive", "alza")
                new_is_up = new_direction in ("up", "bullish", "positive", "alza")
                if pred_is_up == new_is_up:
                    continue  # same direction, not a counter-signal

                # Use the best price tracked so far (or current if no best yet)
                best = best_so_far if best_so_far > 0 else current_price
                best_change = (best - p_in) / p_in * 100

                # Binary: correct only if best price already reached threshold in predicted direction
                threshold = _get_threshold_for_asset(asset)
                if pred_is_up:
                    outcome = "correct" if best_change >= threshold else "incorrect"
                else:
                    outcome = "correct" if best_change <= -threshold else "incorrect"

                with self._get_conn() as conn:
                    conn.execute(text("""
                        UPDATE predictions
                        SET outcome = :outcome,
                            price_at_validation = :price,
                            validated_at = :now
                        WHERE id = :id
                    """), {
                        "outcome": outcome,
                        "price": current_price,
                        "now": datetime.utcnow().isoformat(),
                        "id": pred_id,
                    })
                    conn.commit()
                logger.info(
                    f"🔄 Predicción #{pred_id} {asset} {pred_dir} cerrada por señal contraria "
                    f"({new_direction}) → {outcome} (mejor cambio: {best_change:+.1f}%)"
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

    def save_prediction_silent(self, event: dict, current_price: float) -> int | None:
        """Save a silent calibration prediction — bypasses cooldown and counter-signal checks."""
        analysis = event.get("analysis", {})
        asset = (analysis.get("most_affected_assets") or ["UNKNOWN"])[0]
        direction = analysis.get("direction", "neutral")
        if direction == "neutral":
            return None
        # Still check for very recent duplicate (same asset+direction in last 30min)
        cutoff_30m = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        with self._get_conn() as conn:
            dup = conn.execute(text("""
                SELECT id FROM predictions
                WHERE asset = :asset AND direction = :dir
                  AND source LIKE '%silent%'
                  AND predicted_at >= :cutoff
                LIMIT 1
            """), {"asset": asset, "dir": direction, "cutoff": cutoff_30m}).fetchone()
        if dup:
            return None
        # Delegate to save_prediction but skip cooldown checks by temporarily patching
        original_method = self._has_recent_prediction
        self._has_recent_prediction = lambda *a, **kw: False
        original_contradictory = self._close_opposite_pending
        self._close_opposite_pending = lambda *a, **kw: None
        try:
            return self.save_prediction(event, current_price)
        finally:
            self._has_recent_prediction = original_method
            self._close_opposite_pending = original_contradictory

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

        # ── Quality gate: reject signals with historically poor accuracy ──
        confidence = float(analysis.get("confidence", 0))
        raw_source = event.get("source", "")
        is_price_signal = "Price Monitor" in raw_source or raw_source == "price_signal"
        is_up = direction in ("up", "bullish", "positive", "alza")

        # 1. Block Price Monitor signals — 41% accuracy
        if is_price_signal:
            logger.info(f"⏭️ Filtro calidad: Price Monitor descartado para {asset} (41% histórico)")
            return None

        # 2. Block UP signals with confidence < 65 — 27.6% accuracy
        if is_up and confidence < 65:
            logger.info(f"⏭️ Filtro calidad: UP+conf<65 descartado para {asset} (conf={confidence})")
            return None

        # 3. Block assets with 0% accuracy in last 7 days
        _BLOCKED_ASSETS = {"BNB", "SUI", "OP", "DOGE"}
        if asset.upper() in _BLOCKED_ASSETS:
            logger.info(f"⏭️ Filtro calidad: {asset} bloqueado (0% accuracy última semana)")
            return None

        # 4. Block bad hours: 15:00-20:00 UTC (27-32% accuracy)
        hour_utc = datetime.utcnow().hour
        if 15 <= hour_utc <= 20:
            logger.info(f"⏭️ Filtro calidad: hora {hour_utc} UTC descartada (27-32% histórico)")
            return None

        # Max 3 alerted predictions per asset per day
        daily_count = self._count_daily_predictions(asset)
        if daily_count >= 3:
            logger.info(f"⏭️ Predicción omitida para {asset}: ya tiene {daily_count} alertas hoy (máx 3)")
            return None

        # Skip if same direction already pending (avoid duplicates)
        if self._has_same_direction_pending(asset, direction):
            logger.info(f"⏭️ Predicción omitida para {asset}: ya hay una pendiente en dirección {direction}")
            return None

        # Cooldown de 3h entre predicciones del mismo activo
        if self._has_recent_prediction(asset, hours=3):
            logger.info(f"⏭️ Predicción omitida para {asset}: ya existe predicción reciente (<3h)")
            return None

        # No longer close opposite predictions early — let each prediction live its full 24h window

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

        # Validate price: reject if zero or suspiciously far from recent prices
        if current_price <= 0:
            logger.warning(f"⚠️  Precio inválido para {asset}: ${current_price} — predicción omitida")
            return None

        # Check for price outliers (>10x or <0.1x from last known price)
        try:
            with self._get_conn() as conn:
                last_price_row = conn.execute(text("""
                    SELECT price_at_prediction FROM predictions
                    WHERE asset = :asset AND price_at_prediction > 0
                    ORDER BY predicted_at DESC LIMIT 1
                """), {"asset": asset}).fetchone()
                if last_price_row:
                    last_price = float(last_price_row[0])
                    ratio = current_price / last_price if last_price > 0 else 1
                    if ratio > 10 or ratio < 0.1:
                        logger.warning(
                            f"⚠️  Precio outlier detectado para {asset}: "
                            f"${last_price:.6f} → ${current_price:.6f} (ratio: {ratio:.2f}x) "
                            f"— revisar RealPriceFetcher"
                        )
        except Exception as e:
            logger.debug(f"Error checking price outlier for {asset}: {e}")

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
        Validación binaria con umbral dinámico por capitalización:
        - BTC/ETH: CORRECT si alcanza ≥1% en dirección predicha
        - Top 10 (SOL, BNB, XRP...): CORRECT si alcanza ≥1.5%
        - Mid/small caps: CORRECT si alcanza ≥2%

        Dentro de la ventana (24h):
        - Trackea el mejor precio visto (max para UP, min para DOWN)
        - Si el mejor ya alcanza umbral → CORRECT inmediato
        - Si la ventana no ha expirado y no se alcanzó → return None (retry next cycle)

        Al expirar la ventana:
        - Si el mejor precio tracked alguna vez alcanzó umbral → CORRECT
        - Si no → INCORRECT (sin zona gris)
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
        if direction == "neutral":
            return None

        predicted_at_str = pred.get("predicted_at", "")
        try:
            predicted_at = datetime.fromisoformat(predicted_at_str)
        except (ValueError, TypeError):
            predicted_at = datetime.utcnow() - timedelta(hours=_EVALUATION_WINDOW_HOURS + 1)

        window_expired = (datetime.utcnow() - predicted_at).total_seconds() >= _EVALUATION_WINDOW_HOURS * 3600
        actual_change_pct = ((current_price - price_at) / price_at) * 100

        # Dynamic threshold based on asset market cap tier
        asset = pred.get("asset", "UNKNOWN")
        threshold = _get_threshold_for_asset(asset)

        # Track best price seen so far in price_at_validation field
        prev_best = pred.get("price_at_validation") or 0
        is_up = direction in ("up", "bullish", "positive", "alza")

        if is_up:
            best_price = max(current_price, prev_best) if prev_best > 0 else current_price
            best_change_pct = ((best_price - price_at) / price_at) * 100
            threshold_reached = best_change_pct >= threshold
        else:
            best_price = min(current_price, prev_best) if prev_best > 0 else current_price
            best_change_pct = ((best_price - price_at) / price_at) * 100
            threshold_reached = best_change_pct <= -threshold

        if threshold_reached:
            # Target reached — CORRECT immediately, no need to wait for window expiry
            outcome = "correct"
        elif not window_expired:
            # Still within 24h window — update best price and retry next cycle
            should_update = (
                (is_up and best_price > (prev_best or 0)) or
                (not is_up and (prev_best <= 0 or best_price < prev_best))
            )
            if should_update:
                with self._get_conn() as conn:
                    conn.execute(text(
                        "UPDATE predictions SET price_at_validation = :price WHERE id = :id"
                    ), {"price": best_price, "id": prediction_id})
                    conn.commit()
            return None
        else:
            # Window expired without reaching ≥2% — INCORRECT
            outcome = "incorrect"

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
            "predicted_change": pred.get("predicted_change", 0),
            "actual_change": round(actual_change_pct, 2),
            "price_at_prediction": price_at,
            "price_at_validation": current_price,
            "outcome": outcome,
            "validated_at": validated_at,
        }

        outcome_icon = "✅" if outcome == "correct" else "❌"
        logger.info(
            f"Predicción validada: ID={prediction_id} | {outcome_icon} {outcome.upper()} | "
            f"Dirección: {direction} | Mejor cambio: {best_change_pct:+.2f}% | "
            f"Umbral: {threshold}% | Ventana {'expirada' if window_expired else 'activa'}"
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
        Binary: solo correct e incorrect. No existe neutral en el nuevo sistema.
        """
        silent_filter = " AND source NOT IN ('price_signal_late_move', 'price_signal_silent')"

        with self._get_conn() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT outcome, confidence, impact_percent
                    FROM predictions
                    WHERE outcome IN ('correct', 'incorrect'){silent_filter}
                """)
            ).fetchall()

            pending = conn.execute(
                text(f"SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'{silent_filter}")
            ).fetchone()[0]

            neutral = conn.execute(
                text(f"SELECT COUNT(*) FROM predictions WHERE outcome = 'neutral'{silent_filter}")
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

    def check_early_reversals(self, price_fetcher) -> list[dict]:
        """
        Checks pending predictions that are moving strongly AGAINST the predicted direction.
        If price moved >= 1.5x threshold against, mark as incorrect early and return
        reversal events (opposite direction) ready to be alerted.

        This lets users react quickly when the market turns against a prediction.
        """
        pending = self.get_pending_predictions()
        if not pending:
            return []

        reversals = []
        now = datetime.utcnow()

        for pred in pending:
            pred_id = pred.get("id")
            asset = pred.get("asset", "UNKNOWN")
            direction = pred.get("direction", "neutral")
            price_at = pred.get("price_at_prediction", 0)
            predicted_at_str = pred.get("predicted_at", "")

            if not price_at or price_at <= 0 or direction == "neutral":
                continue

            # Only check predictions that are at least 1h old (avoid noise)
            try:
                predicted_at = datetime.fromisoformat(predicted_at_str)
                elapsed_hours = (now - predicted_at).total_seconds() / 3600
                if elapsed_hours < 1:
                    continue
            except (ValueError, TypeError):
                continue

            current_price = price_fetcher.get_price(asset)
            if current_price is None or current_price <= 0:
                continue

            change_pct = (current_price - price_at) / price_at * 100
            threshold = _get_threshold_for_asset(asset)
            reversal_threshold = threshold * 1.5

            is_up = direction in ("up", "bullish", "positive", "alza")

            # Check if price moved strongly AGAINST the prediction
            should_reverse = False
            if is_up and change_pct <= -reversal_threshold:
                should_reverse = True
            elif not is_up and change_pct >= reversal_threshold:
                should_reverse = True

            if not should_reverse:
                continue

            # Check daily limit before generating reversal
            daily_count = self._count_daily_predictions(asset)
            if daily_count >= 3:
                logger.info(f"🔄 Reversión detectada para {asset} pero ya tiene {daily_count} alertas hoy")
                continue

            # Mark the failing prediction as incorrect
            with self._get_conn() as conn:
                conn.execute(text("""
                    UPDATE predictions
                    SET outcome = 'incorrect',
                        price_at_validation = :price,
                        validated_at = :now
                    WHERE id = :id
                """), {
                    "price": current_price,
                    "now": now.isoformat(),
                    "id": pred_id,
                })
                conn.commit()

            new_direction = "down" if is_up else "up"
            logger.info(
                f"🔄 REVERSIÓN: {asset} #{pred_id} {direction} → marcada incorrecta "
                f"({change_pct:+.1f}% vs umbral ±{reversal_threshold:.1f}%). "
                f"Generando señal {new_direction}"
            )

            # Build reversal event
            reversal_event = {
                "title": f"[Reversión] {asset} señal {new_direction.upper()} (cambio de tendencia)",
                "description": f"Predicción anterior ({direction}) invalidada por movimiento de {change_pct:+.1f}%. Nueva dirección: {new_direction}.",
                "source": "Early Reversal",
                "score": 75,
                "suggested_asset": asset,
                "category": "reversal",
                "_silent": False,
                "_is_reversal": True,
                "analysis": {
                    "direction": new_direction,
                    "confidence": 70,
                    "most_affected_assets": [asset],
                    "timeframe": "hours",
                    "reasoning": f"Reversión: {asset} {change_pct:+.1f}% contra predicción anterior. Cambio de tendencia confirmado.",
                    "signal_strength": "high",
                    "verification_window_hours": 24,
                },
            }

            # Save the reversal prediction
            rev_pred_id = self.save_prediction(reversal_event, current_price)
            if rev_pred_id:
                reversal_event["prediction_id"] = rev_pred_id
                reversal_event["price_at_prediction"] = current_price
                reversals.append(reversal_event)

        if reversals:
            logger.info(f"🔄 {len(reversals)} reversiones generadas en este ciclo")
        return reversals
