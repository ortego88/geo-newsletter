from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from web.models import PLANS, AVAILABLE_ASSETS, get_conn
import logging
import os
import sqlite3 as _sq
from datetime import datetime
import pytz

_logger = logging.getLogger("dashboard_web")

dashboard_bp = Blueprint("dashboard_web", __name__)

_PREDICTIONS_DB_PATH = os.getenv("PREDICTIONS_DB_PATH", "data/predictions.db")
_MADRID_TZ = pytz.timezone("Europe/Madrid")

_VALID_SORTS = ["predicted_at", "score", "confidence", "impact_percent", "price_at_prediction", "price_at_validation"]

# Allowlist mapping of sort parameter values to SQL column names (prevents SQL injection)
_SORT_FIELD_MAP = {s: s for s in _VALID_SORTS}


def _get_predictions_conn():
    """Return a connection to the predictions SQLite database."""
    return _sq.connect(_PREDICTIONS_DB_PATH)


def _to_madrid_time(dt_str: str) -> str:
    """Convert an ISO datetime string (UTC) to Madrid time formatted as dd/mm HH:MM."""
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt.astimezone(_MADRID_TZ).strftime("%d/%m %H:%M")
    except Exception:
        return dt_str[:16]


def _require_active_subscription():
    sub = current_user.get_subscription()
    if not sub or sub["status"] not in ("active", "trial"):
        flash("Necesitas una suscripción activa para acceder a esta sección", "warning")
        return redirect(url_for("billing.pricing"))
    return None


@dashboard_bp.route("/dashboard")
@login_required
def index():
    redirect_resp = _require_active_subscription()
    if redirect_resp:
        return redirect_resp

    sub = current_user.get_subscription()
    plan_config = PLANS.get(sub["plan"], PLANS["basic"])

    # Pagination & filters
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset = (page - 1) * per_page
    asset_filter = request.args.get("asset", "")
    sort_by = request.args.get("sort", "predicted_at")
    sort_dir = request.args.get("dir", "desc")

    if sort_by not in _SORT_FIELD_MAP:
        sort_by = "predicted_at"
    sort_col = _SORT_FIELD_MAP[sort_by]
    sort_order = "DESC" if sort_dir == "desc" else "ASC"

    # Get recent alerts from predictions DB (last 24h)
    alerts = []
    total_alerts = 0
    total_pages = 1
    try:
        conn2 = _get_predictions_conn()
        c2 = conn2.cursor()

        where = "WHERE datetime(predicted_at) >= datetime('now', '-24 hours')"
        params: list = []
        if asset_filter:
            where += " AND asset = ?"
            params.append(asset_filter)

        total_alerts = c2.execute(
            f"SELECT COUNT(*) FROM predictions {where}", params
        ).fetchone()[0]
        total_pages = max(1, (total_alerts + per_page - 1) // per_page)

        c2.execute(
            f"""SELECT asset, direction, confidence, predicted_at, reasoning,
                       score, impact_percent, price_at_prediction, price_at_validation, outcome, title
                FROM predictions {where}
                ORDER BY {sort_col} {sort_order}
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        )
        alerts_raw = c2.fetchall()
        conn2.close()
    except _sq.Error:
        _logger.warning("Could not load predictions", exc_info=True)
        alerts_raw = []

    # Convert dates to Madrid time and compute price variation
    processed_alerts = []
    for row in alerts_raw:
        row = list(row)
        row[3] = _to_madrid_time(row[3])  # predicted_at → Madrid time
        price_initial = row[7]   # price_at_prediction
        price_validated = row[8]  # price_at_validation
        if price_initial and price_validated and price_initial > 0:
            variation = round((price_validated - price_initial) / price_initial * 100, 2)
        else:
            variation = None
        row.append(variation)  # index 11
        processed_alerts.append(tuple(row))
    alerts = processed_alerts

    # Get accuracy stats (scoped to last 24h and optional asset filter)
    accuracy_stats = {"total": 0, "correct": 0, "incorrect": 0, "accuracy_pct": 0.0, "high_confidence_accuracy": 0.0, "pending": 0}
    try:
        conn2 = _get_predictions_conn()
        c2 = conn2.cursor()

        stats_where = "WHERE datetime(predicted_at) >= datetime('now', '-24 hours')"
        stats_params: list = []
        if asset_filter:
            stats_where += " AND asset = ?"
            stats_params.append(asset_filter)

        c2.execute(
            f"SELECT outcome, confidence FROM predictions {stats_where} AND outcome != 'pending'",
            stats_params,
        )
        outcomes = c2.fetchall()

        # Count pending in same window
        pending = c2.execute(
            f"SELECT COUNT(*) FROM predictions {stats_where} AND outcome = 'pending'",
            stats_params,
        ).fetchone()[0]

        conn2.close()
        if outcomes:
            total = len(outcomes)
            correct = sum(1 for r in outcomes if r[0] == "correct")
            # High-confidence accuracy (confidence >= 70%)
            high_conf = [r for r in outcomes if (r[1] or 0) >= 70]
            hc_correct = sum(1 for r in high_conf if r[0] == "correct")
            hc_accuracy = round(hc_correct / len(high_conf) * 100, 1) if high_conf else 0.0
            accuracy_stats = {
                "total": total,
                "correct": correct,
                "incorrect": total - correct,
                "accuracy_pct": round(correct / total * 100, 1) if total > 0 else 0.0,
                "high_confidence_accuracy": hc_accuracy,
                "pending": pending,
            }
        else:
            accuracy_stats["pending"] = pending
    except _sq.Error:
        _logger.warning("Could not load accuracy stats", exc_info=True)

    return render_template(
        "dashboard/index.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
        alerts=alerts,
        accuracy_stats=accuracy_stats,
        available_assets=AVAILABLE_ASSETS,
        page=page,
        total_pages=total_pages,
        total_alerts=total_alerts,
        asset_filter=asset_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        per_page=per_page,
    )


@dashboard_bp.route("/dashboard/settings", methods=["GET", "POST"])
@login_required
def settings():
    redirect_resp = _require_active_subscription()
    if redirect_resp:
        return redirect_resp

    sub = current_user.get_subscription()
    plan_config = PLANS.get(sub["plan"], PLANS["basic"])

    if request.method == "POST":
        selected_assets = request.form.getlist("assets")
        max_assets = plan_config["max_assets"]
        if max_assets != -1 and len(selected_assets) > max_assets:
            flash(f"Tu plan solo permite seleccionar {max_assets} activo(s)", "error")
        else:
            language = request.form.get("language", "es")
            telegram_id = request.form.get("telegram_chat_id", "").strip()
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                "UPDATE subscriptions SET selected_assets=? WHERE user_id=?",
                (",".join(selected_assets), current_user.id),
            )
            c.execute(
                "UPDATE users SET language=?, telegram_chat_id=? WHERE id=?",
                (language, telegram_id, current_user.id),
            )
            conn.commit()
            conn.close()
            flash("Configuración guardada", "success")
            return redirect(url_for("dashboard_web.settings"))

    selected = [a for a in (sub.get("selected_assets") or []) if a]
    max_assets = plan_config["max_assets"]
    # Assets that are not selected and would exceed the plan limit are locked
    if max_assets != -1 and len(selected) >= max_assets:
        locked_symbols = {a["symbol"] for a in AVAILABLE_ASSETS if a["symbol"] not in selected}
    else:
        locked_symbols = set()

    return render_template(
        "dashboard/settings.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
        available_assets=AVAILABLE_ASSETS,
        locked_symbols=locked_symbols,
    )


@dashboard_bp.route("/dashboard/subscription")
@login_required
def subscription():
    redirect_resp = _require_active_subscription()
    if redirect_resp:
        return redirect_resp
    sub = current_user.get_subscription()
    plan_config = PLANS.get(sub["plan"], PLANS["basic"]) if sub else None
    return render_template(
        "dashboard/subscription.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
    )


@dashboard_bp.route("/dashboard/set-language", methods=["POST"])
@login_required
def set_language():
    data = request.get_json(silent=True) or {}
    lang = data.get("language", "es")
    VALID = {'es', 'en', 'fr', 'de', 'it', 'pt', 'zh', 'ar'}
    if lang not in VALID:
        lang = 'es'
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET language=? WHERE id=?", (lang, current_user.id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "language": lang})
