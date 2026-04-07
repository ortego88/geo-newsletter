"""
src/services/weekly_digest.py — Envío del resumen semanal por email.

Envía cada domingo a las 10:00 AM (hora de Madrid) un email con el resumen
de alertas de la semana a los usuarios con plan premium o pro.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from collections import Counter

import pytz
from jinja2 import Environment, FileSystemLoader

from src.services.email_sender import send_email, is_email_configured

logger = logging.getLogger("weekly_digest")

MADRID_TZ = pytz.timezone("Europe/Madrid")

# Path to the templates directory (relative to project root)
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "templates")


def get_weekly_events(db_path: str, days: int = 7) -> list:
    """
    Obtiene los eventos de los últimos `days` días desde la BD de predicciones.
    Devuelve una lista de dicts con los datos del evento.
    """
    from web.db_engine import get_engine
    from sqlalchemy import text

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        with get_engine("predictions").connect() as conn:
            rows = conn.execute(
                text("""
                SELECT id, event_id, title, category, asset, direction,
                       impact_percent, timeframe, confidence, reasoning,
                       predicted_at, outcome, score, source
                FROM predictions
                WHERE predicted_at >= :cutoff
                ORDER BY score DESC
                """),
                {"cutoff": cutoff},
            ).mappings().fetchall()
    except Exception as e:
        logger.error(f"Error consultando predicciones: {e}")
        return []

    events = []
    for row in rows:
        assets = [row["asset"]] if row["asset"] else []
        events.append({
            "event_id": row["event_id"],
            "title": row["title"] or "",
            "category": row["category"] or "",
            "score": row["score"] or 0,
            "impact_score": row["score"] or 0,
            "analysis": {
                "direction": row["direction"] or "neutral",
                "most_affected_assets": assets,
                "market_impact_percent": row["impact_percent"] or 0,
                "timeframe": row["timeframe"] or "",
                "confidence": row["confidence"] or 0,
                "reasoning": row["reasoning"] or "",
            },
            "predicted_at": row["predicted_at"],
            "outcome": row["outcome"],
        })

    return events


def get_premium_users(app_db_path: str) -> list:
    """
    Obtiene los usuarios con plan premium o pro y estado active o trial desde app.db.
    Devuelve una lista de dicts con id, email, name, plan.
    """
    from web.db_engine import get_engine
    from sqlalchemy import text

    try:
        with get_engine("app").connect() as conn:
            rows = conn.execute(
                text("""
                SELECT u.id, u.email, u.name, s.plan, s.status
                FROM users u
                JOIN subscriptions s ON s.user_id = u.id
                WHERE s.plan IN ('premium', 'pro')
                  AND s.status IN ('active', 'trial')
                  AND u.is_active = 1
                ORDER BY u.id
                """),
            ).mappings().fetchall()
    except Exception as e:
        logger.error(f"Error consultando usuarios premium: {e}")
        return []

    return [
        {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "plan": row["plan"],
            "status": row["status"],
        }
        for row in rows
    ]


def _build_digest_context(user: dict, events: list) -> dict:
    """Construye el contexto para el template del resumen semanal."""
    now_madrid = datetime.now(MADRID_TZ)
    week_end = now_madrid.strftime("%d/%m/%Y")
    week_start = (now_madrid - timedelta(days=7)).strftime("%d/%m/%Y")

    total_alerts = len(events)
    critical_alerts = sum(1 for e in events if (e.get("score") or 0) >= 85)
    high_alerts = sum(1 for e in events if 70 <= (e.get("score") or 0) < 85)

    # Count asset mentions
    asset_counter: Counter = Counter()
    for event in events:
        analysis = event.get("analysis") or {}
        for asset in analysis.get("most_affected_assets", []):
            if asset:
                asset_counter[asset.upper()] += 1
    top_assets = [asset for asset, _ in asset_counter.most_common(5)]

    # Only include top 10 events
    top_events = events[:10]

    return {
        "user_name": user.get("name", "Usuario"),
        "week_start": week_start,
        "week_end": week_end,
        "events": top_events,
        "total_alerts": total_alerts,
        "critical_alerts": critical_alerts,
        "high_alerts": high_alerts,
        "top_assets": top_assets,
        "plan": user.get("plan", "premium"),
    }


def send_weekly_digest(predictions_db: str, app_db: str) -> int:
    """
    Función principal: obtiene eventos y usuarios, renderiza el template y envía emails.
    Retorna el número de emails enviados correctamente.
    """
    if not is_email_configured():
        logger.info("Email no configurado — resumen semanal desactivado")
        return 0

    logger.info("📧 Iniciando envío del resumen semanal...")

    events = get_weekly_events(predictions_db)
    logger.info(f"Eventos de la semana: {len(events)}")

    users = get_premium_users(app_db)
    logger.info(f"Usuarios premium/pro: {len(users)}")

    if not users:
        logger.info("No hay usuarios premium/pro para enviar el resumen")
        return 0

    # Set up Jinja2 environment
    templates_dir = os.path.abspath(_TEMPLATES_DIR)
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=True,
    )

    try:
        template = env.get_template("email/weekly_digest.html")
    except Exception as e:
        logger.error(f"Error cargando template de email: {e}")
        return 0

    sent = 0
    now_madrid = datetime.now(MADRID_TZ)
    week_end_str = now_madrid.strftime("%d/%m/%Y")

    for user in users:
        try:
            context = _build_digest_context(user, events)
            html_body = template.render(**context)

            subject = f"🌍 Tu resumen semanal de alertas geopolíticas — {week_end_str}"
            if send_email(user["email"], subject, html_body):
                sent += 1
                logger.info(f"✅ Resumen enviado a {user['email']} ({user['plan']})")
            else:
                logger.warning(f"No se pudo enviar el resumen a {user['email']}")
        except Exception as e:
            logger.error(f"Error enviando resumen a {user.get('email', '?')}: {e}")

    logger.info(f"📤 Resumen semanal: {sent}/{len(users)} emails enviados")
    return sent
