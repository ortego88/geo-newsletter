"""
newsletter_sender.py — Envía el resumen semanal a todos los suscriptores via Brevo.

Se ejecuta cada domingo a las 11:00 (Madrid) desde el scheduler de run_all.py.
Usa la plantilla templates/newsletter/weekly_digest.html con datos reales de la semana.
"""

import logging
import os
from datetime import datetime, timedelta

import requests
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger("newsletter")

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_LIST_ID = int(os.getenv("BREVO_LIST_ID", "2"))
SENDER_EMAIL = os.getenv("NEWSLETTER_SENDER_EMAIL", "alertas@trianio.com")
SENDER_NAME = "Trianio"


def _get_week_stats() -> dict:
    """Fetches prediction stats for the past 7 days."""
    try:
        from web.db_engine import get_engine
        from sqlalchemy import text

        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with get_engine("predictions").connect() as conn:
            rows = conn.execute(text("""
                SELECT asset, direction, confidence, outcome, reasoning,
                    price_at_prediction, price_at_validation, predicted_at
                FROM predictions
                WHERE predicted_at >= :since AND outcome IN ('correct', 'incorrect')
                ORDER BY predicted_at DESC
            """), {"since": week_ago}).fetchall()

        if not rows:
            return None

        correct = sum(1 for r in rows if r[3] == "correct")
        total = len(rows)
        accuracy = round(correct / total * 100, 1) if total else 0

        asset_stats = {}
        for r in rows:
            asset = r[0]
            if asset not in asset_stats:
                asset_stats[asset] = {"correct": 0, "total": 0}
            asset_stats[asset]["total"] += 1
            if r[3] == "correct":
                asset_stats[asset]["correct"] += 1

        best_asset = max(
            ((a, s["correct"] / s["total"]) for a, s in asset_stats.items() if s["total"] >= 3),
            key=lambda x: x[1],
            default=("—", 0),
        )[0]

        top_predictions = []
        for r in rows[:5]:
            actual_change = ""
            if r[5] and r[6] and r[5] > 0:
                pct = (r[6] - r[5]) / r[5] * 100
                actual_change = f"{pct:+.1f}%"
            top_predictions.append({
                "asset": r[0],
                "direction": r[1],
                "outcome": r[3],
                "reasoning": (r[4] or "")[:80],
                "actual_change": actual_change,
            })

        now = datetime.utcnow()
        week_start = (now - timedelta(days=7)).strftime("%d %b")
        week_end = now.strftime("%d %b %Y")

        return {
            "week_range": f"{week_start} — {week_end}",
            "accuracy_pct": accuracy,
            "correct": correct,
            "total": total,
            "top_predictions": top_predictions,
            "total_alerts": total,
            "best_asset": best_asset,
            "global_accuracy": accuracy,
            "sectors": [],
            "unsubscribe_url": "https://trianio.com/newsletter/unsubscribe",
        }
    except Exception as e:
        logger.error(f"Error getting week stats: {e}")
        return None


def _render_newsletter(stats: dict) -> str:
    """Renders the newsletter HTML template with stats."""
    env = Environment(loader=FileSystemLoader("templates/newsletter"))
    template = env.get_template("weekly_digest.html")
    return template.render(**stats)


def send_weekly_newsletter():
    """Sends the weekly digest to all Brevo list subscribers."""
    if not BREVO_API_KEY:
        logger.warning("BREVO_API_KEY not configured — newsletter not sent")
        return

    stats = _get_week_stats()
    if not stats:
        logger.info("No prediction data for this week — skipping newsletter")
        return

    html_content = _render_newsletter(stats)
    subject = f"Trianio — {stats['accuracy_pct']}% accuracy esta semana ({stats['correct']}/{stats['total']})"

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/emailCampaigns",
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            json={
                "name": f"Weekly Digest {stats['week_range']}",
                "subject": subject,
                "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
                "type": "classic",
                "htmlContent": html_content,
                "recipients": {"listIds": [BREVO_LIST_ID]},
                "scheduledAt": datetime.utcnow().isoformat() + "Z",
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            campaign_id = resp.json().get("id")
            logger.info(f"Newsletter campaign created: ID={campaign_id}")
            _send_campaign(campaign_id)
        else:
            logger.error(f"Brevo campaign creation failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Error sending newsletter: {e}")


def _send_campaign(campaign_id: int):
    """Triggers immediate send of a created campaign."""
    try:
        resp = requests.post(
            f"https://api.brevo.com/v3/emailCampaigns/{campaign_id}/sendNow",
            headers={"api-key": BREVO_API_KEY},
            timeout=10,
        )
        if resp.status_code in (200, 201, 204):
            logger.info(f"Newsletter sent successfully (campaign {campaign_id})")
        else:
            logger.error(f"Brevo send failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Error triggering campaign send: {e}")
