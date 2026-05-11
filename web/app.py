"""
web/app.py — Aplicación Flask principal con todos los blueprints.
"""
import logging
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_login import LoginManager
from sqlalchemy import text
from src.services.alert_formatter import ASSET_NAMES
from src.services.market_config import get_assets_by_type, get_asset_type
from web.models import init_db, User, PLANS, get_conn, AVAILABLE_ASSETS
from web.db_engine import get_engine
import pytz

_logger = logging.getLogger(__name__)
_MADRID_TZ = pytz.timezone("Europe/Madrid")

_VALID_SORTS = [
    "predicted_at", "score", "confidence", "impact_percent",
    "price_at_prediction", "price_at_validation",
]
_SORT_FIELD_MAP = {s: s for s in _VALID_SORTS}


def _get_predictions_conn():
    return get_engine("predictions").connect()


def _to_madrid_str(dt_str) -> str:
    """UTC ISO string → 'dd/mm HH:MM' hora Madrid. Devuelve '—' si falla."""
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.utc)
        return dt.astimezone(_MADRID_TZ).strftime("%d/%m %H:%M")
    except Exception:
        return str(dt_str)[:16]


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    debug_mode = (
        os.getenv("FLASK_ENV", "production") == "development"
        or os.getenv("DEBUG", "").lower() in ("1", "true")
    )
    if debug_mode:
        app.config["TEMPLATES_AUTO_RELOAD"] = True

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Inicia sesión para acceder a esta página"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    init_db()

    from web.admin import admin_bp
    from web.auth import auth_bp
    from web.billing import billing_bp
    from web.dashboard_web import dashboard_bp
    from web.blog import blog_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(blog_bp)

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
        """
        Página pública de historial. Misma lógica que el dashboard privado,
        sin requerir login. Muestra todas las predicciones de la BD.
        """
        page = max(1, int(request.args.get("page", 1)))
        per_page = 20
        offset = (page - 1) * per_page

        asset_filter = request.args.get("asset", "").strip()
        asset_type_filter = request.args.get("asset_type", "").strip()
        outcome_filter = request.args.get("outcome", "").strip()
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
        accuracy_stats = {
            "total": 0, "correct": 0, "incorrect": 0,
            "accuracy_pct": 0.0, "pending": 0, "neutral": 0,
        }

        try:
            with _get_predictions_conn() as conn:
                where = "WHERE 1=1"
                params: dict = {}

                # Time filter
                if time_filter == "24h":
                    cutoff = datetime.utcnow() - timedelta(hours=24)
                    where += " AND predicted_at >= :time_cutoff"
                    params["time_cutoff"] = cutoff.isoformat()
                elif time_filter == "7d":
                    cutoff = datetime.utcnow() - timedelta(days=7)
                    where += " AND predicted_at >= :time_cutoff"
                    params["time_cutoff"] = cutoff.isoformat()
                elif time_filter == "30d":
                    cutoff = datetime.utcnow() - timedelta(days=30)
                    where += " AND predicted_at >= :time_cutoff"
                    params["time_cutoff"] = cutoff.isoformat()

                if asset_filter:
                    where += " AND asset = :asset"
                    params["asset"] = asset_filter

                if asset_type_filter and not asset_filter:
                    type_assets = sorted(list(get_assets_by_type(asset_type_filter)))
                    if type_assets:
                        placeholders = ",".join(f"'{a}'" for a in type_assets)
                        where += f" AND asset IN ({placeholders})"

                if outcome_filter in ("correct", "incorrect", "pending", "neutral"):
                    where += " AND outcome = :outcome"
                    params["outcome"] = outcome_filter

                total_alerts = conn.execute(
                    text(f"SELECT COUNT(*) FROM predictions {where}"), params
                ).fetchone()[0]
                total_pages = max(1, (total_alerts + per_page - 1) // per_page)

                # Stats — neutral no entra en correct/incorrect
                all_outcomes = conn.execute(
                    text(f"SELECT outcome, confidence FROM predictions {where}"), params
                ).fetchall()

                pending = sum(1 for r in all_outcomes if r[0] == "pending")
                neutral = sum(1 for r in all_outcomes if r[0] == "neutral")
                decisive = [r for r in all_outcomes if r[0] not in ("pending", "neutral")]
                correct = sum(1 for r in decisive if r[0] == "correct")
                total_decisive = len(decisive)

                accuracy_stats = {
                    "total": total_decisive,
                    "correct": correct,
                    "incorrect": total_decisive - correct,
                    "accuracy_pct": round(correct / total_decisive * 100, 1) if total_decisive else 0.0,
                    "pending": pending,
                    "neutral": neutral,
                }

                rows = conn.execute(
                    text(f"""
                        SELECT id, title, asset, direction, impact_percent, confidence,
                               price_at_prediction, price_at_validation, predicted_at,
                               outcome, score, reasoning
                        FROM predictions {where}
                        ORDER BY {sort_col} {sort_order}
                        LIMIT :lim OFFSET :off
                    """),
                    {**params, "lim": per_page, "off": offset},
                ).mappings().fetchall()

        except Exception as exc:
            _logger.error("Error cargando historial: %s", exc, exc_info=True)
            rows = []

        for row in rows:
            d = dict(row)
            d["predicted_at_madrid"] = _to_madrid_str(d.get("predicted_at"))
            p_in = d.get("price_at_prediction") or 0
            p_out = d.get("price_at_validation")
            if p_in and p_in > 0 and p_out:
                d["price_change_pct"] = round((p_out - p_in) / p_in * 100, 2)
            else:
                d["price_change_pct"] = None
            alerts.append(d)

        asset_type_map = {a["symbol"]: get_asset_type(a["symbol"]) for a in AVAILABLE_ASSETS}

        return render_template(
            "history.html",
            alerts=alerts,
            accuracy_stats=accuracy_stats,
            available_assets=AVAILABLE_ASSETS,
            asset_type_map=asset_type_map,
            asset_names=ASSET_NAMES,
            page=page,
            per_page=per_page,
            total_alerts=total_alerts,
            total_pages=total_pages,
            asset_filter=asset_filter,
            asset_type_filter=asset_type_filter,
            outcome_filter=outcome_filter,
            time_filter=time_filter,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    @main_bp.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @main_bp.route("/test-telegram")
    def test_telegram():
        """
        Endpoint para forzar el envío de una alerta de prueba a Telegram.
        Útil para verificar que el bot y el chat_id están configurados correctamente.
        """
        try:
            from src.services.telegram_sender import send_telegram
            from src.services.alert_formatter import format_telegram_alert

            # Evento de prueba
            test_event = {
                "title": "🧪 ALERTA DE PRUEBA - Sistema funcionando correctamente",
                "description": "Esta es una alerta manual disparada desde el endpoint /test-telegram",
                "score": 85,
                "category": "test",
                "sources": ["endpoint_test"],
                "prediction_id": 999999,
                "analysis": {
                    "direction": "up",
                    "confidence": 90,
                    "most_affected_assets": ["BTC", "ETH"],
                    "signal_strength": "high",
                    "timeframe": "hours",
                    "reasoning": "Prueba manual del sistema de alertas. Si recibes esto, todo funciona ✅",
                    "market_impact_percent": 0,
                }
            }

            # Formatear y enviar
            msg = format_telegram_alert(test_event, test_event["analysis"])
            success = send_telegram(msg)

            if success:
                return jsonify({
                    "status": "success",
                    "message": "✅ Alerta de prueba enviada correctamente a Telegram",
                    "telegram_message": msg
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "❌ Error al enviar alerta. Verifica TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID"
                }), 500

        except Exception as e:
            _logger.error(f"Error en test-telegram: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"❌ Error: {str(e)}"
            }), 500

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
            with _get_predictions_conn() as conn:
                rows = conn.execute(text("""
                    SELECT direction, price_at_prediction
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

        for direction, price in rows:
            if price and price > 0:
                # Señal alcista: si tenemos efectivo, compramos; si ya tenemos posición, mantenemos
                if direction in ("up", "bullish", "positive", "alza"):
                    if cash > 0:
                        # Compramos con todo el efectivo disponible
                        position = cash / price
                        cash = 0.0
                # Señal bajista: si tenemos posición, vendemos; si ya estamos en efectivo, mantenemos
                elif direction in ("down", "bearish", "negative", "baja"):
                    if position > 0:
                        # Vendemos toda la posición y convertimos a efectivo
                        cash = position * price
                        position = 0.0
                last_price = price

        # Al final, si quedamos con posición abierta, la cerramos al último precio
        if position > 0 and last_price:
            cash = position * last_price

        profit_loss = cash - amount
        percentage = (profit_loss / amount) * 100 if amount > 0 else 0.0

        return jsonify({
            "initial_amount": f"{amount:.2f}",
            "final_amount": f"{cash:.2f}",
            "profit_loss": f"{profit_loss:+.2f}",
            "percentage": f"{percentage:+.2f}",
        })

    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_cookiebot():
        return dict(cookiebot_id=os.environ.get("COOKIEBOT_ID", ""))

    return app
