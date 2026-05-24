"""
web/telegram_bot.py — Webhook endpoint for the Telegram bot.

Handles:
- /start command: links Telegram user to their Trianio account
- /start <token>: links via unique token generated in dashboard settings
- Sends channel invite link to active subscribers

Setup:
  1. Set webhook: POST https://api.telegram.org/bot<TOKEN>/setWebhook
     Body: {"url": "https://your-domain.up.railway.app/telegram/webhook"}
  2. Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
"""

import hashlib
import hmac
import logging
import os

import requests
from flask import Blueprint, request, jsonify
from sqlalchemy import text

from web.db_engine import get_engine

logger = logging.getLogger("telegram_bot")

telegram_bp = Blueprint("telegram_bot", __name__, url_prefix="/telegram")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")


def _reply(chat_id: int, text_msg: str):
    """Sends a reply message to a Telegram chat."""
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text_msg,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logger.warning(f"Error replying to {chat_id}: {e}")


def _create_invite_link() -> str | None:
    """Creates a single-use invite link for the private channel."""
    if not BOT_TOKEN or not CHANNEL_ID:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"
    try:
        resp = requests.post(url, json={
            "chat_id": CHANNEL_ID,
            "member_limit": 1,
            "creates_join_request": False,
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["invite_link"]
    except Exception as e:
        logger.warning(f"Error creating invite link: {e}")
    return None


def _link_user_by_token(chat_id: int, user_id: int, token: str) -> bool:
    """Links a Telegram chat_id to a user via their linking token."""
    try:
        with get_engine("app").connect() as conn:
            row = conn.execute(text(
                "SELECT id FROM users WHERE id = :uid"
            ), {"uid": user_id}).fetchone()
            if not row:
                return False

            conn.execute(text(
                "UPDATE users SET telegram_chat_id = :chat_id WHERE id = :uid"
            ), {"chat_id": str(chat_id), "uid": user_id})
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error linking user {user_id}: {e}")
        return False


def _find_user_by_chat_id(chat_id: int) -> dict | None:
    """Finds a user by their telegram_chat_id."""
    try:
        with get_engine("app").connect() as conn:
            row = conn.execute(text(
                "SELECT u.id, u.email, s.status FROM users u "
                "LEFT JOIN subscriptions s ON s.user_id = u.id "
                "WHERE u.telegram_chat_id = :cid"
            ), {"cid": str(chat_id)}).fetchone()
            if row:
                return {"id": row[0], "email": row[1], "status": row[2]}
    except Exception:
        pass
    return None


def _generate_link_token(user_id: int) -> str:
    """Generates a deterministic token for linking (user_id + secret)."""
    secret = os.getenv("SECRET_KEY", "dev-secret")
    raw = f"{user_id}:{secret}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _handle_start(chat_id: int, username: str, args: str):
    """Handles /start command with optional linking token."""

    # Check if already linked
    existing = _find_user_by_chat_id(chat_id)
    if existing:
        status = existing.get("status", "none")
        if status in ("active", "trial"):
            # Already linked and active — send invite if channel configured
            msg = "✅ Tu cuenta de Telegram ya está vinculada a Trianio.\n\n"
            msg += "Recibirás alertas personalizadas directamente aquí."
            if CHANNEL_ID:
                invite = _create_invite_link()
                if invite:
                    msg += f"\n\n🔔 Accede al canal de alertas diarias:\n{invite}"
            _reply(chat_id, msg)
        else:
            _reply(chat_id, (
                "⚠️ Tu cuenta está vinculada pero tu suscripción no está activa.\n\n"
                "Activa tu suscripción en la web para recibir alertas."
            ))
        return

    # Try to link via token: /start <user_id>_<token>
    if args:
        parts = args.split("_", 1)
        if len(parts) == 2:
            try:
                user_id = int(parts[0])
                token = parts[1]
                expected = _generate_link_token(user_id)
                if hmac.compare_digest(token, expected):
                    if _link_user_by_token(chat_id, user_id, token):
                        msg = "✅ ¡Cuenta vinculada correctamente!\n\n"
                        msg += "A partir de ahora recibirás alertas personalizadas aquí."
                        if CHANNEL_ID:
                            invite = _create_invite_link()
                            if invite:
                                msg += f"\n\n🔔 Únete al canal de alertas diarias:\n{invite}"
                        _reply(chat_id, msg)
                        logger.info(f"User {user_id} linked to chat {chat_id}")
                        return
            except (ValueError, TypeError):
                pass

    # Not linked and no valid token — show instructions
    _reply(chat_id, (
        "👋 ¡Bienvenido a Trianio Bot!\n\n"
        "Para recibir alertas crypto, vincula tu cuenta:\n\n"
        "1️⃣ Inicia sesión en trianio.com\n"
        "2️⃣ Ve a Configuración\n"
        "3️⃣ Pulsa \"Vincular Telegram\"\n\n"
        "Recibirás un enlace personalizado para completar la vinculación."
    ))


@telegram_bp.route("/webhook", methods=["POST"])
def webhook():
    """Receives updates from Telegram Bot API."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": True})

    message = data.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message.get("chat", {}).get("id")
    text_msg = message.get("text", "")
    username = message.get("from", {}).get("username", "")

    if not chat_id:
        return jsonify({"ok": True})

    if text_msg.startswith("/start"):
        args = text_msg[7:].strip() if len(text_msg) > 6 else ""
        _handle_start(chat_id, username, args)

    elif text_msg == "/status":
        user = _find_user_by_chat_id(chat_id)
        if user:
            status_text = {
                "active": "✅ Activa",
                "trial": "🆓 Período de prueba",
            }.get(user["status"], "❌ Inactiva")
            _reply(chat_id, f"📊 Estado de tu suscripción: {status_text}")
        else:
            _reply(chat_id, "No tienes cuenta vinculada. Usa /start para comenzar.")

    elif text_msg == "/invite":
        user = _find_user_by_chat_id(chat_id)
        if user and user.get("status") in ("active", "trial"):
            if CHANNEL_ID:
                invite = _create_invite_link()
                if invite:
                    _reply(chat_id, f"🔔 Enlace al canal de alertas diarias:\n{invite}")
                else:
                    _reply(chat_id, "⚠️ No se pudo generar el enlace. Inténtalo más tarde.")
            else:
                _reply(chat_id, "El canal de alertas no está configurado aún.")
        else:
            _reply(chat_id, "Necesitas una suscripción activa para acceder al canal.")

    return jsonify({"ok": True})
