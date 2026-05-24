"""
Canal privado de Telegram — 1 alerta diaria con la señal de mayor confianza.

Flujo:
- Cada ciclo del pipeline evalúa si ya se envió la alerta del día.
- Si no se ha enviado, selecciona el evento con mayor score × confidence.
- Solo se envía si score >= 70 y confidence >= 70 (señal fuerte).
- Se registra en la BD para no repetir en el mismo día.

Variables de entorno:
  TELEGRAM_BOT_TOKEN      — token del bot (compartido con alertas individuales)
  TELEGRAM_CHANNEL_ID     — ID del canal privado (ej: -1001234567890)
"""

import logging
import os
from datetime import datetime

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
    """Returns True if we already sent the daily channel alert."""
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
    """Formats the daily channel alert — premium look, concise."""
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
            logger.info("✅ Alerta diaria enviada al canal privado")
            return True
        else:
            logger.error(f"Error enviando al canal: {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Excepción enviando al canal: {e}")
        return False


def send_daily_channel_alert(events: list) -> bool:
    """
    Main entry point — called from run_all after pipeline produces events.
    Selects the best event and sends it to the private channel (max 1/day).

    Returns True if an alert was sent, False otherwise.
    """
    if not TELEGRAM_CHANNEL_ID:
        return False

    if _already_sent_today():
        logger.debug("Alerta de canal ya enviada hoy — omitiendo")
        return False

    # Filter to high-quality events only
    candidates = []
    for event in events:
        analysis = event.get("analysis", {})
        if not analysis:
            continue
        if not event.get("prediction_id"):
            continue
        event_score = event.get("score", 0)
        event_confidence = analysis.get("confidence", 0)
        if event_score >= _MIN_SCORE and event_confidence >= _MIN_CONFIDENCE:
            candidates.append(event)

    if not candidates:
        logger.debug(f"Sin candidatos para canal (requiere score>={_MIN_SCORE}, conf>={_MIN_CONFIDENCE})")
        return False

    # Pick the best: score × confidence
    best = max(candidates, key=lambda e: e.get("score", 0) * e.get("analysis", {}).get("confidence", 0))
    analysis = best["analysis"]

    msg = _format_channel_message(best, analysis)
    if _send_to_channel(msg):
        _log_sent(best, analysis)
        return True

    return False
