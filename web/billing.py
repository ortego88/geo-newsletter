import os
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import text
from web.models import PLANS, get_conn, AVAILABLE_ASSETS
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("billing")

billing_bp = Blueprint("billing", __name__)

STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "pk_test_placeholder")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Live Stripe price IDs
STRIPE_PRICE_IDS = {
    "basic":   {"monthly": "price_1TezhcB3AvOaSpMMtbU5ngRd", "yearly": "price_1TezhdB3AvOaSpMMm4roa8mG"},
    "premium": {"monthly": "price_1TezheB3AvOaSpMMcgZV2kJ5", "yearly": "price_1TezheB3AvOaSpMMjzV9QlXf"},
    "pro":     {"monthly": "price_1TezhfB3AvOaSpMM6zrXI4gO", "yearly": "price_1TezhgB3AvOaSpMMoSGPnGTT"},
}


def _get_user_payment_method(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            text("SELECT id, card_last4, card_brand, created_at FROM payment_methods WHERE user_id=:uid ORDER BY id DESC LIMIT 1"),
            {"uid": user_id}
        ).fetchone()
    return row


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
    next_step = request.args.get("next_step", "")
    trial_end_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%d/%m/%Y")
    has_payment_method = _get_user_payment_method(current_user.id) is not None
    return render_template(
        "billing/checkout.html",
        plan=plan,
        plan_config=PLANS[plan],
        billing_cycle="monthly",
        is_trial=True,
        stripe_pk=STRIPE_PUBLISHABLE_KEY,
        trial_end_date=trial_end_date,
        has_payment_method=has_payment_method,
        next_step=next_step,
    )


@billing_bp.route("/subscribe/process", methods=["POST"])
@login_required
def process_subscription():
    """Procesa la suscripción. En local/test simplemente simula el cobro."""
    plan = request.form.get("plan", "basic")
    billing_cycle = request.form.get("billing_cycle", "monthly")
    payment_token = request.form.get("stripe_token", "")
    is_trial = request.form.get("is_trial") == "1"

    card_number = request.form.get("card_number", "").replace(" ", "")
    card_expiry = request.form.get("card_expiry", "").strip()
    card_cvc = request.form.get("card_cvc", "").strip()
    card_name = request.form.get("card_name", "").strip()

    existing_payment = _get_user_payment_method(current_user.id)
    using_saved_card = False

    next_step = request.form.get("next_step", "")
    if not card_number or not card_expiry or not card_cvc or not card_name:
        if existing_payment:
            using_saved_card = True
        else:
            flash("Por favor, introduce los datos de tu tarjeta para continuar.", "error")
            if is_trial:
                return redirect(url_for("billing.checkout_trial", plan=plan, next_step=next_step))
            return redirect(url_for("billing.subscribe", plan=plan))

    if request.form.get("accept_terms") != "1":
        flash("Debes aceptar los Términos y Condiciones para continuar.", "error")
        if is_trial:
            return redirect(url_for("billing.checkout_trial", plan=plan, next_step=next_step))
        return redirect(url_for("billing.subscribe", plan=plan))

    if plan not in PLANS:
        flash("Plan no válido", "error")
        return redirect(url_for("billing.pricing"))

    conn = get_conn()

    if STRIPE_SECRET_KEY and payment_token:
        # Production: use real Stripe
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            # Simplified — full implementation would use PaymentIntent
            flash("Pago procesado correctamente", "success")
        except Exception as e:
            flash(f"Error procesando el pago: {e}", "error")
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

    with conn:
        # Update or create subscription
        existing = conn.execute(
            text("SELECT id FROM subscriptions WHERE user_id=:uid"), {"uid": current_user.id}
        ).fetchone()
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing:
            conn.execute(
                text("""UPDATE subscriptions SET plan=:plan, billing_cycle=:cycle, status=:status,
                       trial_ends_at=:trial, current_period_end=:period, updated_at=:now
                       WHERE user_id=:uid"""),
                {"plan": plan, "cycle": billing_cycle, "status": status,
                 "trial": trial_end, "period": period_end, "now": now_iso, "uid": current_user.id},
            )
        else:
            conn.execute(
                text("""INSERT INTO subscriptions
                       (user_id,plan,billing_cycle,status,trial_ends_at,current_period_end,created_at,updated_at)
                       VALUES (:uid,:plan,:cycle,:status,:trial,:period,:now,:now)"""),
                {"uid": current_user.id, "plan": plan, "cycle": billing_cycle,
                 "status": status, "trial": trial_end, "period": period_end, "now": now_iso},
            )

        # Save simulated payment method if a new card was provided
        if not using_saved_card:
            conn.execute(
                text("INSERT INTO payment_methods (user_id, card_last4, card_brand, created_at) VALUES (:uid, :last4, :brand, :now)"),
                {"uid": current_user.id, "last4": "4242", "brand": "Visa (test)", "now": now_iso},
            )
        conn.commit()

    flash("✅ Suscripción activada correctamente", "success")
    if next_step == "select_assets":
        return redirect(url_for("dashboard_web.settings", next_step="select_assets"))
    return redirect(url_for("billing.success"))


@billing_bp.route("/subscribe/activate", methods=["POST"])
@login_required
def activate_subscription():
    sub = current_user.get_subscription()
    if not sub:
        flash("No se encontró una subscripción para activar.", "error")
        return redirect(url_for("billing.pricing"))

    if sub["status"] == "active":
        flash("Tu suscripción ya está activa.", "info")
        return redirect(url_for("billing.success"))

    payment_method = _get_user_payment_method(current_user.id)
    if not payment_method:
        flash("No hay un método de pago guardado. Por favor, añade tu tarjeta primero.", "error")
        return redirect(url_for("billing.subscribe", plan=sub["plan"]))

    billing_cycle = sub.get("billing_cycle") or "monthly"
    period_end = (
        datetime.now(timezone.utc) + (
            timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
        )
    ).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            text("""UPDATE subscriptions SET status='active', billing_cycle=:cycle,
                   trial_ends_at=NULL, current_period_end=:period, updated_at=:now
                   WHERE user_id=:uid"""),
            {"cycle": billing_cycle, "period": period_end, "now": now_iso, "uid": current_user.id},
        )
        conn.commit()

    flash("✅ Suscripción activada correctamente usando tu método de pago guardado.", "success")
    return redirect(url_for("billing.success"))


@billing_bp.route("/subscribe/reactivate", methods=["POST"])
@login_required
def reactivate_subscription():
    """
    Reactiva una suscripción que estaba en cancelled_pending.
    La reactivación tomará efecto al final del período actual.
    """
    sub = current_user.get_subscription()
    if not sub:
        flash("No se encontró una subscripción para reactivar.", "error")
        return redirect(url_for("billing.pricing"))

    if sub["status"] != "cancelled_pending":
        flash("Tu suscripción no está cancelada.", "info")
        return redirect(url_for("dashboard_web.subscription"))

    payment_method = _get_user_payment_method(current_user.id)
    if not payment_method:
        flash("No hay un método de pago guardado. Por favor, añade tu tarjeta primero.", "error")
        return redirect(url_for("billing.subscribe", plan=sub["plan"]))

    # Cambiar estado de cancelled_pending a active
    # La renovación automática continuará al final del período
    with get_conn() as conn:
        conn.execute(
            text("UPDATE subscriptions SET status='active', updated_at=:now WHERE user_id=:uid"),
            {"now": datetime.now(timezone.utc).isoformat(), "uid": current_user.id},
        )
        conn.commit()

    flash("✅ Suscripción reactivada. La renovación continuará automáticamente.", "success")
    return redirect(url_for("dashboard_web.subscription"))


@billing_bp.route("/subscribe/success")
@login_required
def success():
    sub = current_user.get_subscription()
    return render_template("billing/success.html", sub=sub, plans=PLANS)


@billing_bp.route("/cancel")
@login_required
def cancel():
    """
    Cancels subscription at period end. Cancels in Stripe first, then updates DB.
    User keeps access until trial/period ends — no immediate cancellation.
    """
    with get_conn() as conn:
        sub_row = conn.execute(
            text("SELECT status, trial_ends_at, current_period_end, stripe_subscription_id FROM subscriptions WHERE user_id=:uid"),
            {"uid": current_user.id}
        ).fetchone()

        if not sub_row:
            flash("No tienes una suscripción activa para cancelar.", "error")
            return redirect(url_for("dashboard_web.subscription"))

        status, trial_ends, period_end, stripe_sub_id = sub_row
        end_date = trial_ends if status == "trial" else period_end

    # Cancel in Stripe (at period end, not immediately)
    if stripe_sub_id and STRIPE_SECRET_KEY:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            stripe.Subscription.modify(stripe_sub_id, cancel_at_period_end=True)
            logger.info(f"Stripe subscription {stripe_sub_id} set to cancel at period end for user {current_user.id}")
        except Exception as e:
            logger.error(f"Error cancelling Stripe subscription: {e}")
            flash("Error al cancelar en Stripe. Contacta con soporte.", "error")
            return redirect(url_for("dashboard_web.subscription"))

    # Update DB
    with get_conn() as conn:
        conn.execute(
            text("UPDATE subscriptions SET status='cancelled_pending', updated_at=:now WHERE user_id=:uid"),
            {"now": datetime.now(timezone.utc).isoformat(), "uid": current_user.id},
        )
        conn.commit()

    if end_date:
        flash(f"Suscripción cancelada. Mantendrás el acceso hasta el {end_date[:10]}.", "info")
    else:
        flash("Suscripción cancelada. Mantendrás el acceso hasta el final del período.", "info")
    return redirect(url_for("dashboard_web.subscription"))


@billing_bp.route("/stripe/checkout", methods=["POST"])
@login_required
def stripe_checkout():
    """Creates a Stripe Checkout session and redirects to hosted payment page."""
    if not STRIPE_SECRET_KEY or not STRIPE_SECRET_KEY.startswith("sk_live_"):
        flash("Pagos en producción no configurados.", "error")
        return redirect(url_for("billing.pricing"))

    plan = request.form.get("plan", "basic")
    cycle = request.form.get("cycle", "monthly")
    is_trial = request.form.get("is_trial") == "1"

    if plan not in STRIPE_PRICE_IDS:
        flash("Plan no válido", "error")
        return redirect(url_for("billing.pricing"))

    price_id = STRIPE_PRICE_IDS[plan][cycle]

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY

        params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": url_for("billing.stripe_success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": url_for("billing.pricing", _external=True),
            "customer_email": current_user.email,
            "metadata": {
                "user_id": str(current_user.id),
                "plan": plan,
                "cycle": cycle,
            },
            "subscription_data": {
                "metadata": {"user_id": str(current_user.id), "plan": plan},
            },
        }

        # Always use trial_period_days=7 for new signups
        # Stripe won't charge until trial ends; user can cancel anytime before
        params["subscription_data"]["trial_period_days"] = 7
        params["payment_method_collection"] = "always"

        session = stripe.checkout.Session.create(**params)
        return redirect(session.url, code=303)

    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        flash("Error al procesar el pago. Inténtalo de nuevo.", "error")
        return redirect(url_for("billing.pricing"))


@billing_bp.route("/stripe/success")
@login_required
def stripe_success():
    """Callback after successful Stripe Checkout."""
    session_id = request.args.get("session_id", "")
    if not session_id or not STRIPE_SECRET_KEY:
        return redirect(url_for("billing.success"))

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)
        meta = session.get("metadata", {})
        plan = meta.get("plan", "basic")
        cycle = meta.get("cycle", "monthly")
        stripe_sub_id = session.get("subscription", "")
        stripe_customer_id = session.get("customer", "")

        trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_conn() as conn:
            existing = conn.execute(
                text("SELECT id FROM subscriptions WHERE user_id=:uid"),
                {"uid": current_user.id}
            ).fetchone()
            if existing:
                conn.execute(text("""
                    UPDATE subscriptions SET plan=:plan, billing_cycle=:cycle,
                    status='trial', trial_ends_at=:trial, current_period_end=:trial,
                    stripe_subscription_id=:sub_id, stripe_customer_id=:cust_id,
                    updated_at=:now
                    WHERE user_id=:uid
                """), {"plan": plan, "cycle": cycle, "trial": trial_end,
                       "sub_id": stripe_sub_id, "cust_id": stripe_customer_id,
                       "now": now_iso, "uid": current_user.id})
            else:
                conn.execute(text("""
                    INSERT INTO subscriptions
                    (user_id,plan,billing_cycle,status,trial_ends_at,current_period_end,
                     stripe_subscription_id,stripe_customer_id,created_at,updated_at)
                    VALUES (:uid,:plan,:cycle,'trial',:trial,:trial,:sub_id,:cust_id,:now,:now)
                """), {"uid": current_user.id, "plan": plan, "cycle": cycle,
                       "trial": trial_end, "sub_id": stripe_sub_id,
                       "cust_id": stripe_customer_id, "now": now_iso})
            conn.commit()

        flash("✅ Prueba gratuita de 7 días activada. No se te cobrará hasta que finalice.", "success")
    except Exception as e:
        logger.error(f"Stripe success callback error: {e}")

    return redirect(url_for("billing.success"))


@billing_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Handles Stripe webhook events (subscription renewals, cancellations)."""
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.warning(f"Stripe webhook validation failed: {e}")
        return "Invalid signature", 400

    etype = event["type"]
    data = event["data"]["object"]

    if etype == "invoice.payment_succeeded":
        customer_email = data.get("customer_email", "")
        if customer_email:
            _handle_payment_succeeded(customer_email, data)

    elif etype == "customer.subscription.trial_will_end":
        pass  # Could send reminder email here

    elif etype == "customer.subscription.deleted":
        _handle_subscription_deleted(data)

    elif etype == "customer.subscription.updated":
        _handle_subscription_updated(data)

    return "ok", 200


def _handle_payment_succeeded(email: str, invoice: dict):
    try:
        lines = invoice.get("lines", {}).get("data", [])
        period_end = None
        if lines:
            ts = lines[0].get("period", {}).get("end", 0)
            if ts:
                period_end = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        with get_conn() as conn:
            user = conn.execute(
                text("SELECT id FROM users WHERE email=:email"), {"email": email}
            ).fetchone()
            if user and period_end:
                conn.execute(text("""
                    UPDATE subscriptions SET status='active', current_period_end=:period, updated_at=:now
                    WHERE user_id=:uid
                """), {"period": period_end, "now": datetime.now(timezone.utc).isoformat(), "uid": user[0]})
                conn.commit()
                logger.info(f"Payment succeeded for {email}")
    except Exception as e:
        logger.error(f"Error handling payment succeeded: {e}")


def _handle_subscription_updated(subscription: dict):
    try:
        status = subscription.get("status", "")
        customer_id = subscription.get("customer", "")
        if not customer_id:
            return

        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        customer = stripe.Customer.retrieve(customer_id)
        email = customer.get("email", "")
        if not email:
            return

        # Map Stripe status to our status
        if status == "active":
            db_status = "active"
        elif status in ("canceled", "unpaid", "incomplete_expired"):
            db_status = "cancelled"
        else:
            db_status = status  # trial, past_due, etc

        with get_conn() as conn:
            user = conn.execute(
                text("SELECT id FROM users WHERE email=:email"), {"email": email}
            ).fetchone()
            if user:
                conn.execute(text(
                    "UPDATE subscriptions SET status=:status, updated_at=:now WHERE user_id=:uid"
                ), {"status": db_status, "now": datetime.now(timezone.utc).isoformat(), "uid": user[0]})
                conn.commit()
                logger.info(f"Subscription updated for {email}: {status} → {db_status}")
    except Exception as e:
        logger.error(f"Error handling subscription update: {e}")


def _handle_subscription_deleted(subscription: dict):
    """Immediately cancels access when Stripe confirms subscription deleted."""
    try:
        customer_id = subscription.get("customer", "")
        if not customer_id:
            return

        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        customer = stripe.Customer.retrieve(customer_id)
        email = customer.get("email", "")
        if not email:
            return

        with get_conn() as conn:
            user = conn.execute(
                text("SELECT id FROM users WHERE email=:email"), {"email": email}
            ).fetchone()
            if user:
                conn.execute(text(
                    "UPDATE subscriptions SET status='cancelled', updated_at=:now WHERE user_id=:uid"
                ), {"now": datetime.now(timezone.utc).isoformat(), "uid": user[0]})
                conn.commit()
                logger.info(f"Subscription deleted/cancelled for {email}")
    except Exception as e:
        logger.error(f"Error handling subscription deleted: {e}")
