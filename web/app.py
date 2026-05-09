"""
web/app.py — Aplicación Flask principal con todos los blueprints.

CAMBIOS v2:
- Fix error 500 en /historial: manejo robusto de valores None en predicted_at,
  conversión explícita de set a list en get_assets_by_type(), y protección
  contra filas con campos faltantes.
- Fix: stats de accuracy en /historial ahora excluyen outcome='neutral'
  (consistente con el nuevo sistema de validación de prediction_tracker).
"""
import logging
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_login import LoginManager
from sqlalchemy import text
from src.services.alert_formatter import ASSET_NAMES
from src.services.market_config import get_assets_by_type
from web.models import init_db, User, PLANS, get_conn, AVAILABLE_ASSETS
from web.db_engine import get_engine
import pytz

_logger = logging.getLogger(__name__)

_MADRID_TZ = pytz.timezone("Europe/Madrid")

def _get_predictions_conn():
    return get_engine("predictions").connect()


def _to_madrid_time(dt_str: str) -> str:
    """Converts a UTC ISO datetime string to Madrid local time. Returns '—' on any error."""
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt.astimezone(_MADRID_TZ).isoformat()
    except Exception:
        return str(dt_str)[:16] if dt_str else "—"


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # Enable template auto-reload in development mode
    debug_mode = os.getenv("FLASK_ENV", "production") == "development" or os.getenv("DEBUG", "").lower() in ("1", "true")
    if debug_mode:
        app.config["TEMPLATES_AUTO_RELOAD"] = True

    # Flask-Login
    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Inicia sesión para acceder a esta página"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    # Initialize DB
    init_db()

    # Blueprints
    from web.admin import admin_bp
    from web.auth import auth_bp
    from web.billing import billing_bp
    from web.dashboard_web import dashboard_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(dashboard_bp)

    # Main routes
    from flask import Blueprint
    main_bp = Blueprint("main", __name__)

    @main_bp.route("/")
    def landing():
        return render_template("landing.html", plans=PLANS)

    @main_bp.route("/privacy")
    def privacy():
        return render_template("privacy.html", plans=PLANS)

    @main_bp.route("/terms")
    def terms():
        return render_template("terms.html")

    @main_bp.route("/historial")
    def history():
        page = max(1, int(request.args.get("page", 1)))
        per_page = 20
        offset = (page - 1) * per_page
        asset_filter = request.args.get("asset", "").strip()
        asset_type_filter = request.args.get("asset_type", "").strip()
        days_param = request.args.get("days", "all")
        time_range = days_param if days_param in ("7", "30", "all") else "all"

        alerts = []
        total_alerts = 0
        total_pages = 1
        # neutral se excluye de correct/incorrect (nuevo sistema de validación)
        accuracy_stats = {
            "correct": 0, "incorrect": 0, "pending": 0,
            "neutral": 0, "total": 0, "accuracy_pct": 0,
        }

        try:
            cutoff_days = {"7": 7, "30": 30, "all": 9999}.get(time_range, 9999)
            cutoff = (datetime.utcnow() - timedelta(days=cutoff_days)).isoformat()

            with _get_predictions_conn() as conn2:
                where = "WHERE predicted_at >= :cutoff"
                extra_params: dict = {"cutoff": cutoff}

                # Filtro por tipo de activo — convertir set a list para evitar errores
                if asset_type_filter and not asset_filter:
                    type_assets = list(get_assets_by_type(asset_type_filter))  # set → list
                    if type_assets:
                        # Usar parámetros posicionales para evitar SQL injection
                        placeholders = ",".join([f"'{a}'" for a in type_assets])
                        where += f" AND asset IN ({placeholders})"

                if asset_filter:
                    where += " AND asset = :asset"
                    extra_params["asset"] = asset_filter

                total_alerts = conn2.execute(
                    text(f"SELECT COUNT(*) FROM predictions {where}"),
                    extra_params,
                ).fetchone()[0]
                total_pages = max(1, (total_alerts + per_page - 1) // per_page)

                # Stats: excluir 'neutral' del cómputo de correct/incorrect
                # (consistente con prediction_tracker.get_accuracy_stats)
                outcome_counts = conn2.execute(
                    text(f"SELECT outcome, COUNT(*) as cnt FROM predictions {where} GROUP BY outcome"),
                    extra_params,
                ).mappings().fetchall()

                for row in outcome_counts:
                    outcome_val = row["outcome"] or "pending"
                    if outcome_val == "correct":
                        accuracy_stats["correct"] = row["cnt"]
                    elif outcome_val == "incorrect":
                        accuracy_stats["incorrect"] = row["cnt"]
                    elif outcome_val == "pending":
                        accuracy_stats["pending"] = row["cnt"]
                    elif outcome_val == "neutral":
                        accuracy_stats["neutral"] = row["cnt"]

                # total solo cuenta correct + incorrect (no neutral ni pending)
                accuracy_stats["total"] = accuracy_stats["correct"] + accuracy_stats["incorrect"]
                if accuracy_stats["total"] > 0:
                    accuracy_stats["accuracy_pct"] = round(
                        100 * accuracy_stats["correct"] / accuracy_stats["total"]
                    )

                alerts_raw = conn2.execute(
                    text(f"""
                        SELECT id, asset, direction, impact_percent, confidence,
                               outcome, predicted_at
                        FROM predictions {where}
                        ORDER BY predicted_at DESC
                        LIMIT :limit OFFSET :offset
                    """),
                    {**extra_params, "limit": per_page, "offset": offset},
                ).mappings().fetchall()

        except Exception as exc:
            _logger.error("Error cargando historial de predicciones: %s", exc, exc_info=True)
            alerts_raw = []

        # Convertir filas a dicts con hora Madrid — protección contra None
        for row in alerts_raw:
            try:
                raw_dt = row.get("predicted_at") or ""
                if raw_dt:
                    dt = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=pytz.utc)
                    madrid_time = dt.astimezone(_MADRID_TZ).isoformat()
                else:
                    madrid_time = "—"
            except Exception:
                madrid_time = str(row.get("predicted_at", "—"))[:16]

            alerts.append({
                "asset": row.get("asset") or "—",
                "direction": row.get("direction") or "neutral",
                "impact_percent": row.get("impact_percent"),
                "confidence": row.get("confidence"),
                "outcome": row.get("outcome") or "pending",
                "predicted_at_madrid": madrid_time,
            })

        # Construir asset_types para los filtros del frontend
        # get_assets_by_type devuelve un set → convertir a lista ordenada
        asset_types = {
            "crypto": sorted(list(get_assets_by_type("crypto"))),
            "ibex35": sorted(list(get_assets_by_type("ibex35"))),
        }

        return render_template(
            "history.html",
            alerts=alerts,
            accuracy_stats=accuracy_stats,
            page=page,
            total_pages=total_pages,
            total_alerts=total_alerts,
            asset_filter=asset_filter,
            asset_type_filter=asset_type_filter,
            time_range=time_range,
            asset_types=asset_types,
            asset_names=ASSET_NAMES,
        )

    @main_bp.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @main_bp.route("/api/simulate", methods=["POST"])
    def simulate():
        data = request.get_json(silent=True) or {}
        asset = data.get("asset", "").strip()
        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0.0
        try:
            period_days = int(data.get("period", 30))
        except (TypeError, ValueError):
            period_days = 30

        if not asset or amount <= 0:
            return jsonify({"error": "Parámetros inválidos"}), 400

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_days)

        try:
            with get_engine("predictions").connect() as conn:
                rows = conn.execute(text("""
                    SELECT direction, price_at_prediction, predicted_at
                    FROM predictions
                    WHERE asset = :asset
                    AND predicted_at >= :start
                    AND predicted_at <= :end
                    AND outcome != 'pending'
                    ORDER BY predicted_at ASC
                """), {
                    "asset": asset,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }).fetchall()
        except Exception as exc:
            _logger.error("Error en simulación: %s", exc)
            return jsonify({"error": "Error de base de datos"}), 500

        cash = amount
        position = 0.0
        last_price = None

        for row in rows:
            direction = row[0] or "neutral"
            price = row[1]
            if price and price > 0:
                if direction in ("up", "bullish", "positive", "alza") and cash > 0:
                    position = cash / price
                    cash = 0.0
                elif direction in ("down", "bearish", "negative", "baja") and position > 0:
                    cash = position * price
                    position = 0.0
                last_price = price

        if position > 0 and last_price:
            cash = position * last_price

        final_amount = cash
        profit_loss = final_amount - amount
        percentage = (profit_loss / amount) * 100 if amount > 0 else 0.0

        return jsonify({
            "initial_amount": f"{amount:.2f}",
            "final_amount": f"{final_amount:.2f}",
            "profit_loss": f"{profit_loss:+.2f}",
            "percentage": f"{percentage:+.2f}",
        })

    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_cookiebot():
        return dict(cookiebot_id=os.environ.get("COOKIEBOT_ID", ""))

    return app
