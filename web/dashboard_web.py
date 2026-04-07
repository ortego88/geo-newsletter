from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from web.models import PLANS, AVAILABLE_ASSETS, get_conn
import os
import sqlite3 as _sq

dashboard_bp = Blueprint("dashboard_web", __name__)


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

    # Get recent alerts from predictions DB
    alerts = []
    try:
        pred_db_path = os.getenv("PREDICTIONS_DB_PATH", "data/predictions.db")
        conn2 = _sq.connect(pred_db_path)
        c2 = conn2.cursor()
        c2.execute(
            """SELECT asset, direction, confidence, predicted_at, reasoning
               FROM predictions
               ORDER BY predicted_at DESC
               LIMIT 20"""
        )
        alerts = c2.fetchall()
        conn2.close()
    except Exception:
        import logging
        logging.getLogger("dashboard_web").warning("Could not load predictions", exc_info=True)

    return render_template(
        "dashboard/index.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
        alerts=alerts,
        available_assets=AVAILABLE_ASSETS,
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
