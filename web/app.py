"""
web/app.py — Aplicación Flask principal con todos los blueprints.
"""
import logging
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager, current_user
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


# ── Best performer cache (recalculated every hour) ───────────────────────────
_best_performer_cache = {"data": None, "expires": 0}


def _get_best_performers() -> dict:
    """
    Scans all 65 cryptos and returns the best gain % and best loss avoided %
    over the last 7 days using the simulator logic. Cached 1 hour.
    """
    import time
    now = time.time()
    if _best_performer_cache["data"] and now < _best_performer_cache["expires"]:
        return _best_performer_cache["data"]

    from src.services.real_price_fetcher import get_price

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    best_gain = {"asset": "", "pct": 0.0}
    best_avoided = {"asset": "", "pct": 0.0}

    try:
        with _get_predictions_conn() as conn:
            for asset_info in AVAILABLE_ASSETS:
                symbol = asset_info["symbol"]
                rows = conn.execute(text("""
                    SELECT direction, price_at_prediction
                    FROM predictions
                    WHERE UPPER(asset) = UPPER(:asset)
                      AND price_at_prediction > 0
                      AND predicted_at >= :start
                      AND predicted_at <= :end
                    ORDER BY predicted_at ASC
                """), {
                    "asset": symbol,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }).fetchall()

                if not rows:
                    continue

                current_price = get_price(symbol)
                if not current_price:
                    continue

                # Simulate
                state = "IN_MARKET"
                balance = 1000.0
                entry_price = rows[0][1]
                loss_avoided = 0.0
                sell_price = None

                for direction, price_pred in rows:
                    is_down = direction in ("down", "bearish", "negative", "baja")
                    is_up = direction in ("up", "bullish", "positive", "alza")

                    if state == "IN_MARKET" and is_down:
                        sell_price = price_pred
                        pct_change = (sell_price - entry_price) / entry_price
                        balance = balance * (1 + pct_change)
                        state = "CASH"
                    elif state == "CASH" and is_up:
                        if sell_price and price_pred < sell_price:
                            loss_avoided += balance * ((sell_price - price_pred) / sell_price)
                        entry_price = price_pred
                        state = "IN_MARKET"

                # Close with current price
                if state == "IN_MARKET" and entry_price:
                    pct_change = (current_price - entry_price) / entry_price
                    balance = balance * (1 + pct_change)
                elif state == "CASH" and sell_price and current_price < sell_price:
                    loss_avoided += balance * ((sell_price - current_price) / sell_price)

                gain_pct = (balance - 1000.0) / 1000.0 * 100
                avoided_pct = loss_avoided / 1000.0 * 100

                if gain_pct > best_gain["pct"]:
                    best_gain = {"asset": symbol, "pct": round(gain_pct, 1)}
                if avoided_pct > best_avoided["pct"]:
                    best_avoided = {"asset": symbol, "pct": round(avoided_pct, 1)}

    except Exception as exc:
        _logger.warning("Error calculating best performers: %s", exc)

    result = {"best_gain": best_gain, "best_avoided": best_avoided}
    _best_performer_cache["data"] = result
    _best_performer_cache["expires"] = now + 3600  # 1 hour
    return result


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
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 604800  # 7 days cache for static files
    app.config["GTM_ID"] = os.getenv("GTM_ID", "")
    app.config["GA4_ID"] = os.getenv("GA4_ID", "")
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
    app.config["WTF_CSRF_ENABLED"] = False  # Using SameSite=Lax as primary CSRF defense

    debug_mode = (
        os.getenv("FLASK_ENV", "production") == "development"
        or os.getenv("DEBUG", "").lower() in ("1", "true")
    )
    if debug_mode:
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.config["SESSION_COOKIE_SECURE"] = False

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Inicia sesión para acceder a esta página"
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    init_db()

    from web.auth import auth_bp
    from web.billing import billing_bp
    from web.dashboard_web import dashboard_bp
    from web.blog import blog_bp
    from web.telegram_bot import telegram_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(telegram_bp)

    from flask import Blueprint
    main_bp = Blueprint("main", __name__)

    @main_bp.route("/")
    def landing():
        best = _get_best_performers()
        return render_template("landing.html", plans=PLANS, best_performers=best, dl_page_name="home", dl_section_name="home", dl_service_type="home", dl_web_area="public")

    @main_bp.route("/app")
    def app_home():
        if current_user.is_authenticated:
            return redirect("/dashboard")
        return render_template("app_home.html")

    @main_bp.route("/como-funciona")
    def how_it_works():
        return render_template("how_it_works.html", dl_page_name="how_it_works", dl_section_name="informational", dl_service_type="serviceInformation", dl_web_area="public")

    @main_bp.route("/activos")
    def assets_page():
        return render_template("assets.html", dl_page_name="assets", dl_section_name="informational", dl_service_type="serviceInformation", dl_web_area="public")

    @main_bp.route("/waitlist")
    def waitlist():
        return redirect("/register")

    @main_bp.route("/privacy")
    def privacy():
        return render_template("privacy.html", plans=PLANS, dl_page_name="privacy", dl_section_name="privacy", dl_service_type="serviceInformation", dl_web_area="public")

    @main_bp.route("/terms")
    def terms():
        return render_template("terms.html", dl_page_name="terms", dl_section_name="terms", dl_service_type="serviceInformation", dl_web_area="public")

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
        direction_filter = request.args.get("direction", "").strip()
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
            "up_correct": 0, "up_incorrect": 0,
            "down_correct": 0, "down_incorrect": 0,
            "best_asset": "", "best_asset_pct": 0.0,
        }

        # Only show predictions for assets in AVAILABLE_ASSETS
        available_symbols = {a["symbol"].upper() for a in AVAILABLE_ASSETS}
        available_in_clause = ",".join(f"'{s}'" for s in sorted(available_symbols))

        try:
            with _get_predictions_conn() as conn:
                # 24h delay: only show predictions older than 24 hours
                # Exclude silent calibration signals from user-facing stats
                delay_cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
                where = (
                    f"WHERE UPPER(asset) IN ({available_in_clause})"
                    f" AND predicted_at <= :delay_cutoff"
                    f" AND source NOT IN ('price_signal_late_move', 'price_signal_silent')"
                )
                params: dict = {"delay_cutoff": delay_cutoff}

                # Only show predictions from after the user's registration date
                user_created_at = current_user.created_at if hasattr(current_user, 'created_at') else None
                if not user_created_at:
                    try:
                        with get_conn() as app_conn:
                            row = app_conn.execute(
                                text("SELECT created_at FROM users WHERE id = :uid"),
                                {"uid": current_user.id}
                            ).fetchone()
                            user_created_at = row[0] if row else None
                    except Exception:
                        pass
                if user_created_at:
                    where += " AND predicted_at >= :user_since"
                    params["user_since"] = str(user_created_at)[:19]

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

                if direction_filter in ("up", "down"):
                    dir_values = ("up", "bullish", "positive", "alza") if direction_filter == "up" else ("down", "bearish", "negative", "baja")
                    dir_list = ",".join([f"'{d}'" for d in dir_values])
                    where += f" AND LOWER(direction) IN ({dir_list})"

                total_alerts = conn.execute(
                    text(f"SELECT COUNT(*) FROM predictions {where}"), params
                ).fetchone()[0]
                total_pages = max(1, (total_alerts + per_page - 1) // per_page)

                # Stats — neutral no entra en correct/incorrect
                all_outcomes = conn.execute(
                    text(f"SELECT outcome, confidence, direction, asset FROM predictions {where}"), params
                ).fetchall()

                pending = sum(1 for r in all_outcomes if r[0] == "pending")
                neutral = sum(1 for r in all_outcomes if r[0] == "neutral")
                decisive = [r for r in all_outcomes if r[0] not in ("pending", "neutral")]
                correct = sum(1 for r in decisive if r[0] == "correct")
                total_decisive = len(decisive)

                # Direction breakdown
                up_dirs = ("up", "bullish", "positive", "alza")
                down_dirs = ("down", "bearish", "negative", "baja")
                up_outcomes = [r for r in decisive if (r[2] or "").lower() in up_dirs]
                down_outcomes = [r for r in decisive if (r[2] or "").lower() in down_dirs]
                up_correct = sum(1 for r in up_outcomes if r[0] == "correct")
                down_correct = sum(1 for r in down_outcomes if r[0] == "correct")

                # Best asset by accuracy (min 3 predictions)
                asset_counts = {}
                for r in decisive:
                    a = (r[3] or "").upper()
                    if not a:
                        continue
                    if a not in asset_counts:
                        asset_counts[a] = {"correct": 0, "total": 0}
                    asset_counts[a]["total"] += 1
                    if r[0] == "correct":
                        asset_counts[a]["correct"] += 1
                best_asset = ""
                best_asset_pct = 0.0
                for a, c in asset_counts.items():
                    if c["total"] >= 3:
                        pct = c["correct"] / c["total"] * 100
                        if pct > best_asset_pct or (pct == best_asset_pct and c["total"] > asset_counts.get(best_asset, {}).get("total", 0)):
                            best_asset = a
                            best_asset_pct = pct

                accuracy_stats = {
                    "total": total_decisive,
                    "correct": correct,
                    "incorrect": total_decisive - correct,
                    "accuracy_pct": round(correct / total_decisive * 100, 1) if total_decisive else 0.0,
                    "pending": pending,
                    "neutral": neutral,
                    "up_correct": up_correct,
                    "up_incorrect": len(up_outcomes) - up_correct,
                    "down_correct": down_correct,
                    "down_incorrect": len(down_outcomes) - down_correct,
                    "best_asset": best_asset,
                    "best_asset_pct": round(best_asset_pct, 0),
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
            outcome = d.get("outcome", "pending")
            direction = d.get("direction", "")
            # Show max favorable move: positive = moved in predicted direction
            # UP: price_at_validation is the max reached → show as positive %
            # DOWN: price_at_validation is the min reached → invert sign to show positive
            if p_in and p_in > 0 and p_out and outcome != "pending":
                raw_pct = (p_out - p_in) / p_in * 100
                if direction in ("down", "bearish", "negative", "baja"):
                    # For DOWN, min price means price went down = positive opportunity
                    d["price_change_pct"] = round(-raw_pct, 2)
                else:
                    d["price_change_pct"] = round(raw_pct, 2)
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
            direction_filter=direction_filter,
            time_filter=time_filter,
            sort_by=sort_by,
            sort_dir=sort_dir,
            dl_page_name="history",
            dl_section_name="history",
            dl_service_type="productInformation",
            dl_web_area="public",
        )

    @main_bp.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @main_bp.route("/google<code>.html")
    def google_verification(code):
        """Google Search Console verification file."""
        from flask import Response
        return Response(
            f"google-site-verification: google{code}.html",
            mimetype="text/html",
        )

    @main_bp.route("/robots.txt")
    def robots_txt():
        from flask import Response
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin\n"
            "Disallow: /api/\n"
            "Disallow: /dashboard\n"
            "\n"
            "Sitemap: https://trianio.com/sitemap.xml\n"
        )
        return Response(content, mimetype="text/plain")

    @main_bp.route("/sitemap.xml")
    def sitemap_xml():
        from flask import Response
        urls = []
        urls.append({"loc": "https://trianio.com/", "priority": "1.0", "changefreq": "daily"})
        urls.append({"loc": "https://trianio.com/blog", "priority": "0.9", "changefreq": "daily"})
        try:
            with get_engine("app").connect() as conn:
                rows = conn.execute(text(
                    "SELECT slug, updated_at, published_at FROM blog_posts "
                    "WHERE is_published = TRUE ORDER BY published_at DESC"
                )).fetchall()
            for row in rows:
                lastmod = row[1] or row[2]
                if lastmod:
                    try:
                        lastmod = datetime.fromisoformat(lastmod).strftime("%Y-%m-%d")
                    except Exception:
                        lastmod = str(lastmod)[:10]
                urls.append({
                    "loc": f"https://trianio.com/blog/{row[0]}",
                    "lastmod": lastmod,
                    "priority": "0.8",
                    "changefreq": "weekly",
                })
        except Exception:
            pass

        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        for url in urls:
            xml += '  <url>\n'
            xml += f'    <loc>{url["loc"]}</loc>\n'
            if url.get("lastmod"):
                xml += f'    <lastmod>{url["lastmod"]}</lastmod>\n'
            xml += f'    <changefreq>{url.get("changefreq", "weekly")}</changefreq>\n'
            xml += f'    <priority>{url.get("priority", "0.5")}</priority>\n'
            xml += '  </url>\n'
        xml += '</urlset>'
        return Response(xml, mimetype="application/xml")


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
                    SELECT direction, price_at_prediction, price_at_validation, outcome
                    FROM predictions
                    WHERE UPPER(asset) = UPPER(:asset)
                      AND price_at_prediction > 0
                      AND predicted_at >= :start
                      AND predicted_at <= :end
                    ORDER BY predicted_at ASC
                """), {
                    "asset": asset,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }).fetchall()
        except Exception as exc:
            _logger.error("Error en simulación: %s", exc)
            return jsonify({"error": "Error de base de datos"}), 500

        if not rows:
            return jsonify({"error": "Sin datos suficientes para este activo y período"}), 400

        # Get current real-time price for end-state calculations
        from src.services.real_price_fetcher import get_price
        current_price = get_price(asset)

        # State machine: IN_MARKET or CASH
        state = "IN_MARKET"
        balance = amount
        entry_price = rows[0][1]
        loss_avoided = 0.0
        sell_price = None
        trades = [{
            "action": "buy",
            "price": round(entry_price, 4),
            "return_pct": 0,
            "balance_after": round(amount, 2),
        }]

        for direction, price_pred, price_val, outcome in rows:
            is_down = direction in ("down", "bearish", "negative", "baja")
            is_up = direction in ("up", "bullish", "positive", "alza")

            if state == "IN_MARKET" and is_down:
                sell_price = price_pred
                pct_change = (sell_price - entry_price) / entry_price
                balance = balance * (1 + pct_change)
                state = "CASH"
                trades.append({
                    "action": "sell",
                    "price": round(sell_price, 4),
                    "return_pct": round(pct_change * 100, 2),
                    "balance_after": round(balance, 2),
                })

            elif state == "CASH" and is_up:
                entry_price = price_pred
                if sell_price and price_pred < sell_price:
                    loss_avoided += balance * ((sell_price - price_pred) / sell_price)
                state = "IN_MARKET"
                trades.append({
                    "action": "buy",
                    "price": round(entry_price, 4),
                    "return_pct": 0,
                    "balance_after": round(balance, 2),
                })

        # End-state: use current real-time price
        if state == "IN_MARKET" and current_price and entry_price:
            pct_change = (current_price - entry_price) / entry_price
            balance = balance * (1 + pct_change)
            trades.append({
                "action": "close",
                "price": round(current_price, 4),
                "return_pct": round(pct_change * 100, 2),
                "balance_after": round(balance, 2),
            })
        elif state == "CASH" and current_price and sell_price:
            # Still in cash after last sell signal — calculate loss avoided
            if current_price < sell_price:
                loss_avoided += balance * ((sell_price - current_price) / sell_price)

        profit_loss = balance - amount
        percentage = (profit_loss / amount) * 100 if amount > 0 else 0.0

        return jsonify({
            "initial_amount": f"{amount:.2f}",
            "final_amount": f"{balance:.2f}",
            "profit_loss": f"{profit_loss:+.2f}",
            "percentage": f"{percentage:+.2f}",
            "loss_avoided": f"{loss_avoided:.2f}",
            "num_signals": len(rows),
            "trades": trades,
        })

    @main_bp.route("/api/newsletter-signup", methods=["POST"])
    def newsletter_signup():
        data = request.get_json(silent=True) or {}
        first_name = data.get("first_name", "").strip()
        last_name = data.get("last_name", "").strip()
        email = data.get("email", "").strip().lower()
        terms = data.get("terms")

        if not first_name or not last_name or not email:
            return jsonify({"error": "Todos los campos son obligatorios"}), 400
        if not terms:
            return jsonify({"error": "Debes aceptar los términos y condiciones"}), 400
        if "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "Email no válido"}), 400

        try:
            with get_conn() as conn:
                existing = conn.execute(
                    text("SELECT id FROM newsletter_subscribers WHERE email = :email"),
                    {"email": email},
                ).fetchone()
                if existing:
                    return jsonify({"ok": True, "message": "Ya estabas suscrito"}), 200

                conn.execute(
                    text("""
                        INSERT INTO newsletter_subscribers (first_name, last_name, email, subscribed_at)
                        VALUES (:first_name, :last_name, :email, :now)
                    """),
                    {
                        "first_name": first_name,
                        "last_name": last_name,
                        "email": email,
                        "now": datetime.utcnow().isoformat(),
                    },
                )
                conn.commit()
        except Exception as exc:
            _logger.error("Error en newsletter signup: %s", exc)
            return jsonify({"error": "Error al registrar. Inténtalo de nuevo."}), 500

        _sync_brevo_contact(email, first_name, last_name)
        return jsonify({"ok": True}), 201

    def _sync_brevo_contact(email: str, first_name: str, last_name: str):
        """Adds or updates contact in Brevo (async, best-effort)."""
        brevo_key = os.getenv("BREVO_API_KEY", "")
        if not brevo_key:
            _logger.warning("Brevo sync skipped: BREVO_API_KEY not set")
            return
        try:
            import requests as _req
            resp = _req.post(
                "https://api.brevo.com/v3/contacts",
                headers={"api-key": brevo_key, "Content-Type": "application/json"},
                json={
                    "email": email,
                    "attributes": {"FIRSTNAME": first_name, "LASTNAME": last_name},
                    "listIds": [int(os.getenv("BREVO_LIST_ID", "2"))],
                    "updateEnabled": True,
                },
                timeout=5,
            )
            _logger.info(f"Brevo sync {email}: {resp.status_code} {resp.text[:100]}")
        except Exception as e:
            _logger.warning(f"Brevo sync failed: {e}")

    @main_bp.route("/api/fcm-token", methods=["POST"])
    def register_fcm_token():
        """Register or update a user's FCM token and subscribe to plan topic."""
        from flask_login import current_user, login_required

        if not current_user.is_authenticated:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        token = data.get("token", "").strip()
        if not token:
            return jsonify({"error": "token required"}), 400

        sub = current_user.get_subscription()
        plan = sub["plan"] if sub else "basic"

        try:
            from src.services.firebase_push import migrate_user_topic
            migrate_user_topic(token, plan)
        except Exception as e:
            _logger.warning(f"FCM topic subscription failed: {e}")

        try:
            with get_conn() as conn:
                conn.execute(text("""
                    INSERT INTO user_fcm_tokens (user_id, token, updated_at)
                    VALUES (:uid, :token, :now)
                    ON CONFLICT (user_id, token) DO UPDATE SET updated_at = :now
                """), {"uid": current_user.id, "token": token,
                       "now": datetime.utcnow().isoformat()})
                conn.commit()
        except Exception as e:
            _logger.warning(f"Error saving FCM token: {e}")

        return jsonify({"ok": True, "topic": f"alerts-{plan}"}), 200

    app.register_blueprint(main_bp)

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html", dl_page_name="404", dl_section_name="error", dl_service_type="error", dl_web_area="public"), 404

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from web.i18n import get_translations
        from web.datalayer import get_datalayer_pageview

        # Detectar idioma: usuario autenticado > cookie > default
        if hasattr(current_user, 'language') and current_user.is_authenticated:
            lang = current_user.language or "es"
        else:
            lang = request.cookies.get("geo_lang", "es")

        # Build dataLayer pageview
        dl_pageview = get_datalayer_pageview(
            request.endpoint,
            view_args=request.view_args,
            request_args=request.args,
        )
        if dl_pageview:
            dl_pageview["language"] = lang
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                dl_pageview["userID"] = str(current_user.id)
                dl_pageview["userStatus"] = "loggedIn"
                sub = current_user.get_subscription() if hasattr(current_user, 'get_subscription') else None
                if sub and sub.get("status") in ("active", "trial", "cancelled_pending"):
                    dl_pageview["userPlan"] = sub["plan"]
                    dl_pageview["userType"] = "client"
                else:
                    dl_pageview["userPlan"] = ""
                    dl_pageview["userType"] = "prospect"
            else:
                dl_pageview["userID"] = ""
                dl_pageview["userStatus"] = "loggedOut"
                dl_pageview["userPlan"] = ""
                dl_pageview["userType"] = "prospect"

        return dict(
            t=get_translations(lang),
            lang=lang,
            dl_pageview=dl_pageview,
        )

    return app
