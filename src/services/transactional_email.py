"""
transactional_email.py — Sends transactional emails via Brevo (welcome, cancellation).
Sender: info@trianio.com
"""

import logging
import os

import requests

logger = logging.getLogger("transactional_email")

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
SENDER = {"name": "Trianio", "email": "info@trianio.com"}


def _send(to_email: str, to_name: str, subject: str, html: str):
    if not BREVO_API_KEY:
        logger.warning("Brevo API key not set — transactional email not sent")
        return
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            json={
                "sender": SENDER,
                "to": [{"email": to_email, "name": to_name}],
                "subject": subject,
                "htmlContent": html,
            },
            timeout=8,
        )
        if resp.status_code == 201:
            logger.info(f"Email '{subject}' sent to {to_email}")
        else:
            logger.warning(f"Brevo error {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        logger.warning(f"Transactional email failed: {e}")


def send_welcome_email(email: str, name: str, plan: str, trial_end: str):
    """Sends welcome email after registration."""
    plan_names = {"basic": "Básica", "premium": "Premium", "pro": "Profesional"}
    plan_display = plan_names.get(plan, plan.capitalize())

    subject = f"Bienvenido a Trianio, {name.split()[0]} 👋"
    html = f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

        <!-- Header -->
        <tr><td style="padding:32px 40px 24px;background:#1e293b;border-radius:16px 16px 0 0;border-bottom:1px solid #334155;">
          <h1 style="margin:0;font-size:24px;font-weight:700;color:#fff;">Trianio</h1>
          <p style="margin:4px 0 0;font-size:13px;color:#94a3b8;">Predicciones crypto con IA</p>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:32px 40px;background:#1e293b;">
          <p style="margin:0 0 16px;font-size:16px;color:#e2e8f0;">Hola <strong>{name.split()[0]}</strong>,</p>
          <p style="margin:0 0 16px;font-size:15px;color:#94a3b8;line-height:1.6;">
            Bienvenido a Trianio. Tu cuenta está lista y tu prueba gratuita de 7 días ha comenzado.
          </p>

          <!-- Plan badge -->
          <div style="background:#0f172a;border:1px solid #334155;border-radius:10px;padding:20px 24px;margin:24px 0;">
            <p style="margin:0;font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Plan activo</p>
            <p style="margin:6px 0 0;font-size:22px;font-weight:700;color:#e8b84b;">{plan_display}</p>
            <p style="margin:4px 0 0;font-size:13px;color:#94a3b8;">Prueba gratuita hasta el <strong style="color:#fff;">{trial_end}</strong></p>
          </div>

          <p style="margin:0 0 16px;font-size:15px;color:#94a3b8;line-height:1.6;">
            A partir de esa fecha, si no cancelas, se cargará automáticamente el importe de tu plan. Puedes cancelar en cualquier momento desde tu panel de control.
          </p>

          <p style="margin:0 0 24px;font-size:15px;color:#94a3b8;line-height:1.6;">
            Para empezar, selecciona las criptomonedas que quieres monitorizar en tu dashboard.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
              <a href="https://trianio.com/dashboard/settings" style="display:inline-block;background:#34d399;color:#064e3b;font-size:14px;font-weight:700;text-decoration:none;padding:14px 32px;border-radius:10px;">
                Seleccionar activos →
              </a>
            </td></tr>
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 40px;background:#1e293b;border-radius:0 0 16px 16px;border-top:1px solid #334155;">
          <p style="margin:0;font-size:12px;color:#64748b;">
            © 2026 Trianio · <a href="https://trianio.com" style="color:#94a3b8;text-decoration:none;">trianio.com</a>
          </p>
          <p style="margin:6px 0 0;font-size:11px;color:#475569;">
            Si tienes dudas escríbenos a <a href="mailto:info@trianio.com" style="color:#94a3b8;">info@trianio.com</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    _send(email, name, subject, html)


def send_cancellation_email(email: str, name: str, access_until: str):
    """Sends cancellation confirmation email."""
    subject = "Tu suscripción a Trianio ha sido cancelada"
    html = f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

        <!-- Header -->
        <tr><td style="padding:32px 40px 24px;background:#1e293b;border-radius:16px 16px 0 0;border-bottom:1px solid #334155;">
          <h1 style="margin:0;font-size:24px;font-weight:700;color:#fff;">Trianio</h1>
          <p style="margin:4px 0 0;font-size:13px;color:#94a3b8;">Confirmación de cancelación</p>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:32px 40px;background:#1e293b;">
          <p style="margin:0 0 16px;font-size:16px;color:#e2e8f0;">Hola <strong>{name.split()[0]}</strong>,</p>
          <p style="margin:0 0 16px;font-size:15px;color:#94a3b8;line-height:1.6;">
            Hemos procesado la cancelación de tu suscripción. No se realizará ningún cargo más.
          </p>

          <div style="background:#0f172a;border:1px solid #334155;border-radius:10px;padding:20px 24px;margin:24px 0;">
            <p style="margin:0;font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;">Acceso hasta</p>
            <p style="margin:6px 0 0;font-size:22px;font-weight:700;color:#fff;">{access_until}</p>
            <p style="margin:4px 0 0;font-size:13px;color:#94a3b8;">Puedes seguir usando Trianio hasta esa fecha</p>
          </div>

          <p style="margin:0 0 24px;font-size:15px;color:#94a3b8;line-height:1.6;">
            Si cambias de opinión antes de esa fecha, puedes reactivar tu suscripción desde tu panel de control.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
              <a href="https://trianio.com/dashboard/subscription" style="display:inline-block;background:#334155;color:#e2e8f0;font-size:14px;font-weight:600;text-decoration:none;padding:14px 32px;border-radius:10px;">
                Ver mi suscripción
              </a>
            </td></tr>
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 40px;background:#1e293b;border-radius:0 0 16px 16px;border-top:1px solid #334155;">
          <p style="margin:0;font-size:12px;color:#64748b;">
            © 2026 Trianio · <a href="https://trianio.com" style="color:#94a3b8;text-decoration:none;">trianio.com</a>
          </p>
          <p style="margin:6px 0 0;font-size:11px;color:#475569;">
            ¿Algo fue mal? Escríbenos a <a href="mailto:info@trianio.com" style="color:#94a3b8;">info@trianio.com</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    _send(email, name, subject, html)
