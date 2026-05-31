"""
web/admin.py — Dashboard interno de administración.
Acceso protegido por ADMIN_PASSWORD (variable de entorno).

CAMBIOS v2:
- Las estadísticas de accuracy excluyen outcome='neutral' del cómputo,
  consistente con prediction_tracker.get_accuracy_stats().
- Se añade 'neutral' al contexto del template para mostrarlo en la UI.
"""
import os
from datetime import datetime
from pathlib import Path

import pytz
from sqlalchemy import text
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
RECENT_ARTICLES_DB = os.getenv("RECENT_ARTICLES_DB_PATH", "data/recent_articles.db")
SEEN_ARTICLES_FILE = os.getenv("SEEN_ARTICLES_FILE_PATH", "data/seen_articles.txt")

_MADRID_TZ = pytz.timezone("Europe/Madrid")

# Allowlist de columnas para ORDER BY (previene SQL injection)
_SORT_FIELD_MAP = {
    "predicted_at": "predicted_at",
    "score": "score",
    "confidence": "confidence",
    "impact_percent": "impact_percent",
    "price_at_prediction": "price_at_prediction",
    "price_at_validation": "price_at_validation",
}

from web.db_engine import get_engine as _get_engine

def _pred_conn():
    return _get_engine("predictions").connect()


def _admin_required() -> bool:
    return session.get("admin_logged_in") is True


def _to_madrid(dt_str: str) -> str:
    """Convert an ISO datetime string (UTC) to Madrid local time, formatted as dd/mm/YYYY HH:MM."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt.astimezone(_MADRID_TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(dt_str)[:16]


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
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

    stats = {
        "total": 0, "correct": 0, "incorrect": 0,
        "accuracy_pct": 0.0, "high_confidence_accuracy": 0.0,
        "pending": 0, "neutral": 0,
    }

    try:
        with _pred_conn() as conn:
            where_clause = "WHERE 1=1"
            q_params: dict = {}
            if asset_filter:
                where_clause += " AND asset = :asset"
                q_params["asset"] = asset_filter

            total = conn.execute(
                text(f"SELECT COUNT(*) FROM predictions {where_clause}"), q_params
            ).fetchone()[0]

            # Stats: excluir 'neutral' y 'pending' del cómputo de accuracy
            outcome_rows = conn.execute(
                text(f"""
                    SELECT outcome, confidence
                    FROM predictions {where_clause}
                    AND outcome NOT IN ('pending', 'neutral')
                """),
                q_params,
            ).fetchall()

            pending_count = conn.execute(
                text(f"SELECT COUNT(*) FROM predictions {where_clause} AND outcome = 'pending'"),
                q_params,
            ).fetchone()[0]

            neutral_count = conn.execute(
                text(f"SELECT COUNT(*) FROM predictions {where_clause} AND outcome = 'neutral'"),
                q_params,
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
                    "neutral": neutral_count,
                }
            else:
                stats["pending"] = pending_count
                stats["neutral"] = neutral_count

            rows = conn.execute(
                text(f"""
                    SELECT id, title, category, asset, direction, impact_percent, timeframe,
                           confidence, price_at_prediction, price_at_validation, predicted_at,
                           validated_at, outcome, score, source, reasoning
                    FROM predictions {where_clause}
                    ORDER BY {sort_col} {sort_order}
                    LIMIT :limit OFFSET :offset
                """),
                {**q_params, "limit": per_page, "offset": offset},
            ).mappings().fetchall()

            assets = [
                r[0]
                for r in conn.execute(
                    text("SELECT DISTINCT asset FROM predictions ORDER BY asset")
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
        price_initial = d.get("price_at_prediction") or 0
        price_validated = d.get("price_at_validation")
        if price_initial and price_initial > 0 and price_validated:
            try:
                d["price_change_pct"] = round(
                    (price_validated - price_initial) / price_initial * 100, 2
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
            with _pred_conn() as conn:
                conn.execute(text("DELETE FROM predictions"))
                conn.commit()

            import sqlite3 as _sq3
            if Path(RECENT_ARTICLES_DB).exists():
                with _sq3.connect(RECENT_ARTICLES_DB) as conn:
                    conn.execute("DELETE FROM recent_articles")
                    conn.commit()

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

    num_predictions = 0
    num_recent_articles = 0
    try:
        with _pred_conn() as conn:
            row = conn.execute(text("SELECT COUNT(*) FROM predictions")).fetchone()
            num_predictions = row[0] if row else 0
    except Exception:
        pass
    try:
        import sqlite3 as _sq3
        if Path(RECENT_ARTICLES_DB).exists():
            with _sq3.connect(RECENT_ARTICLES_DB) as conn:
                row = conn.execute("SELECT COUNT(*) FROM recent_articles").fetchone()
                num_recent_articles = row[0] if row else 0
    except Exception:
        pass

    return render_template(
        "admin/reset_predictions.html",
        num_predictions=num_predictions,
        num_recent_articles=num_recent_articles,
    )


@admin_bp.route("/seed-users", methods=["GET", "POST"])
def seed_users():
    if not _admin_required():
        return redirect(url_for("admin.login"))

    from werkzeug.security import generate_password_hash
    from web.models import init_db

    SHARED_PASSWORD = "Trianio2026!"
    TEST_USERS = [
        {"email": f"demo{i}@trianio.com", "name": f"Demo User {i}"}
        for i in range(1, 11)
    ]

    if request.method == "POST":
        init_db()
        pw_hash = generate_password_hash(SHARED_PASSWORD)
        now = datetime.utcnow().isoformat()
        created = 0
        skipped = 0

        try:
            from web.db_engine import get_engine as _get_app_engine
            with _get_app_engine("app").connect() as conn:
                for u in TEST_USERS:
                    existing = conn.execute(
                        text("SELECT id FROM users WHERE email = :email"),
                        {"email": u["email"]},
                    ).fetchone()
                    if existing:
                        skipped += 1
                        continue

                    result = conn.execute(
                        text(
                            "INSERT INTO users (email, password_hash, name, language, created_at, is_active) "
                            "VALUES (:email, :pw, :name, 'es', :now, 1) RETURNING id"
                        ),
                        {"email": u["email"], "pw": pw_hash, "name": u["name"], "now": now},
                    )
                    user_id = result.fetchone()[0]
                    conn.execute(
                        text(
                            "INSERT INTO subscriptions (user_id, plan, billing_cycle, status, created_at, updated_at) "
                            "VALUES (:uid, 'pro', 'monthly', 'active', :now, :now)"
                        ),
                        {"uid": user_id, "now": now},
                    )
                    created += 1
                conn.commit()

            flash(f"✅ {created} usuarios creados, {skipped} ya existían. Password: {SHARED_PASSWORD}", "success")
        except Exception as e:
            flash(f"❌ Error: {e}", "danger")

        return redirect(url_for("admin.seed_users"))

    # GET — show current state
    existing_users = []
    try:
        from web.db_engine import get_engine as _get_app_engine
        with _get_app_engine("app").connect() as conn:
            for u in TEST_USERS:
                row = conn.execute(
                    text("SELECT id, email, created_at FROM users WHERE email = :email"),
                    {"email": u["email"]},
                ).fetchone()
                existing_users.append({"email": u["email"], "exists": row is not None, "id": row[0] if row else None})
    except Exception:
        pass

    html = f"""
    <!DOCTYPE html>
    <html><head><title>Seed Test Users</title>
    <style>body{{font-family:monospace;background:#1e293b;color:#e2e8f0;padding:2rem}}
    .btn{{background:#10b981;color:white;padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:14px}}
    .btn:hover{{background:#059669}} table{{border-collapse:collapse;margin:1rem 0}} td,th{{padding:6px 12px;border:1px solid #475569}}
    .exists{{color:#10b981}} .missing{{color:#94a3b8}}</style></head>
    <body><h1>Seed Test Users</h1>
    <p>Password compartida: <strong>{SHARED_PASSWORD}</strong></p>
    <p>Plan: <strong>Profesional (pro)</strong> — activo, sin trial</p>
    <table><tr><th>Email</th><th>Estado</th></tr>
    {''.join(f'<tr><td>{u["email"]}</td><td class="{"exists" if u["exists"] else "missing"}">{"✅ Existe (id=" + str(u["id"]) + ")" if u["exists"] else "⏳ Pendiente"}</td></tr>' for u in existing_users)}
    </table>
    <form method="POST" style="margin-top:1rem">
    <button type="submit" class="btn">Crear usuarios faltantes</button>
    </form>
    <br><a href="{url_for('admin.dashboard')}" style="color:#60a5fa">← Volver al admin</a>
    </body></html>"""
    return html
