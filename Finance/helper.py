from .models import Company, StripeCredential, Payment, Plan
from django.http import Http404
from django.conf import settings
import stripe

def get_stripe_client(company=None, use_env=False):
    """Return Stripe client configuration."""
    if use_env:
        # Use global environment Stripe credentials
        return stripe, settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET

    if not company:
        raise ValueError("Company is required for company-based Stripe credentials")

    try:
        cred = StripeCredential.objects.get(company=company)
        return stripe, cred.api_key, cred.webhook_secret
    except StripeCredential.DoesNotExist:
        raise Http404("Stripe credentials not found for this company.")

def create_stripe_checkout(
    type,
    company_id,
    email=None,
    plan_id=None,
    amount=None,
    reason=None,
    method="web"
    ):
    """
    Create a Stripe Checkout session and return the session URL.
    Supports both subscription and service payments.
    """

    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        raise ValueError("Company not found")

    stripe_client, api_key, webhook_secret = get_stripe_client(company=company if type=="services" else None, use_env=True)

    # ---------------- SUBSCRIPTION PAYMENT ----------------
    if type == "subscriptions":
        if not plan_id:
            raise ValueError("Plan ID is required for subscriptions")

        try:
            plan = Plan.objects.get(id=plan_id)
        except Plan.DoesNotExist:
            raise ValueError("Plan not found")

        unit_amount = int(float(plan.price) * 100)
        if unit_amount <= 0:
            raise ValueError("Invalid plan price")

        price_data = {
            "currency": "usd",
            "product_data": {"name": f"{plan.get_name_display()} ({plan.get_duration_display()})"},
            "unit_amount": unit_amount
        }

        payment = Payment.objects.create(
            company=company,
            type="subscriptions",
            amount=plan.price,
            reason=f"Subscription for {plan.get_name_display()}",
            status="pending",
        )

    # ---------------- SERVICE PAYMENT ----------------
    elif type == "services":
        if not email:
            raise ValueError("Email is required for service payments")

        cred = StripeCredential.objects.get(company=company)

        amount = float(amount or 5)
        if amount <= 0:
            raise ValueError("Invalid amount for service payment")

        price_data = {
            "currency": "usd",
            "product_data": {"name": reason or "One-time Payment"},
            "unit_amount": int(amount * 100)
        }

        payment = Payment.objects.create(
            company=company,
            client=email,
            type="services",
            amount=amount,
            reason=reason or "One-time Payment",
            status="pending",
        )
        plan = None  # No plan for service payments

    else:
        raise ValueError("Invalid payment type")

    stripe_client.api_key = api_key

    # Success/cancel URLs
    success_url = "https://www.youtube.com" if method == "app" else "https://www.facebook.com"
    cancel_url = "https://www.facebook.com" if method == "app" else "https://www.youtube.com"

    # ---------------- METADATA ----------------
    metadata = {
        "payment_id": str(payment.id),
        "company_id": str(company.id),
        "plan_id": str(plan.id) if plan else "",
        "type": type,
        "email": email or "",
        "reason": reason or "",
        "amount": str(amount),
        "method": method
    }

    # ---------------- CREATE STRIPE CHECKOUT ----------------
    session = stripe_client.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price_data": price_data, "quantity": 1}],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata
    )

    # Save Stripe session URL in Payment
    payment.url = session.url
    payment.save()

    return payment
