"""
src/services/email_sender.py — Envío de emails HTML.

Variables de entorno:
  SMTP_HOST       — Servidor SMTP (ej: smtp.gmail.com)
  SMTP_PORT       — Puerto SMTP (default: 587)
  SMTP_USER       — Usuario SMTP
  SMTP_PASSWORD   — Contraseña SMTP o App Password
  SMTP_FROM_NAME  — Nombre del remitente (default: GEO-NEWSLETTER)
  SMTP_FROM_EMAIL — Email del remitente
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("email_sender")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "GEO-NEWSLETTER")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")


def is_email_configured() -> bool:
    """Retorna True si todas las credenciales SMTP están configuradas."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM_EMAIL)


def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """
    Envía un email HTML via SMTP.
    Retorna True si tuvo éxito, False si no está configurado o hay error.
    """
    if not is_email_configured():
        logger.info("Email no configurado (faltan SMTP_HOST, SMTP_USER, SMTP_PASSWORD o SMTP_FROM_EMAIL)")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = to_email

        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())

        logger.info(f"Email enviado a {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Error enviando email a {to_email}: {e}")
        return False
