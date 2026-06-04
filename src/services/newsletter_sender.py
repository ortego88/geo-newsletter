"""
newsletter_sender.py — Envía el resumen semanal a todos los suscriptores via Brevo.

Se ejecuta cada lunes a las 8:00 (Madrid) desde el scheduler de run_all.py.
Enfoque positivo: mejores señales, pérdidas evitadas, precisión por dirección.
"""

import logging
import os
from datetime import datetime, timedelta

import requests
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger("newsletter")

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_LIST_ID = int(os.getenv("BREVO_LIST_ID", "2"))
SENDER_EMAIL = os.getenv("NEWSLETTER_SENDER_EMAIL", "newsletter@trianio.com")
SENDER_NAME = "Trianio"


def _get_week_stats() -> dict:
    """Fetches prediction stats for the past 7 days with positive framing."""
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
        global_accuracy = round(correct / total * 100, 1) if total else 0

        # Accuracy by direction
        up_rows = [r for r in rows if r[1] == "up"]
        down_rows = [r for r in rows if r[1] == "down"]
        correct_up = sum(1 for r in up_rows if r[3] == "correct")
        correct_down = sum(1 for r in down_rows if r[3] == "correct")
        accuracy_up = round(correct_up / len(up_rows) * 100) if up_rows else 0
        accuracy_down = round(correct_down / len(down_rows) * 100) if down_rows else 0

        # Best UP signal (biggest correct gain)
        best_up_asset = "—"
        best_up_pct = "0.0"
        best_up_reason = ""
        for r in rows:
            if r[1] == "up" and r[3] == "correct" and r[5] and r[6] and r[5] > 0:
                gain = (r[6] - r[5]) / r[5] * 100
                if gain > float(best_up_pct):
                    best_up_pct = f"{gain:.1f}"
                    best_up_asset = r[0]
                    best_up_reason = (r[4] or "")[:80]

        # Best DOWN signal (biggest correct loss avoided)
        loss_avoided_asset = "—"
        loss_avoided_pct = "0.0"
        for r in rows:
            if r[1] == "down" and r[3] == "correct" and r[5] and r[6] and r[5] > 0:
                drop = (r[5] - r[6]) / r[5] * 100
                if drop > float(loss_avoided_pct):
                    loss_avoided_pct = f"{drop:.1f}"
                    loss_avoided_asset = r[0]

        # Asset to watch: best accuracy with >= 5 predictions this week
        asset_stats = {}
        for r in rows:
            a = r[0]
            if a not in asset_stats:
                asset_stats[a] = {"correct": 0, "total": 0}
            asset_stats[a]["total"] += 1
            if r[3] == "correct":
                asset_stats[a]["correct"] += 1

        watch_asset = "BTC"
        watch_accuracy = 0
        watch_reason = "El activo más seguido del mercado"
        for a, s in asset_stats.items():
            if s["total"] >= 5:
                acc = s["correct"] / s["total"] * 100
                if acc > watch_accuracy:
                    watch_accuracy = acc
                    watch_asset = a
                    watch_reason = f"{s['correct']}/{s['total']} predicciones correctas esta semana"

        assets_covered = len(set(r[0] for r in rows))

        now = datetime.utcnow()
        week_start = (now - timedelta(days=7)).strftime("%d %b")
        week_end = now.strftime("%d %b %Y")

        return {
            "week_range": f"{week_start} — {week_end}",
            "best_up_asset": best_up_asset,
            "best_up_pct": best_up_pct,
            "best_up_reason": best_up_reason,
            "loss_avoided_asset": loss_avoided_asset,
            "loss_avoided_pct": loss_avoided_pct,
            "accuracy_up": accuracy_up,
            "correct_up": correct_up,
            "total_up": len(up_rows),
            "accuracy_down": accuracy_down,
            "correct_down": correct_down,
            "total_down": len(down_rows),
            "watch_asset": watch_asset,
            "watch_accuracy": round(watch_accuracy),
            "watch_reason": watch_reason,
            "total_alerts": total,
            "global_accuracy": global_accuracy,
            "assets_covered": assets_covered,
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
    subject = f"Esta semana: {stats['global_accuracy']}% de acierto y {stats['best_up_asset']} +{stats['best_up_pct']}%"

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


def send_test_newsletter(to_email: str):
    """Sends a test newsletter to a single email (for preview)."""
    stats = _get_week_stats()
    if not stats:
        return "No data available"

    html_content = _render_newsletter(stats)
    subject = f"[TEST] Esta semana: {stats['global_accuracy']}% de acierto y {stats['best_up_asset']} +{stats['best_up_pct']}%"

    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        json={
            "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
        },
        timeout=15,
    )
    return f"{resp.status_code}: {resp.text[:100]}"
