"""
transactional_email.py — Sends transactional emails via Brevo (welcome, cancellation, abandoned checkout).
Sender: info@trianio.com
"""

import logging
import os
from datetime import datetime, timezone, timedelta

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


ADMIN_EMAIL = "info@trianio.com"


def send_new_subscriber_notification(user_email: str, user_name: str, plan: str, cycle: str):
    """Notifies admin when a new user completes checkout."""
    plan_names = {"basic": "Básico", "premium": "Premium", "pro": "Profesional"}
    plan_display = plan_names.get(plan, plan)
    cycle_display = "anual" if cycle == "yearly" else "mensual"

    subject = f"🎉 Nuevo suscriptor: {user_name} ({plan_display})"
    html = f"""
<div style="font-family:sans-serif;padding:20px;background:#1e293b;color:#e2e8f0;border-radius:12px;">
  <h2 style="color:#34d399;margin-top:0;">Nuevo suscriptor en Trianio</h2>
  <table style="border-collapse:collapse;width:100%;">
    <tr><td style="padding:8px 0;color:#94a3b8;">Nombre:</td><td style="padding:8px 0;color:#fff;font-weight:bold;">{user_name}</td></tr>
    <tr><td style="padding:8px 0;color:#94a3b8;">Email:</td><td style="padding:8px 0;color:#fff;">{user_email}</td></tr>
    <tr><td style="padding:8px 0;color:#94a3b8;">Plan:</td><td style="padding:8px 0;color:#e8b84b;font-weight:bold;">{plan_display} ({cycle_display})</td></tr>
    <tr><td style="padding:8px 0;color:#94a3b8;">Fecha:</td><td style="padding:8px 0;color:#fff;">{datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")} UTC</td></tr>
  </table>
  <p style="margin-top:16px;color:#94a3b8;font-size:13px;">Trial de 7 días activado. El cobro se realizará si no cancela antes.</p>
</div>
"""
    _send(ADMIN_EMAIL, "Trianio Admin", subject, html)


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


def send_abandoned_checkout_email(email: str, name: str, hours_since: int):
    """Sends a reminder to users who registered but didn't complete payment."""
    first_name = name.split()[0] if name else ""

    if hours_since <= 6:
        subject = f"{first_name}, tu prueba gratuita te está esperando"
        headline = "Solo te falta un paso"
        body_text = (
            "Vimos que creaste tu cuenta pero no llegaste a configurar tu método de pago. "
            "Tu prueba de 7 días no empezará hasta que completes este paso — y no se te cobrará nada durante ese tiempo."
        )
        cta_text = "Completar registro →"
    else:
        subject = f"{first_name}, no te quedes sin tus 7 días gratis"
        headline = "Te quedan alertas por descubrir"
        body_text = (
            "Ya tienes cuenta en Trianio pero aún no has activado tu prueba gratuita. "
            "Añade tu método de pago (no se cobra nada en 7 días) y empieza a recibir alertas crypto antes que el mercado se mueva."
        )
        cta_text = "Activar prueba gratis →"

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
          <p style="margin:0 0 16px;font-size:16px;color:#e2e8f0;">Hola <strong>{first_name}</strong>,</p>

          <h2 style="margin:0 0 16px;font-size:20px;color:#fff;">{headline}</h2>

          <p style="margin:0 0 24px;font-size:15px;color:#94a3b8;line-height:1.6;">
            {body_text}
          </p>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
              <a href="https://trianio.com/checkout/trial" style="display:inline-block;background:#34d399;color:#064e3b;font-size:14px;font-weight:700;text-decoration:none;padding:14px 32px;border-radius:10px;">
                {cta_text}
              </a>
            </td></tr>
          </table>

          <div style="background:#0f172a;border:1px solid #334155;border-radius:10px;padding:20px 24px;margin:24px 0;">
            <p style="margin:0;font-size:13px;color:#94a3b8;line-height:1.6;">
              <strong style="color:#e8b84b;">Recuerda:</strong> No se realiza ningún cargo durante los 7 días de prueba. Puedes cancelar en cualquier momento.
            </p>
          </div>
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


def check_abandoned_checkouts():
    """
    Checks for users who registered but never completed Stripe payment.
    Sends reminder at 3h and 24h after registration.
    """
    from sqlalchemy import text
    from web.db_engine import get_engine

    now = datetime.now(timezone.utc)
    three_hours_ago = (now - timedelta(hours=3)).isoformat()
    four_hours_ago = (now - timedelta(hours=4)).isoformat()
    twenty_four_hours_ago = (now - timedelta(hours=24)).isoformat()
    twenty_five_hours_ago = (now - timedelta(hours=25)).isoformat()

    try:
        engine = get_engine("app")
        with engine.connect() as conn:
            # Users registered 3-4h ago without Stripe subscription
            users_3h = conn.execute(text("""
                SELECT u.id, u.email, u.name
                FROM users u
                LEFT JOIN subscriptions s ON s.user_id = u.id
                WHERE u.created_at BETWEEN :start AND :end
                  AND u.is_active = 1
                  AND (s.stripe_subscription_id IS NULL OR s.stripe_subscription_id = '')
                  AND u.id NOT IN (
                      SELECT user_id FROM abandoned_checkout_log
                      WHERE reminder_type = '3h'
                  )
            """), {"start": four_hours_ago, "end": three_hours_ago}).fetchall()

            # Users registered 24-25h ago without Stripe subscription
            users_24h = conn.execute(text("""
                SELECT u.id, u.email, u.name
                FROM users u
                LEFT JOIN subscriptions s ON s.user_id = u.id
                WHERE u.created_at BETWEEN :start AND :end
                  AND u.is_active = 1
                  AND (s.stripe_subscription_id IS NULL OR s.stripe_subscription_id = '')
                  AND u.id NOT IN (
                      SELECT user_id FROM abandoned_checkout_log
                      WHERE reminder_type = '24h'
                  )
            """), {"start": twenty_five_hours_ago, "end": twenty_four_hours_ago}).fetchall()

        sent = 0
        for user_id, email, name in users_3h:
            send_abandoned_checkout_email(email, name or "", 3)
            _log_abandoned_reminder(user_id, "3h")
            sent += 1

        for user_id, email, name in users_24h:
            send_abandoned_checkout_email(email, name or "", 24)
            _log_abandoned_reminder(user_id, "24h")
            sent += 1

        if sent:
            logger.info(f"📧 Abandoned checkout: sent {sent} reminders ({len(users_3h)} at 3h, {len(users_24h)} at 24h)")

    except Exception as e:
        logger.error(f"Error in abandoned checkout check: {e}")


def _log_abandoned_reminder(user_id: int, reminder_type: str):
    """Logs that a reminder was sent to avoid duplicates."""
    from sqlalchemy import text
    from web.db_engine import get_engine

    try:
        with get_engine("app").connect() as conn:
            conn.execute(text("""
                INSERT INTO abandoned_checkout_log (user_id, reminder_type, sent_at)
                VALUES (:uid, :type, :now)
            """), {
                "uid": user_id,
                "type": reminder_type,
                "now": datetime.now(timezone.utc).isoformat(),
            })
            conn.commit()
    except Exception as e:
        logger.warning(f"Error logging abandoned checkout reminder: {e}")


def init_abandoned_checkout_table():
    """Creates the abandoned_checkout_log table if it doesn't exist."""
    from sqlalchemy import text
    from web.db_engine import get_engine

    try:
        with get_engine("app").connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS abandoned_checkout_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    reminder_type TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )
            """))
            conn.commit()
    except Exception as e:
        logger.warning(f"Error creating abandoned_checkout_log table: {e}")


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
