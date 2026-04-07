"""
web/admin.py — Dashboard interno de administración.
Acceso protegido por ADMIN_PASSWORD (variable de entorno).
Completamente independiente del sistema de usuarios de la app.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

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
from src.services.alert_formatter import ASSET_NAMES

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-in-production")
PREDICTIONS_DB = os.getenv("PREDICTIONS_DB_PATH", "data/predictions.db")
RECENT_ARTICLES_DB = os.getenv("RECENT_ARTICLES_DB_PATH", "data/recent_articles.db")
SEEN_ARTICLES_FILE = os.getenv("SEEN_ARTICLES_FILE_PATH", "data/seen_articles.txt")

_MADRID_TZ = pytz.timezone("Europe/Madrid")

# Allowlist mapping of sort parameter values to SQL column names (prevents SQL injection)
_SORT_FIELD_MAP = {
    "predicted_at": "predicted_at",
    "score": "score",
    "confidence": "confidence",
    "impact_percent": "impact_percent",
    "price_at_prediction": "price_at_prediction",
    "price_at_validation": "price_at_validation",
}


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
        password = request.form.get("password", "")
        # Login only succeeds when ADMIN_PASSWORD is set and matches
        if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
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

    stats = {"total": 0, "correct": 0, "incorrect": 0, "accuracy_pct": 0.0,
             "high_confidence_accuracy": 0.0, "pending": 0}

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

            # Accuracy stats scoped to the same 24h window + asset filter
            outcome_rows = conn.execute(
                f"SELECT outcome, confidence FROM predictions {where_clause} AND outcome != 'pending'",
                params,
            ).fetchall()
            pending_count = conn.execute(
                f"SELECT COUNT(*) FROM predictions {where_clause} AND outcome = 'pending'",
                params,
            ).fetchone()[0]

            if outcome_rows:
                _total = len(outcome_rows)
                _correct = sum(1 for r in outcome_rows if r[0] == "correct")
                high_conf = [r for r in outcome_rows if (r[1] or 0) >= 70]
                hc_correct = sum(1 for r in high_conf if r[0] == "correct")
                stats = {
                    "total": _total,
                    "correct": _correct,
                    "incorrect": _total - _correct,
                    "accuracy_pct": round(_correct / _total * 100, 1) if _total else 0.0,
                    "high_confidence_accuracy": round(hc_correct / len(high_conf) * 100, 1) if high_conf else 0.0,
                    "pending": pending_count,
                }
            else:
                stats["pending"] = pending_count

            rows = conn.execute(
                f"""SELECT id, title, category, asset, direction, impact_percent, timeframe,
                           confidence, price_at_prediction, price_at_validation, predicted_at,
                           validated_at, outcome, score, source, reasoning
                    FROM predictions {where_clause}
                    ORDER BY {sort_col} {sort_order}
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
        asset_names=ASSET_NAMES,
        page=page,
        total_pages=total_pages,
        total=total,
        asset_filter=asset_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        per_page=per_page,
    )


@admin_bp.route("/reset-predictions", methods=["GET", "POST"])
def reset_predictions():
    if not _admin_required():
        return redirect(url_for("admin.login"))

    if request.method == "POST":
        try:
            # Borrar predicciones
            with sqlite3.connect(PREDICTIONS_DB) as conn:
                conn.execute("DELETE FROM predictions")
                conn.commit()

            # Borrar caché de deduplicación (artículos recientes)
            if Path(RECENT_ARTICLES_DB).exists():
                with sqlite3.connect(RECENT_ARTICLES_DB) as conn:
                    conn.execute("DELETE FROM recent_articles")
                    conn.commit()

            # Borrar hashes de deduplicación de nivel 1 (seen_articles.txt)
            seen_file = Path(SEEN_ARTICLES_FILE)
            if seen_file.exists():
                seen_file.write_text("")

            flash(
                "✅ Histórico de predicciones y noticias borrado correctamente. "
                "La base de datos está limpia.",
                "success",
            )
        except Exception as e:
            flash(f"❌ Error al resetear la base de datos: {str(e)}", "danger")
        return redirect(url_for("admin.dashboard"))

    # GET: mostrar página de confirmación con recuento de registros
    num_predictions = 0
    num_recent_articles = 0
    try:
        with sqlite3.connect(PREDICTIONS_DB) as conn:
            row = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()
            num_predictions = row[0] if row else 0
    except Exception:
        pass
    try:
        if Path(RECENT_ARTICLES_DB).exists():
            with sqlite3.connect(RECENT_ARTICLES_DB) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM recent_articles"
                ).fetchone()
                num_recent_articles = row[0] if row else 0
    except Exception:
        pass

    return render_template(
        "admin/reset_predictions.html",
        num_predictions=num_predictions,
        num_recent_articles=num_recent_articles,
    )
