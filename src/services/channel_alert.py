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

_MIN_SCORE = 70
_MIN_CONFIDENCE = 70

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
                sent_at TEXT NOT NULL
            )
        """))
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
    try:
        with get_engine("app").connect() as conn:
            conn.execute(text("""
                INSERT INTO channel_alert_log (sent_date, event_title, asset, score, confidence, sent_at)
                VALUES (:date, :title, :asset, :score, :conf, :sent_at)
            """), {
                "date": today,
                "title": (event.get("title") or "")[:200],
                "asset": asset,
                "score": int(event.get("score", 0)),
                "conf": int(analysis.get("confidence", 0)),
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
    Scheduled job (10:00 Madrid) — sends yesterday's channel alert results.
    Only shows results for alerts that were sent to the public channel (from channel_alert_log),
    not all predictions from the system.
    """
    if not TELEGRAM_CHANNEL_ID:
        return False

    yesterday = (_now_madrid() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_display = (_now_madrid() - timedelta(days=1)).strftime("%d/%m/%Y")

    # Get channel alerts sent yesterday from channel_alert_log
    try:
        _init_channel_log_table()
        with get_engine("app").connect() as conn:
            channel_rows = conn.execute(text("""
                SELECT event_title, asset, score, confidence
                FROM channel_alert_log
                WHERE sent_date = :yesterday
            """), {"yesterday": yesterday}).fetchall()
    except Exception as e:
        logger.error(f"Error reading channel_alert_log for summary: {e}")
        return False

    if not channel_rows:
        logger.info("Canal resumen: sin alertas de canal ayer — no se envía")
        return False

    # Get prediction outcomes for those channel alerts
    try:
        engine = get_engine("predictions")
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT asset, direction, outcome, confidence, score
                FROM predictions
                WHERE UPPER(asset) = 'BTC'
                AND alerted = 1
                AND DATE(predicted_at) = :yesterday
                ORDER BY score DESC
                LIMIT :limit
            """), {"yesterday": yesterday, "limit": len(channel_rows)}).fetchall()
    except Exception as e:
        logger.error(f"Error reading predictions for daily summary: {e}")
        return False

    if not rows:
        logger.info("Canal resumen: sin predicciones BTC alertadas ayer — no se envía")
        return False

    total = len(rows)
    correct = sum(1 for r in rows if r[2] == "correct")
    incorrect = sum(1 for r in rows if r[2] == "incorrect")
    pending = sum(1 for r in rows if r[2] == "pending")
    accuracy = round(correct / (correct + incorrect) * 100) if (correct + incorrect) > 0 else 0

    # Get cumulative channel stats (all time from channel_alert_log)
    try:
        engine_pred = get_engine("predictions")
        with engine_pred.connect() as conn:
            all_channel = conn.execute(text("""
                SELECT outcome FROM predictions
                WHERE UPPER(asset) = 'BTC'
                AND alerted = 1
                AND outcome IN ('correct', 'incorrect')
            """)).fetchall()
        total_hist = len(all_channel)
        correct_hist = sum(1 for r in all_channel if r[0] == "correct")
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
    lines.append(f"📬 Alertas BTC enviadas: {total}")
    lines.append(f"✅ Correctas: {correct}")
    lines.append(f"❌ Incorrectas: {incorrect}")
    if pending:
        lines.append(f"⏳ Pendientes: {pending}")

    if total_hist > 0:
        lines.append("")
        lines.append(f"📈 Acumulado canal: {accuracy_hist}% ({correct_hist}/{total_hist})")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if accuracy >= 65:
        lines.append("🔥 ¡Buen día para BTC! Nuestro sistema de IA sigue mejorando.")
    elif accuracy >= 55:
        lines.append("💡 Análisis basado en IA con datos en tiempo real.")
    else:
        lines.append("📡 Seguimos optimizando nuestros modelos de predicción.")

    lines.append("")
    lines.append("💎 Recibe alertas de +65 criptomonedas con planes desde 14,99€")
    lines.append("👉 Suscríbete en trianio.com")

    msg = "\n".join(lines)

    if _send_to_channel(msg):
        logger.info(f"📊 Resumen diario enviado al canal: {total} alertas BTC, {accuracy}% accuracy")
        return True

    return False
