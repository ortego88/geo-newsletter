import time
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
from web.models import User, init_db, PLANS

auth_bp = Blueprint("auth", __name__)

_login_attempts: dict[str, list[float]] = {}
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 300


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    return len(attempts) >= _MAX_ATTEMPTS


def _record_attempt(ip: str):
    _login_attempts.setdefault(ip, []).append(time.time())


def _is_safe_redirect(url: str) -> bool:
    """Return True only if the URL is a relative path (no scheme/netloc)."""
    if not url:
        return False
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return _redirect_based_on_completion_status()

    if request.method == "POST":
        ip = request.headers.get("X-Real-IP", request.remote_addr)
        if _is_rate_limited(ip):
            flash("Demasiados intentos. Espera 5 minutos.", "error")
            return render_template("auth/login.html", dl_page_name="login", dl_section_name="login", dl_service_type="userLogin", dl_web_area="public")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.get_by_email(email)
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get("next", "")
            if _is_safe_redirect(next_page):
                return redirect(next_page)
            return _redirect_based_on_completion_status()
        _record_attempt(ip)
        flash("Email o contraseña incorrectos", "error")
    return render_template("auth/login.html", dl_page_name="login", dl_section_name="login", dl_service_type="userLogin", dl_web_area="public")


def _redirect_based_on_completion_status():
    """Redirige al usuario al siguiente paso incompleto del flujo de onboarding."""
    from web.models import get_conn
    from sqlalchemy import text

    sub = current_user.get_subscription()

    # Si no tiene suscripción O está cancelada completamente, a pricing o subscription page
    if not sub or sub["status"] not in ("active", "trial", "cancelled_pending"):
        # Si tiene suscripción cancelada (no pending), llevarlo a la página de suscripción
        if sub and sub["status"] == "cancelled":
            return redirect(url_for("dashboard_web.subscription"))
        return redirect(url_for("billing.pricing"))

    # Si no tiene método de pago, a checkout
    with get_conn() as conn:
        has_payment = conn.execute(
            text("SELECT 1 FROM payment_methods WHERE user_id = :uid LIMIT 1"),
            {"uid": current_user.id}
        ).fetchone()

    if not has_payment:
        return redirect(url_for("billing.checkout_trial", plan=sub["plan"], next_step="select_assets"))

    # Si no tiene activos seleccionados, a settings
    user_selected_assets = [a for a in (sub.get("selected_assets") or []) if a]
    if not user_selected_assets:
        return redirect(url_for("dashboard_web.settings", next_step="select_assets"))

    # Si completó todo, al dashboard
    return redirect(url_for("dashboard_web.index"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    import os
    if os.getenv("REGISTRATION_OPEN", "false").lower() not in ("true", "1", "yes"):
        return redirect("/pricing")
    if current_user.is_authenticated:
        # Si ya está autenticado, redirigir según el estado del flujo
        return _redirect_based_on_completion_status()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        plan = request.form.get("plan", "basic").strip()
        if plan not in PLANS:
            plan = "basic"
        if not name or not email or not password:
            flash("Todos los campos son obligatorios", "error")
            return render_template("auth/register.html", plan=plan)
        if password != password2:
            flash("Las contraseñas no coinciden", "error")
            return render_template("auth/register.html", plan=plan)
        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres", "error")
            return render_template("auth/register.html", plan=plan)
        if User.get_by_email(email):
            flash("Ya existe una cuenta con ese email", "error")
            return render_template("auth/register.html", plan=plan)
        VALID_LANGS = {'es', 'en', 'fr', 'de', 'it', 'pt', 'zh', 'ar'}
        preferred_lang = request.form.get("preferred_lang", "es").strip()
        if preferred_lang not in VALID_LANGS:
            preferred_lang = 'es'
        user = User.create(email, password, name, language=preferred_lang, plan=plan)
        login_user(user, remember=True)

        try:
            from src.services.transactional_email import send_welcome_email
            trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%d/%m/%Y")
            send_welcome_email(email, name, plan, trial_end)
        except Exception:
            pass

        flash(
            "Cuenta creada. Añade tus datos de pago y después selecciona los activos que quieres monitorear.",
            "info",
        )
        return redirect(url_for("billing.checkout_trial", plan=plan, next_step="select_assets"))
    plan = request.args.get("plan", "basic")
    if plan not in PLANS:
        plan = "basic"
    trial_end_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%d/%m/%Y")
    return render_template("auth/register.html", plan=plan, trial_end_date=trial_end_date, dl_page_name="register/step01/personalDetails", dl_section_name="register", dl_service_type="userRegister", dl_web_area="public", dl_process_type="register", dl_process_step="step01", dl_process_detail="personalDetails")



@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.landing"))
