"""
src/services/telegram_sender.py — Envío de mensajes a Telegram.
"""
import logging
import os

import requests

logger = logging.getLogger("telegram")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_subscribed_assets() -> set:
    """
    Lee TELEGRAM_ALERT_ASSETS del entorno.
    Si está vacío → retorna set vacío (significa "todos").
    """
    raw = os.getenv("TELEGRAM_ALERT_ASSETS", "").strip()
    if not raw:
        return set()
    return {a.strip().upper() for a in raw.split(",") if a.strip()}


def send_telegram(message: str, chat_id: str | None = None) -> bool:
    """Envía un mensaje a Telegram. Retorna True si tuvo éxito.

    Si se proporciona `chat_id`, se usa ese destinatario en lugar del
    TELEGRAM_CHAT_ID global (útil para envíos per-usuario).
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram no configurado (falta BOT_TOKEN)")
        return False

    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not target_chat:
        logger.warning("Telegram no configurado (falta CHAT_ID)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        resp = requests.post(
            url,
            data={
                "chat_id": target_chat,
                "text": message,
            },
            timeout=10,
        )

        if resp.status_code == 200:
            logger.info("Mensaje enviado a Telegram correctamente")
            return True
        else:
            logger.error(f"Error Telegram: {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Excepción enviando a Telegram: {e}")
        return False
