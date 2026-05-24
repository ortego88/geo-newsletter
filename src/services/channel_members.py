"""
Gestión de miembros del canal privado de Telegram.

Funciones:
- Generar invite links únicos para nuevos suscriptores.
- Expulsar usuarios cuya suscripción ha expirado.
- Verificación periódica de membresía.

Variables de entorno:
  TELEGRAM_BOT_TOKEN      — token del bot
  TELEGRAM_CHANNEL_ID     — ID del canal privado (ej: -1001234567890)
"""

import logging
import os

import requests
from sqlalchemy import text

from web.db_engine import get_engine

logger = logging.getLogger("channel_members")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _bot_request(method: str, params: dict = None) -> dict | None:
    """Makes a request to Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return None
    try:
        resp = requests.post(f"{_API_BASE}/{method}", json=params or {}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data.get("result")
        logger.warning(f"Telegram API {method} error: {data.get('description', '')}")
        return None
    except Exception as e:
        logger.error(f"Telegram API {method} exception: {e}")
        return None


def create_invite_link(user_id: int = None) -> str | None:
    """
    Creates a single-use invite link to the private channel.
    If user_id is provided, creates a member-limited link.
    """
    params = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "member_limit": 1,
        "creates_join_request": False,
    }
    result = _bot_request("createChatInviteLink", params)
    if result:
        link = result.get("invite_link")
        logger.info(f"Invite link creado para canal: {link[:30]}...")
        return link
    return None


def kick_member(telegram_user_id: int) -> bool:
    """Removes a user from the channel (ban + unban to allow re-joining later)."""
    result = _bot_request("banChatMember", {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "user_id": telegram_user_id,
    })
    if result:
        # Unban immediately so they can re-join if they resubscribe
        _bot_request("unbanChatMember", {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "user_id": telegram_user_id,
            "only_if_banned": True,
        })
        logger.info(f"Usuario {telegram_user_id} expulsado del canal")
        return True
    return False


def sync_channel_members():
    """
    Periodic job: checks all users with telegram_chat_id and ensures:
    - Active subscribers remain in the channel.
    - Expired subscribers are kicked from the channel.

    telegram_chat_id for DMs is the same numeric user ID that Telegram
    uses for group/channel membership management.
    """
    if not TELEGRAM_CHANNEL_ID:
        return

    try:
        with get_engine("app").connect() as conn:
            expired = conn.execute(text("""
                SELECT u.telegram_chat_id
                FROM users u
                JOIN subscriptions s ON s.user_id = u.id
                WHERE u.telegram_chat_id IS NOT NULL
                  AND u.telegram_chat_id != ''
                  AND s.status NOT IN ('active', 'trial')
            """)).fetchall()

            kicked = 0
            for row in expired:
                tg_id = row[0]
                if tg_id:
                    if kick_member(int(tg_id)):
                        kicked += 1

            if kicked:
                logger.info(f"Canal: {kicked} usuarios expirados eliminados")

    except Exception as e:
        logger.warning(f"Error syncing channel members: {e}")
