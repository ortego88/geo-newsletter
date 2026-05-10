"""
web/dashboard_web.py — Dashboard web del usuario.

CAMBIOS v2:
- Las estadísticas de accuracy ahora excluyen outcome='neutral' del cómputo de
  correct/incorrect, consistente con el nuevo sistema de validación por niveles
  de prediction_tracker.py.
- Se añade el campo 'neutral' al contexto del template para mostrarlo en la UI.
- Fix menor: protección contra price_at_prediction = 0 en el cálculo de price_change_pct.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import text
from web.models import PLANS, AVAILABLE_ASSETS, get_conn
from web.db_engine import get_engine
from src.services.alert_formatter import ASSET_NAMES
from src.services.market_config import get_assets_by_type, get_asset_type
import logging
import os
from datetime import datetime, timedelta
import pytz

_logger = logging.getLogger("dashboard_web")

dashboard_bp = Blueprint("dashboard_web", __name__)

_MADRID_TZ = pytz.timezone("Europe/Madrid")

_VALID_SORTS = [
    "predicted_at", "score", "confidence", "impact_percent",
    "price_at_prediction", "price_at_validation",
]
_SORT_FIELD_MAP = {s: s for s in _VALID_SORTS}


def _get_predictions_conn():
    return get_engine("predictions").connect()


def _to_madrid_time(dt_str: str) -> str:
    """Convert UTC ISO datetime string to Madrid local time formatted as dd/mm HH:MM."""
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt.astimezone(_MADRID_TZ).strftime("%d/%m %H:%M")
    except Exception:
        return str(dt_str)[:16]


def _user_has_payment_method(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT 1 FROM payment_methods WHERE user_id = :uid LIMIT 1"),
            {"uid": user_id},
        ).fetchone()
    return bool(row)


def _require_active_subscription():
    """
    Valida que el usuario tenga suscripción activa Y que haya completado el flujo completo:
    1. Suscripción activa o trial
    2. Método de pago guardado
    3. Activos seleccionados
    """
    sub = current_user.get_subscription()

    # Paso 1: Verificar suscripción activa
    if not sub or sub["status"] not in ("active", "trial"):
        flash("Necesitas una suscripción activa para acceder a esta sección", "warning")
        return redirect(url_for("billing.pricing"))

    # Paso 2: Verificar método de pago
    if not _user_has_payment_method(current_user.id):
        flash("Añade tu método de pago para continuar", "warning")
        return redirect(url_for("billing.checkout_trial", plan=sub["plan"], next_step="select_assets"))

    # Paso 3: Verificar activos seleccionados
    user_selected_assets = [a for a in (sub.get("selected_assets") or []) if a]
    if not user_selected_assets:
        flash("Selecciona al menos un activo para empezar a recibir alertas", "info")
        return redirect(url_for("dashboard_web.settings", next_step="select_assets"))

    return None


@dashboard_bp.route("/dashboard")
@login_required
def index():
    redirect_resp = _require_active_subscription()
    if redirect_resp:
        return redirect_resp

    sub = current_user.get_subscription()
    plan_config = PLANS.get(sub["plan"], PLANS["basic"])

    user_selected_assets = set(a for a in (sub.get("selected_assets") or []) if a)

    # Paginación y filtros
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset = (page - 1) * per_page
    asset_filter = request.args.get("asset", "").strip()
    outcome_filter = request.args.get("outcome", "").strip()
    asset_type_filter = request.args.get("asset_type", "").strip()
    time_filter = request.args.get("time_filter", "").strip()
    sort_by = request.args.get("sort", "predicted_at")
    sort_dir = request.args.get("dir", "desc")

    if sort_by not in _SORT_FIELD_MAP:
        sort_by = "predicted_at"
    sort_col = _SORT_FIELD_MAP[sort_by]
    sort_order = "DESC" if sort_dir == "desc" else "ASC"

    alerts = []
    total_alerts = 0
    total_pages = 1

    try:
        with _get_predictions_conn() as conn2:
            where = "WHERE 1=1"
            extra_params: dict = {}

            # Time filter
            if time_filter == "24h":
                cutoff = datetime.utcnow() - timedelta(hours=24)
                where += " AND predicted_at >= :time_cutoff"
                extra_params["time_cutoff"] = cutoff.isoformat()
            elif time_filter == "7d":
                cutoff = datetime.utcnow() - timedelta(days=7)
                where += " AND predicted_at >= :time_cutoff"
                extra_params["time_cutoff"] = cutoff.isoformat()
            elif time_filter == "30d":
                cutoff = datetime.utcnow() - timedelta(days=30)
                where += " AND predicted_at >= :time_cutoff"
                extra_params["time_cutoff"] = cutoff.isoformat()

            if user_selected_assets:
                asset_list = ",".join([f"'{a}'" for a in user_selected_assets])
                where += f" AND asset IN ({asset_list})"

            if asset_filter:
                where += " AND asset = :asset"
                extra_params["asset"] = asset_filter

            if asset_type_filter and not asset_filter:
                # get_assets_by_type devuelve set → convertir a list
                type_assets = list(get_assets_by_type(asset_type_filter))
                if type_assets:
                    asset_list = ",".join([f"'{a}'" for a in type_assets])
                    where += f" AND asset IN ({asset_list})"

            if outcome_filter in ("correct", "incorrect", "pending", "neutral"):
                where += " AND outcome = :outcome"
                extra_params["outcome"] = outcome_filter

            total_alerts = conn2.execute(
                text(f"SELECT COUNT(*) FROM predictions {where}"), extra_params
            ).fetchone()[0]
            total_pages = max(1, (total_alerts + per_page - 1) // per_page)

            alerts_raw = conn2.execute(
                text(f"""
                    SELECT id, title, category, asset, direction, impact_percent, timeframe,
                           confidence, price_at_prediction, price_at_validation, predicted_at,
                           validated_at, outcome, score, source, reasoning
                    FROM predictions {where}
                    ORDER BY {sort_col} {sort_order}
                    LIMIT :limit OFFSET :offset
                """),
                {**extra_params, "limit": per_page, "offset": offset},
            ).mappings().fetchall()

    except Exception:
        _logger.warning("Could not load predictions", exc_info=True)
        alerts_raw = []

    for row in alerts_raw:
        d = dict(row)
        d["predicted_at_madrid"] = _to_madrid_time(d.get("predicted_at", ""))
        d["validated_at_madrid"] = _to_madrid_time(d.get("validated_at", ""))
        price_initial = d.get("price_at_prediction") or 0
        price_validated = d.get("price_at_validation")
        if price_initial and price_initial > 0 and price_validated:
            d["price_change_pct"] = round(
                (price_validated - price_initial) / price_initial * 100, 2
            )
        else:
            d["price_change_pct"] = None
        alerts.append(d)

    # ── Estadísticas de accuracy ────────────────────────────────────────────
    # IMPORTANTE: 'neutral' se excluye del cómputo de correct/incorrect.
    # Solo cuentan las predicciones donde el mercado se movió de forma significativa.
    accuracy_stats = {
        "total": 0, "correct": 0, "incorrect": 0,
        "accuracy_pct": 0.0, "high_confidence_accuracy": 0.0,
        "pending": 0, "neutral": 0,
    }
    try:
        with _get_predictions_conn() as conn2:
            stats_where = "WHERE 1=1"
            stats_params: dict = {}

            # Time filter for stats
            if time_filter == "24h":
                cutoff = datetime.utcnow() - timedelta(hours=24)
                stats_where += " AND predicted_at >= :time_cutoff"
                stats_params["time_cutoff"] = cutoff.isoformat()
            elif time_filter == "7d":
                cutoff = datetime.utcnow() - timedelta(days=7)
                stats_where += " AND predicted_at >= :time_cutoff"
                stats_params["time_cutoff"] = cutoff.isoformat()
            elif time_filter == "30d":
                cutoff = datetime.utcnow() - timedelta(days=30)
                stats_where += " AND predicted_at >= :time_cutoff"
                stats_params["time_cutoff"] = cutoff.isoformat()

            if user_selected_assets:
                asset_list = ",".join([f"'{a}'" for a in user_selected_assets])
                stats_where += f" AND asset IN ({asset_list})"

            if asset_filter:
                stats_where += " AND asset = :asset"
                stats_params["asset"] = asset_filter

            if asset_type_filter and not asset_filter:
                type_assets = list(get_assets_by_type(asset_type_filter))
                if type_assets:
                    asset_list = ",".join([f"'{a}'" for a in type_assets])
                    stats_where += f" AND asset IN ({asset_list})"

            if outcome_filter in ("correct", "incorrect", "pending", "neutral"):
                stats_where += " AND outcome = :outcome"
                stats_params["outcome"] = outcome_filter

            # Obtener todos los outcomes para las stats
            rows = conn2.execute(
                text(f"SELECT outcome, confidence FROM predictions {stats_where}"),
                stats_params,
            ).fetchall()

        pending = sum(1 for r in rows if r[0] == "pending")
        neutral = sum(1 for r in rows if r[0] == "neutral")
        # Solo correct + incorrect entran en el cálculo de accuracy
        outcomes = [r for r in rows if r[0] not in ("pending", "neutral")]

        total = len(outcomes)
        correct = sum(1 for r in outcomes if r[0] == "correct")
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
            "neutral": neutral,
        }
    except Exception:
        _logger.warning("Could not load accuracy stats", exc_info=True)

    asset_type_map = {}
    for asset in AVAILABLE_ASSETS:
        asset_type_map[asset["symbol"]] = get_asset_type(asset["symbol"])

    return render_template(
        "dashboard/index.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
        alerts=alerts,
        accuracy_stats=accuracy_stats,
        available_assets=AVAILABLE_ASSETS,
        asset_type_map=asset_type_map,
        asset_names=ASSET_NAMES,
        page=page,
        total_pages=total_pages,
        total_alerts=total_alerts,
        asset_filter=asset_filter,
        asset_type_filter=asset_type_filter,
        outcome_filter=outcome_filter,
        time_filter=time_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        per_page=per_page,
        history_label="Histórico completo",
    )


@dashboard_bp.route("/dashboard/settings", methods=["GET", "POST"])
@login_required
def settings():
    # Para settings, solo validamos suscripción y método de pago, no activos
    # (porque es aquí donde los seleccionan por primera vez)
    sub = current_user.get_subscription()
    if not sub or sub["status"] not in ("active", "trial"):
        flash("Necesitas una suscripción activa para acceder a esta sección", "warning")
        return redirect(url_for("billing.pricing"))

    # Si no tiene método de pago, redirigir a checkout
    if not _user_has_payment_method(current_user.id):
        flash("Añade tu método de pago antes de seleccionar activos", "warning")
        return redirect(url_for("billing.checkout_trial", plan=sub["plan"], next_step="select_assets"))

    plan_config = PLANS.get(sub["plan"], PLANS["basic"])

    if request.method == "POST":
        selected_assets = request.form.getlist("assets")
        max_assets = plan_config["max_assets"]

        if not selected_assets:
            flash("Debes seleccionar al menos un activo", "error")
            return redirect(url_for("dashboard_web.settings"))

        if max_assets != -1 and len(selected_assets) > max_assets:
            flash(f"Tu plan solo permite seleccionar {max_assets} activo(s)", "error")
        else:
            language = request.form.get("language", "es")
            telegram_id = request.form.get("telegram_chat_id", "").strip()
            with get_conn() as conn:
                conn.execute(
                    text("UPDATE subscriptions SET selected_assets=:assets WHERE user_id=:uid"),
                    {"assets": ",".join(selected_assets), "uid": current_user.id},
                )
                conn.execute(
                    text("UPDATE users SET language=:lang, telegram_chat_id=:tid WHERE id=:uid"),
                    {"lang": language, "tid": telegram_id, "uid": current_user.id},
                )
                conn.commit()
            flash("Configuración guardada", "success")

            next_step = request.args.get("next_step", "")
            if next_step == "select_assets":
                return redirect(url_for("dashboard_web.index"))

            return redirect(url_for("dashboard_web.settings"))

    selected = [a for a in (sub.get("selected_assets") or []) if a]
    max_assets = plan_config["max_assets"]
    if max_assets != -1 and len(selected) >= max_assets:
        locked_symbols = {a["symbol"] for a in AVAILABLE_ASSETS if a["symbol"] not in selected}
    else:
        locked_symbols = set()

    next_step = request.args.get("next_step", "")
    is_new_user = next_step == "select_assets"

    return render_template(
        "dashboard/settings.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
        available_assets=AVAILABLE_ASSETS,
        locked_symbols=locked_symbols,
        is_new_user=is_new_user,
        next_step=next_step,
    )


@dashboard_bp.route("/dashboard/subscription")
@login_required
def subscription():
    # Para subscription, solo validamos suscripción activa (pueden no tener pago aún)
    sub = current_user.get_subscription()
    if not sub or sub["status"] not in ("active", "trial"):
        flash("Necesitas una suscripción activa para acceder a esta sección", "warning")
        return redirect(url_for("billing.pricing"))

    plan_config = PLANS.get(sub["plan"], PLANS["basic"]) if sub else None
    has_payment_method = _user_has_payment_method(current_user.id)
    return render_template(
        "dashboard/subscription.html",
        sub=sub,
        plan_config=plan_config,
        plans=PLANS,
        has_payment_method=has_payment_method,
    )


@dashboard_bp.route("/dashboard/set-language", methods=["POST"])
@login_required
def set_language():
    data = request.get_json(silent=True) or {}
    lang = data.get("language", "es")
    VALID = {"es", "en", "fr", "de", "it", "pt", "zh", "ar"}
    if lang not in VALID:
        lang = "es"
    with get_conn() as conn:
        conn.execute(
            text("UPDATE users SET language=:lang WHERE id=:uid"),
            {"lang": lang, "uid": current_user.id},
        )
        conn.commit()
    return jsonify({"ok": True, "language": lang})
