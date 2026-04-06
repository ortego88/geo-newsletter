from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
from web.models import User, init_db

auth_bp = Blueprint("auth", __name__)


def _is_safe_redirect(url: str) -> bool:
    """Return True only if the URL is a relative path (no scheme/netloc)."""
    if not url:
        return False
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard_web.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.get_by_email(email)
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get("next", "")
            if _is_safe_redirect(next_page):
                return redirect(next_page)
            return redirect(url_for("dashboard_web.index"))
        flash("Email o contraseña incorrectos", "error")
    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard_web.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if not name or not email or not password:
            flash("Todos los campos son obligatorios", "error")
            return render_template("auth/register.html")
        if password != password2:
            flash("Las contraseñas no coinciden", "error")
            return render_template("auth/register.html")
        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres", "error")
            return render_template("auth/register.html")
        if User.get_by_email(email):
            flash("Ya existe una cuenta con ese email", "error")
            return render_template("auth/register.html")
        user = User.create(email, password, name)
        login_user(user, remember=True)
        flash(
            "Cuenta creada. Tienes 7 días de prueba gratuita. "
            "¡Añade tu método de pago para continuar!",
            "success",
        )
        return redirect(url_for("billing.checkout_trial"))
    return render_template("auth/register.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.landing"))
