"""
web/admin.py — Dashboard interno de administración.
Acceso protegido por ADMIN_PASSWORD (variable de entorno).
Completamente independiente del sistema de usuarios de la app.
"""
import os
import sqlite3
from datetime import datetime

import pytz
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.services.prediction_tracker import PredictionTracker

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
PREDICTIONS_DB = os.getenv("PREDICTIONS_DB_PATH", "data/predictions.db")

_MADRID_TZ = pytz.timezone("Europe/Madrid")

# Valid fields for ORDER BY (used to prevent SQL injection)
_VALID_SORT_FIELDS = [
    "predicted_at",
    "score",
    "confidence",
    "impact_percent",
    "price_at_prediction",
    "price_at_validation",
]


def _admin_required() -> bool:
    return session.get("admin_logged_in") is True


def _to_madrid(dt_str: str) -> str:
    """Convert an ISO datetime string (UTC) to Madrid local time, formatted as dd/mm/YYYY HH:MM."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt.astimezone(_MADRID_TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt_str


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin.dashboard"))
        flash("Contraseña incorrecta", "error")
    return render_template("admin/login.html")


@admin_bp.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
def dashboard():
    if not _admin_required():
        return redirect(url_for("admin.login"))

    tracker = PredictionTracker(PREDICTIONS_DB)
    stats = tracker.get_accuracy_stats()

    # Pagination & filters
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset = (page - 1) * per_page

    asset_filter = request.args.get("asset", "")
    sort_by = request.args.get("sort", "predicted_at")
    sort_dir = request.args.get("dir", "desc")

    if sort_by not in _VALID_SORT_FIELDS:
        sort_by = "predicted_at"
    sort_sql = f"{sort_by} {'DESC' if sort_dir == 'desc' else 'ASC'}"

    try:
        with sqlite3.connect(PREDICTIONS_DB) as conn:
            conn.row_factory = sqlite3.Row

            where_clause = "WHERE datetime(predicted_at) >= datetime('now', '-24 hours')"
            params: list = []
            if asset_filter:
                where_clause += " AND asset = ?"
                params.append(asset_filter)

            total = conn.execute(
                f"SELECT COUNT(*) FROM predictions {where_clause}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"""SELECT id, title, category, asset, direction, impact_percent, timeframe,
                           confidence, price_at_prediction, price_at_validation, predicted_at,
                           validated_at, outcome, score, source, reasoning
                    FROM predictions {where_clause}
                    ORDER BY {sort_sql}
                    LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()

            assets = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT asset FROM predictions ORDER BY asset"
                ).fetchall()
            ]
    except Exception:
        total = 0
        rows = []
        assets = []

    total_pages = max(1, (total + per_page - 1) // per_page)

    predictions = []
    for row in rows:
        d = dict(row)
        if d.get("price_at_prediction") and d.get("price_at_validation"):
            try:
                d["price_change_pct"] = round(
                    (d["price_at_validation"] - d["price_at_prediction"])
                    / d["price_at_prediction"]
                    * 100,
                    2,
                )
            except ZeroDivisionError:
                d["price_change_pct"] = None
        else:
            d["price_change_pct"] = None

        d["predicted_at_madrid"] = _to_madrid(d.get("predicted_at", ""))
        d["validated_at_madrid"] = _to_madrid(d.get("validated_at", ""))
        predictions.append(d)

    return render_template(
        "admin/dashboard.html",
        predictions=predictions,
        stats=stats,
        assets=assets,
        page=page,
        total_pages=total_pages,
        total=total,
        asset_filter=asset_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        per_page=per_page,
    )
