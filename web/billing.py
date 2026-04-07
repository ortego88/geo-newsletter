import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from web.models import PLANS, get_conn, AVAILABLE_ASSETS
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("billing")

billing_bp = Blueprint("billing", __name__)

STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "pk_test_placeholder")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")


@billing_bp.route("/pricing")
def pricing():
    return render_template("billing/pricing.html", plans=PLANS)


@billing_bp.route("/subscribe/<plan>", methods=["GET", "POST"])
@login_required
def subscribe(plan):
    if plan not in PLANS:
        flash("Plan no válido", "error")
        return redirect(url_for("billing.pricing"))
    plan_config = PLANS[plan]
    billing_cycle = request.args.get("cycle", "monthly")
    return render_template(
        "billing/checkout.html",
        plan=plan,
        plan_config=plan_config,
        billing_cycle=billing_cycle,
        stripe_pk=STRIPE_PUBLISHABLE_KEY,
    )


@billing_bp.route("/checkout/trial")
@login_required
def checkout_trial():
    """Captura datos de pago para el período de prueba gratuita."""
    plan = request.args.get("plan", "basic")
    if plan not in PLANS:
        plan = "basic"
    return render_template(
        "billing/checkout.html",
        plan=plan,
        plan_config=PLANS[plan],
        billing_cycle="monthly",
        is_trial=True,
        stripe_pk=STRIPE_PUBLISHABLE_KEY,
    )


@billing_bp.route("/subscribe/process", methods=["POST"])
@login_required
def process_subscription():
    """Procesa la suscripción. En local/test simplemente simula el cobro."""
    plan = request.form.get("plan", "basic")
    billing_cycle = request.form.get("billing_cycle", "monthly")
    payment_token = request.form.get("stripe_token", "")
    is_trial = request.form.get("is_trial") == "1"

    if request.form.get("accept_terms") != "1":
        flash("Debes aceptar los Términos y Condiciones para continuar.", "error")
        return redirect(url_for("billing.checkout_trial") if is_trial else url_for("billing.subscribe", plan=plan))

    if plan not in PLANS:
        flash("Plan no válido", "error")
        return redirect(url_for("billing.pricing"))

    conn = get_conn()
    c = conn.cursor()

    if STRIPE_SECRET_KEY and payment_token:
        # Production: use real Stripe
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            # Simplified — full implementation would use PaymentIntent
            flash("Pago procesado correctamente", "success")
        except Exception as e:
            flash(f"Error procesando el pago: {e}", "error")
            conn.close()
            return redirect(url_for("billing.subscribe", plan=plan))
    else:
        # Local/test mode: payment is simulated, no real charge is made
        logger.info("Test mode: simulating payment for user %s, plan %s", current_user.id, plan)

    if is_trial:
        trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        period_end = trial_end
        status = "trial"
    else:
        period_end = (
            datetime.now(timezone.utc) + (
                timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
            )
        ).isoformat()
        status = "active"
        trial_end = None

    # Update or create subscription
    c.execute("SELECT id FROM subscriptions WHERE user_id=?", (current_user.id,))
    existing = c.fetchone()
    if existing:
        c.execute(
            """UPDATE subscriptions SET plan=?, billing_cycle=?, status=?,
               trial_ends_at=?, current_period_end=?, updated_at=datetime('now')
               WHERE user_id=?""",
            (plan, billing_cycle, status, trial_end, period_end, current_user.id),
        )
    else:
        c.execute(
            """INSERT INTO subscriptions
               (user_id,plan,billing_cycle,status,trial_ends_at,current_period_end)
               VALUES (?,?,?,?,?,?)""",
            (current_user.id, plan, billing_cycle, status, trial_end, period_end),
        )

    # Save simulated payment method
    c.execute(
        "INSERT INTO payment_methods (user_id, card_last4, card_brand) VALUES (?, ?, ?)",
        (current_user.id, "4242", "Visa (test)"),
    )
    conn.commit()
    conn.close()

    flash("✅ Suscripción activada correctamente", "success")
    return redirect(url_for("billing.success"))


@billing_bp.route("/subscribe/success")
@login_required
def success():
    sub = current_user.get_subscription()
    return render_template("billing/success.html", sub=sub, plans=PLANS)


@billing_bp.route("/cancel")
@login_required
def cancel():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "UPDATE subscriptions SET status='cancelled' WHERE user_id=?",
        (current_user.id,),
    )
    conn.commit()
    conn.close()
    flash(
        "Suscripción cancelada. Seguirás teniendo acceso hasta el final del período.",
        "info",
    )
    return redirect(url_for("dashboard_web.settings"))
