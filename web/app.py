"""
web/app.py — Aplicación Flask principal con todos los blueprints.
"""
import os
from flask import Flask, render_template, redirect, url_for, jsonify
from flask_login import LoginManager
from web.models import init_db, User, PLANS, get_conn


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

    @main_bp.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @main_bp.route("/api/simulate", methods=["POST"])
    def simulate():
        from flask import request, jsonify
        import json
        from datetime import datetime, timedelta
        from sqlalchemy import text

        data = request.get_json()
        asset = data.get('asset')
        amount = float(data.get('amount', 0))
        period_days = int(data.get('period', 30))

        if not asset or amount <= 0:
            return jsonify({"error": "Invalid input"}), 400

        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_days)

        # Get predictions from the predictions database
        from web.db_engine import get_engine
        with get_engine("predictions").connect() as conn:
            rows = conn.execute(text("""
                SELECT direction, price_at_prediction, predicted_at
                FROM predictions
                WHERE asset = :asset
                AND predicted_at >= :start
                AND predicted_at <= :end
                ORDER BY predicted_at ASC
            """), {
                "asset": asset,
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }).fetchall()

        # Simulate
        cash = amount
        position = 0  # shares/units held
        last_price = None

        for row in rows:
            direction = row[0]
            price = row[1]
            if price and price > 0:
                if direction == "up" and cash > 0:
                    # Buy
                    position = cash / price
                    cash = 0
                elif direction == "down" and position > 0:
                    # Sell
                    cash = position * price
                    position = 0
                last_price = price

        # If still holding, sell at last known price
        if position > 0 and last_price:
            cash = position * last_price
            position = 0

        final_amount = cash
        profit_loss = final_amount - amount
        percentage = (profit_loss / amount) * 100 if amount > 0 else 0

        return jsonify({
            "initial_amount": f"{amount:.2f}",
            "final_amount": f"{final_amount:.2f}",
            "profit_loss": f"{profit_loss:+.2f}",
            "percentage": f"{percentage:+.2f}"
        })

    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_cookiebot():
        return dict(cookiebot_id=os.environ.get('COOKIEBOT_ID', ''))

    return app
