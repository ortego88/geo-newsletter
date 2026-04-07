"""
src/services/whatsapp_sender.py — Envío de mensajes vía WhatsApp (Twilio).

Variables de entorno requeridas (cuando estén disponibles):
  TWILIO_ACCOUNT_SID  — SID de la cuenta Twilio
  TWILIO_AUTH_TOKEN   — Token de autenticación Twilio
  TWILIO_WHATSAPP_FROM — Número de origen (ej: whatsapp:+14155238886)
  WHATSAPP_TO         — Número destino (ej: whatsapp:+34600000000)
"""
import logging
import os

logger = logging.getLogger("whatsapp")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
WHATSAPP_TO = os.getenv("WHATSAPP_TO")


def is_whatsapp_configured() -> bool:
    """Retorna True si todas las credenciales de WhatsApp están configuradas."""
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and WHATSAPP_TO)


def send_whatsapp(message: str) -> bool:
    """
    Envía un mensaje de WhatsApp via Twilio.
    Retorna True si tuvo éxito, False si no está configurado o hay error.
    Si Twilio no está instalado, lo avisa pero no falla.
    """
    if not is_whatsapp_configured():
        logger.info("WhatsApp no configurado (faltan TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN o WHATSAPP_TO)")
        return False

    try:
        from twilio.rest import Client
    except ImportError:
        logger.warning("twilio no está instalado. Ejecuta: pip install twilio")
        return False

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_FROM,
            to=WHATSAPP_TO,
        )
        logger.info(f"Mensaje WhatsApp enviado. SID: {msg.sid}")
        return True
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")
        return False
