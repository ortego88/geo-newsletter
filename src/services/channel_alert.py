"""
Canal privado de Telegram — alerta BTC + resumen diario.

Flujo:
- Cada ciclo: si hay una alerta BTC de calidad y no se ha enviado hoy, se envía
  inmediatamente al canal (máx 1 alerta/día, siempre BTC para atraer usuarios).
- A las 10:00 (Madrid): resumen del día anterior con resultados de predicciones.

Variables de entorno:
  TELEGRAM_BOT_TOKEN      — token del bot (compartido con alertas individuales)
  TELEGRAM_CHANNEL_ID     — ID del canal privado (ej: -1001234567890)
"""

import logging
import os
from datetime import datetime, timedelta

import pytz
import requests
from sqlalchemy import text

from web.db_engine import get_engine
from src.services.alert_formatter import (
    AssetPriceFetcher, ASSET_ICONS, ASSET_NAMES, _now_madrid,
)

logger = logging.getLogger("channel_alert")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

_MIN_SCORE = 60
_MIN_CONFIDENCE = 60

_MADRID_TZ = pytz.timezone("Europe/Madrid")


def _init_channel_log_table():
    """Creates channel_alert_log table if it doesn't exist."""
    engine = get_engine("app")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS channel_alert_log (
                id SERIAL PRIMARY KEY,
                sent_date TEXT NOT NULL,
                event_title TEXT,
                asset TEXT,
                score INTEGER,
                confidence INTEGER,
                prediction_id INTEGER,
                sent_at TEXT NOT NULL,
                result_posted BOOLEAN DEFAULT FALSE
            )
        """))
        conn.commit()
        # Migration: add prediction_id if missing
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='channel_alert_log' AND column_name='prediction_id'
        """)).fetchone()
        if not result:
            conn.execute(text("ALTER TABLE channel_alert_log ADD COLUMN prediction_id INTEGER"))
            conn.commit()
        # Migration: add result_posted if missing
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='channel_alert_log' AND column_name='result_posted'
        """)).fetchone()
        if not result:
            conn.execute(text("ALTER TABLE channel_alert_log ADD COLUMN result_posted BOOLEAN DEFAULT FALSE"))
            conn.commit()


def _already_sent_today() -> bool:
    """Returns True if we already sent the daily BTC alert."""
    today = _now_madrid().strftime("%Y-%m-%d")
    try:
        _init_channel_log_table()
        with get_engine("app").connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM channel_alert_log WHERE sent_date = :today"),
                {"today": today},
            ).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"Error checking channel_alert_log: {e}")
        return False


def _log_sent(event: dict, analysis: dict):
    """Records that today's channel alert was sent."""
    today = _now_madrid().strftime("%Y-%m-%d")
    now_iso = datetime.utcnow().isoformat()
    asset = (analysis.get("most_affected_assets") or [""])[0]
    prediction_id = event.get("prediction_id")
    try:
        with get_engine("app").connect() as conn:
            conn.execute(text("""
                INSERT INTO channel_alert_log (sent_date, event_title, asset, score, confidence, prediction_id, sent_at)
                VALUES (:date, :title, :asset, :score, :conf, :pred_id, :sent_at)
            """), {
                "date": today,
                "title": (event.get("title") or "")[:200],
                "asset": asset,
                "score": int(event.get("score", 0)),
                "conf": int(analysis.get("confidence", 0)),
                "pred_id": prediction_id,
                "sent_at": now_iso,
            })
            conn.commit()
    except Exception as e:
        logger.warning(f"Error logging channel alert: {e}")


def _format_channel_message(event: dict, analysis: dict) -> str:
    """Formats the BTC channel alert — premium look, concise."""
    fetcher = AssetPriceFetcher()

    title = event.get("title", "Sin título")
    score = event.get("score", 0)
    direction = analysis.get("direction", "neutral")
    confidence = analysis.get("confidence", 0)
    reasoning = (analysis.get("reasoning") or "")[:200]
    affected_assets = analysis.get("most_affected_assets", [])
    timeframe = analysis.get("timeframe", "hours")

    timeframe_es = {
        "hours": "horas",
        "days": "días",
        "hours to days": "horas a días",
        "days to weeks": "días a semanas",
        "weeks": "semanas",
        "immediate": "inmediato",
    }.get(timeframe, timeframe)

    if direction in ("up", "bullish", "positive", "alza"):
        dir_icon = "📈"
        dir_text = "ALCISTA"
    elif direction in ("down", "bearish", "negative", "baja"):
        dir_icon = "📉"
        dir_text = "BAJISTA"
    else:
        dir_icon = "➡️"
        dir_text = "LATERAL"

    lines = []
    lines.append("🔔 ALERTA DEL DÍA — Trianio")
    lines.append("")
    lines.append(f"📍 {title}")
    lines.append("")

    if affected_assets:
        asset = affected_assets[0].upper()
        icon = ASSET_ICONS.get(asset, "💹")
        name = ASSET_NAMES.get(asset, asset)
        price_str = fetcher.get_formatted_price(asset)
        lines.append(f"{icon} {name} ({asset}) — {price_str}")
        lines.append("")

    lines.append(f"{dir_icon} Señal: {dir_text}")
    lines.append(f"🎯 Confianza: {confidence}%")
    lines.append(f"⏱ Plazo: {timeframe_es}")
    lines.append(f"📊 Score: {score}/100")

    if reasoning:
        lines.append("")
        lines.append(f"💡 {reasoning}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💎 ¿Quieres alertas de más activos?")
    lines.append("👉 Suscríbete en trianio.com")
    lines.append("")
    lines.append(f"⏰ {_now_madrid().strftime('%d/%m/%Y %H:%M')} (Madrid)")

    return "\n".join(lines)


def _send_to_channel(message: str) -> bool:
    """Sends message to the private Telegram channel."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logger.info("Canal de Telegram no configurado (falta TELEGRAM_CHANNEL_ID)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": message,
        }, timeout=10)
        if resp.status_code == 200:
            return True
        else:
            logger.error(f"Error enviando al canal: {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Excepción enviando al canal: {e}")
        return False


def send_daily_channel_alert(events: list) -> bool:
    """
    Called from run_all after each pipeline cycle.
    Sends the FIRST BTC alert of the day that passes quality filters.
    Immediate — no accumulation, no delay.

    Returns True if an alert was sent, False otherwise.
    """
    if not TELEGRAM_CHANNEL_ID:
        return False

    if _already_sent_today():
        return False

    for event in events:
        analysis = event.get("analysis", {})
        if not analysis:
            continue
        if not event.get("prediction_id"):
            continue

        assets = analysis.get("most_affected_assets", [])
        primary_asset = (assets[0].upper() if assets else "")
        if primary_asset != "BTC":
            continue

        event_score = event.get("score", 0)
        event_confidence = analysis.get("confidence", 0)
        if event_score < _MIN_SCORE or event_confidence < _MIN_CONFIDENCE:
            continue

        msg = _format_channel_message(event, analysis)
        if _send_to_channel(msg):
            _log_sent(event, analysis)
            logger.info(f"📢 Alerta BTC enviada al canal: score={event_score} conf={event_confidence}")
            return True

    return False


def send_daily_summary() -> bool:
    """
    Scheduled job (10:00 Madrid) — sends yesterday's results for ALL alerts to the channel.
    Shows total alerts, correct/incorrect breakdown by asset, overall accuracy.
    """
    if not TELEGRAM_CHANNEL_ID:
        return False

    yesterday = (_now_madrid() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_display = (_now_madrid() - timedelta(days=1)).strftime("%d/%m/%Y")

    try:
        engine = get_engine("predictions")
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT asset, direction, outcome, confidence, score
                FROM predictions
                WHERE alerted = 1
                AND DATE(predicted_at) = :yesterday
                ORDER BY score DESC
            """), {"yesterday": yesterday}).fetchall()
    except Exception as e:
        logger.error(f"Error reading predictions for daily summary: {e}")
        return False

    if not rows:
        logger.info("Canal resumen: sin predicciones alertadas ayer — no se envía")
        return False

    total = len(rows)
    correct = sum(1 for r in rows if r[2] == "correct")
    incorrect = sum(1 for r in rows if r[2] == "incorrect")
    pending = sum(1 for r in rows if r[2] == "pending")
    accuracy = round(correct / (correct + incorrect) * 100) if (correct + incorrect) > 0 else 0

    # Breakdown by asset
    assets_seen = {}
    for r in rows:
        asset = (r[0] or "?").upper()
        if asset not in assets_seen:
            assets_seen[asset] = {"correct": 0, "incorrect": 0, "pending": 0}
        if r[2] == "correct":
            assets_seen[asset]["correct"] += 1
        elif r[2] == "incorrect":
            assets_seen[asset]["incorrect"] += 1
        else:
            assets_seen[asset]["pending"] += 1

    # Cumulative all-time accuracy
    try:
        with engine.connect() as conn:
            all_time = conn.execute(text("""
                SELECT outcome FROM predictions
                WHERE alerted = 1
                AND outcome IN ('correct', 'incorrect')
            """)).fetchall()
        total_hist = len(all_time)
        correct_hist = sum(1 for r in all_time if r[0] == "correct")
        accuracy_hist = round(correct_hist / total_hist * 100) if total_hist > 0 else 0
    except Exception:
        total_hist = 0
        accuracy_hist = 0

    lines = []
    lines.append("📊 RESUMEN DEL DÍA — Trianio")
    lines.append(f"📅 {yesterday_display}")
    lines.append("")

    if correct + incorrect > 0:
        if accuracy >= 70:
            lines.append(f"🏆 Precisión ayer: {accuracy}%")
        elif accuracy >= 55:
            lines.append(f"✅ Precisión ayer: {accuracy}%")
        else:
            lines.append(f"📈 Precisión ayer: {accuracy}%")
    lines.append(f"📬 Alertas enviadas: {total}")
    lines.append(f"✅ Correctas: {correct}")
    lines.append(f"❌ Incorrectas: {incorrect}")
    if pending:
        lines.append(f"⏳ Pendientes: {pending}")

    if total_hist > 0:
        lines.append("")
        lines.append(f"📈 Acumulado total: {accuracy_hist}% ({correct_hist}/{total_hist})")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📋 Detalle por activo:")
    lines.append("")

    for asset, stats in sorted(assets_seen.items(), key=lambda x: x[1]["correct"], reverse=True):
        icon = ASSET_ICONS.get(asset, "💹")
        name = ASSET_NAMES.get(asset, asset)
        parts = []
        if stats["correct"]:
            parts.append(f"✅{stats['correct']}")
        if stats["incorrect"]:
            parts.append(f"❌{stats['incorrect']}")
        if stats["pending"]:
            parts.append(f"⏳{stats['pending']}")
        lines.append(f"  {icon} {name}: {' '.join(parts)}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if accuracy >= 65:
        lines.append("🔥 ¡Buen día! Nuestro sistema de IA sigue mejorando.")
    elif accuracy >= 55:
        lines.append("💡 Análisis basado en IA con datos en tiempo real.")
    else:
        lines.append("📡 Seguimos optimizando nuestros modelos de predicción.")

    lines.append("")
    lines.append("💎 Recibe alertas personalizadas de +50 criptomonedas")
    lines.append("👉 Suscríbete en trianio.com")

    msg = "\n".join(lines)

    if _send_to_channel(msg):
        logger.info(f"📊 Resumen diario enviado al canal: {total} alertas, {accuracy}% accuracy")
        return True

    return False


def send_daily_btc_fallback() -> bool:
    """
    Fallback: if no BTC alert was sent today via the pipeline, find the best
    BTC prediction of the day from the DB and send it to the channel.
    Called at 12:00 and 18:00 Madrid time.
    """
    if not TELEGRAM_CHANNEL_ID:
        return False

    if _already_sent_today():
        return False

    _init_channel_log_table()

    try:
        engine = get_engine("predictions")
        with engine.connect() as conn:
            today = _now_madrid().strftime("%Y-%m-%d")
            row = conn.execute(text("""
                SELECT id, asset, direction, confidence, score, reasoning,
                       price_at_prediction, source
                FROM predictions
                WHERE asset = 'BTC'
                  AND alerted = 1
                  AND DATE(predicted_at) = :today
                ORDER BY confidence DESC, score DESC
                LIMIT 1
            """), {"today": today}).fetchone()

        if not row:
            logger.info("Canal fallback: sin predicciones BTC hoy")
            return False

        pred_id, asset, direction, confidence, score, reasoning, price_pred, source = row

        fetcher = AssetPriceFetcher()

        event = {
            "title": f"Señal BTC — {direction.upper()}",
            "score": score,
            "prediction_id": pred_id,
            "source": source or "",
        }
        analysis = {
            "direction": direction,
            "confidence": confidence,
            "most_affected_assets": ["BTC"],
            "reasoning": reasoning or "",
            "timeframe": "hours",
        }

        msg = _format_channel_message(event, analysis)
        if _send_to_channel(msg):
            _log_sent(event, analysis)
            logger.info(f"📢 Canal fallback: alerta BTC enviada (conf={confidence}, score={score})")
            return True

    except Exception as e:
        logger.error(f"Error in channel BTC fallback: {e}")

    return False


def send_channel_btc_result() -> bool:
    """
    Checks if today's BTC channel alert has been validated and sends the result.
    Called periodically (every 30 min). Only sends once per prediction.
    """
    if not TELEGRAM_CHANNEL_ID:
        return False

    try:
        engine_app = get_engine("app")
        engine_pred = get_engine("predictions")

        # Find channel alerts that have a prediction_id but result not yet posted
        with engine_app.connect() as conn:
            pending = conn.execute(text("""
                SELECT prediction_id, sent_date
                FROM channel_alert_log
                WHERE prediction_id IS NOT NULL
                  AND result_posted IS NOT TRUE
                ORDER BY sent_at DESC
                LIMIT 5
            """)).fetchall()

        if not pending:
            return False

        for pred_id, sent_date in pending:
            # Check if the prediction has been validated
            with engine_pred.connect() as conn:
                pred = conn.execute(text("""
                    SELECT asset, direction, outcome, confidence,
                           price_at_prediction, price_at_validation
                    FROM predictions
                    WHERE id = :pid AND outcome IN ('correct', 'incorrect')
                """), {"pid": pred_id}).fetchone()

            if not pred:
                continue

            asset, direction, outcome, confidence, price_pred, price_val = pred

            # Format the result message
            if price_pred and price_val and price_pred > 0:
                move_pct = (price_val - price_pred) / price_pred * 100
            else:
                move_pct = 0

            if outcome == "correct":
                emoji = "✅"
                result_text = "ACERTADA"
                desc = f"El precio se movió {abs(move_pct):.1f}% en la dirección predicha"
            else:
                emoji = "❌"
                result_text = "FALLADA"
                desc = f"El precio no alcanzó el umbral en la dirección predicha ({move_pct:+.1f}%)"

            dir_text = "ALCISTA" if direction in ("up", "bullish") else "BAJISTA"

            lines = []
            lines.append(f"{emoji} RESULTADO — Alerta BTC del {sent_date}")
            lines.append("")
            lines.append(f"📍 Señal: {dir_text} (confianza {confidence}%)")
            lines.append(f"💰 Precio entrada: ${price_pred:.2f}" if price_pred else "")
            lines.append(f"💰 Precio cierre: ${price_val:.2f}" if price_val else "")
            lines.append("")
            lines.append(f"📊 Resultado: {result_text}")
            lines.append(f"💡 {desc}")
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("📈 Historial completo: trianio.com/historial")
            lines.append("💎 Alertas de +50 activos: trianio.com")

            msg = "\n".join(l for l in lines if l is not None)

            if _send_to_channel(msg):
                # Mark result as posted
                with engine_app.connect() as conn:
                    conn.execute(text(
                        "UPDATE channel_alert_log SET result_posted = TRUE WHERE prediction_id = :pid"
                    ), {"pid": pred_id})
                    conn.commit()
                logger.info(f"📢 Resultado BTC enviado al canal: {outcome} (pred {pred_id})")
                return True

    except Exception as e:
        logger.error(f"Error sending channel BTC result: {e}")

    return False
