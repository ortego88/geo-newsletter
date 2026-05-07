"""
web/app.py — Aplicación Flask principal con todos los blueprints.
"""
import logging
from src.services.alert_formatter import ASSET_NAMES
from web.models import init_db, User, PLANS, get_conn, AVAILABLE_ASSETS

_logger = logging.getLogger(__name__)


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

    @main_bp.route("/historial")
    def historial():
        from flask import request
        from sqlalchemy import text
        from datetime import datetime, timedelta
        from web.db_engine import get_engine

        # Get time range from query param (7, 30, or all)
        time_range_param = request.args.get('days', '7')
        if time_range_param == 'all':
            time_range = 'all'
        else:
            time_range = int(time_range_param)
        
        # Pagination
        page = max(1, int(request.args.get('page', 1)))
        per_page = 20
        offset = (page - 1) * per_page
        
        # Filters
        asset_type_filter = request.args.get('asset_type', '')
        asset_filter = request.args.get('asset', '')
        
        # Define asset types - only crypto and ibex35 (ETFs removed)
        crypto_symbols = {a['symbol'] for a in AVAILABLE_ASSETS if a['symbol'] in ['BTC', 'ETH', 'XRP', 'SOL', 'BNB', 'ADA', 'DOGE', 'DOT', 'AVAX', 'MATIC', 'LINK', 'UNI', 'LTC', 'ATOM', 'XLM', 'ALGO', 'FIL', 'NEAR', 'ARB', 'OP']}
        ibex35_symbols = {a['symbol'] for a in AVAILABLE_ASSETS if a['symbol'] in ['IBEX35', 'ACS', 'ACX', 'AENA', 'ALM', 'AMS', 'ANA', 'BBVA', 'BKT', 'CABK', 'CLNX', 'COL', 'ELE', 'ENG', 'FDR', 'FER', 'GRF', 'IAG', 'IBE', 'IDR', 'ITX', 'LOG', 'MAP', 'MEL', 'MRL', 'MTS', 'NTGY', 'PHM', 'RED', 'REP', 'ROVI', 'SAB', 'SAN', 'SGRE', 'TEF']}
        
        asset_types = {
            'crypto': list(crypto_symbols),
            'ibex35': list(ibex35_symbols)
        }
        
        # Filter assets based on type
        if asset_type_filter and asset_type_filter in asset_types:
            allowed_assets = asset_types[asset_type_filter]
        else:
            allowed_assets = crypto_symbols | ibex35_symbols | etf_symbols
        
        # Calculate cutoff date (exclude today)
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        if time_range == '7':
            cutoff = (today - timedelta(days=7)).isoformat()
        elif time_range == '30':
            cutoff = (today - timedelta(days=30)).isoformat()
        else:  # all
            cutoff = '2000-01-01T00:00:00'
        
        end_date = today.isoformat()  # Exclude today
        
        # Helper function to convert UTC to Madrid time
        def to_madrid_time(iso_str):
            if not iso_str:
                return ""
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
                # Convert to Madrid timezone
                import pytz
                madrid_tz = pytz.timezone('Europe/Madrid')
                dt_madrid = dt.astimezone(madrid_tz)
                return dt_madrid.strftime('%Y-%m-%d %H:%M')
            except:
                return iso_str[:16]
        
        # Query predictions
        alerts = []
        total_alerts = 0
        accuracy_stats = {"total": 0, "correct": 0, "incorrect": 0, "accuracy_pct": 0.0, "pending": 0}
        
        try:
            with get_engine("predictions").connect() as conn:
                # Build WHERE clause
                where_parts = ["predicted_at >= :cutoff AND predicted_at < :end_date"]
                params = {"cutoff": cutoff, "end_date": end_date}
                
                if asset_filter:
                    where_parts.append("asset = :asset")
                    params["asset"] = asset_filter
                elif asset_type_filter and asset_type_filter in asset_types:
                    allowed = asset_types[asset_type_filter]
                    if allowed:
                        placeholders = ",".join([f"'{a}'" for a in allowed])
                        where_parts.append(f"asset IN ({placeholders})")
                
                where_clause = " AND ".join(where_parts)
                
                # Get total count
                total_result = conn.execute(text(f"""
                    SELECT COUNT(*) FROM predictions
                    WHERE {where_clause}
                """), params).fetchone()
                total_alerts = total_result[0] if total_result else 0
                total_pages = (total_alerts + per_page - 1) // per_page
                
                # Get paginated alerts
                alerts_raw = conn.execute(text(f"""
                    SELECT id, asset, direction, impact_percent, confidence, 
                           price_at_prediction, price_at_validation, predicted_at,
                           validated_at, outcome, score, title
                    FROM predictions
                    WHERE {where_clause}
                    ORDER BY predicted_at DESC
                    LIMIT :limit OFFSET :offset
                """), {**params, "limit": per_page, "offset": offset}).mappings().fetchall()
                
                # Process alerts with Madrid time
                for row in alerts_raw:
                    d = dict(row)
                    d["predicted_at_madrid"] = to_madrid_time(d.get("predicted_at", ""))
                    d["validated_at_madrid"] = to_madrid_time(d.get("validated_at", ""))
                    alerts.append(d)
                
                # Calculate accuracy stats for displayed alerts
                outcomes = conn.execute(text(f"""
                    SELECT outcome, confidence FROM predictions
                    WHERE predicted_at >= :cutoff AND predicted_at < :end_date AND outcome != 'pending'
                """), {"cutoff": cutoff, "end_date": end_date}).fetchall()
                
                if outcomes:
                    total = len(outcomes)
                    correct = sum(1 for r in outcomes if r[0] == "correct")
                    accuracy_stats["total"] = total
                    accuracy_stats["correct"] = correct
                    accuracy_stats["incorrect"] = total - correct
                    accuracy_stats["accuracy_pct"] = round(correct / total * 100, 1) if total > 0 else 0.0
                
                # Count pending
                pending = conn.execute(text(f"""
                    SELECT COUNT(*) FROM predictions
                    WHERE predicted_at >= :cutoff AND predicted_at < :end_date AND outcome = 'pending'
                """), {"cutoff": cutoff, "end_date": end_date}).fetchone()[0]
                accuracy_stats["pending"] = pending
                
        except Exception as e:
            _logger.warning(f"Could not load history: {e}", exc_info=True)
        
        return render_template(
            "history.html",
            alerts=alerts,
            total_alerts=total_alerts,
            accuracy_stats=accuracy_stats,
            time_range=time_range,
            plans=PLANS,
            asset_names=ASSET_NAMES,
            page=page,
            total_pages=total_pages,
            asset_type_filter=asset_type_filter,
            asset_filter=asset_filter,
            asset_types=asset_types
        )

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
