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

    cred = StripeCredential.objects.get(company=company)
    return stripe, cred.api_key, cred.webhook_secret

def create_stripe_checkout_for_service(
    company_id,
    email,
    amount,
    reason
    ):
    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        raise ValueError("Company not found")

    # Try to get company-specific Stripe credentials first, fallback to environment if not found
    try:
        stripe_client, api_key, webhook_secret = get_stripe_client(company=company, use_env=False)
    except (StripeCredential.DoesNotExist, ValueError):
        stripe_client, api_key, webhook_secret = get_stripe_client(company=company, use_env=True)

    # ---------------- SERVICE PAYMENT ----------------
    if not email:
        raise ValueError("Email is required for service payments")

    amount = float(amount)
    if amount <= 0:
        raise ValueError("Invalid amount for service payment")

    price_data = {
        "currency": "eur",
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

    stripe_client.api_key = api_key

    # Success/cancel URLs
    success_url = "https://www.youtube.com"
    cancel_url = "https://www.facebook.com"

    # ---------------- METADATA ----------------
    metadata = {
        "payment_id": str(payment.id),
        "company_id": str(company.id),
        "type": "services",
        "email": email,
        "reason": reason,
        "amount": str(amount)
    }

    # ---------------- CREATE STRIPE CHECKOUT ----------------
    checkout_args = {
        "payment_method_types": ["card"],
        "line_items": [{"price_data": price_data, "quantity": 1}],
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata,
    }

    # Pass existing customer or email
    if company.stripe_customer_id:
        checkout_args["customer"] = company.stripe_customer_id
    elif email:
        checkout_args["customer_email"] = email
    elif company.user.email:
        checkout_args["customer_email"] = company.user.email

    session = stripe_client.checkout.Session.create(**checkout_args)

    # Save Stripe session URL in Payment
    payment.url = session.url
    payment.save()

    return payment

def create_stripe_checkout_for_subscription(
    company_id,
    plan_id,
    auto_renew = False,
    ):
    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        raise ValueError("Company not found")

    stripe_client, api_key, webhook_secret = get_stripe_client(company=company, use_env=True)
    plan = Plan.objects.filter(id=plan_id).first()

    if not plan:
        raise ValueError("Plan not found")

    price_data = {
        "currency": "eur",
        "product_data": {"name": plan.get_name_display()},
        "unit_amount": int(float(plan.price) * 100)
    }
    
    print(f"DEBUG: Plan={plan.get_name_display()}, Price={plan.price}, Unit Amount={price_data['unit_amount']}")

    payment = Payment.objects.create(
        company=company,
        client=company.user.email,
        type="subscriptions",
        amount=plan.price,
        reason=plan.get_name_display(),
        status="pending",
    )

    stripe_client.api_key = api_key

    # Success/cancel URLs
    success_url = "https://www.youtube.com"
    cancel_url = "https://www.facebook.com"

    # ---------------- METADATA ----------------
    metadata = {
        "payment_id": str(payment.id),
        "company_id": str(company.id),
        "type": "subscriptions",
        "plan_id": str(plan_id),
        "auto_renew": str(auto_renew).lower(),
    }

    # If auto-renewal is enabled, we tell Stripe to save the payment method for off-session use
    is_auto_renew_enabled = str(auto_renew).lower() == 'true'

    # Ensure company has a Stripe Customer ID before session creation
    # This is the most reliable way to get a customer_id back in the webhook
    if not company.stripe_customer_id:
        try:
            stripe_client.api_key = api_key
            customer = stripe_client.Customer.create(
                email=company.user.email,
                name=company.name,
                metadata={"company_id": str(company.id)}
            )
            company.stripe_customer_id = customer.id
            company.save()
            print(f"DEBUG: Created new Stripe Customer ID: {customer.id}")
        except Exception as e:
            print(f"DEBUG: Error creating Stripe customer: {e}")

    # ---------------- CREATE STRIPE CHECKOUT ----------------
    checkout_args = {
        "payment_method_types": ["card"],
        "line_items": [{"price_data": price_data, "quantity": 1}],
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata,
    }

    if company.stripe_customer_id:
        checkout_args["customer"] = company.stripe_customer_id
    else:
        # Emergency fallback
        checkout_args["customer_email"] = company.user.email

    if is_auto_renew_enabled:
        checkout_args["payment_intent_data"] = {
            "setup_future_usage": "off_session"
        }

    session = stripe_client.checkout.Session.create(**checkout_args)

    # Save Stripe session URL in Payment
    payment.url = session.url
    payment.save()
    return payment



def process_auto_renewal(company_id):
    """
    Check if a company's subscription has expired and needs auto-renewal.
    If auto-renewal is enabled and payment details exist, attempt to charge and renew.
    """
    from .models import Subscriptions, Payment
    from django.utils import timezone
    
    try:
        company = Company.objects.get(id=company_id)
        # Find the most recent expired but auto-renewable subscription
        subscription = Subscriptions.objects.filter(
            company=company,
            active=True,
            auto_renew=True,
            end__lt=timezone.now()
        ).order_by('-end').first()

        if not subscription:
            return None, "No active expired subscription found with auto-renew enabled."

        if not company.stripe_customer_id or not company.stripe_payment_method_id:
            return None, "Missing Stripe customer or payment method for auto-charge."

        plan = subscription.plan
        amount = float(plan.price)
        
        # 1. Initialize Stripe
        stripe_client, api_key, _ = get_stripe_client(use_env=True)
        stripe_client.api_key = api_key

        # 2. Create Payment record
        payment = Payment.objects.create(
            company=company,
            type="subscriptions",
            amount=amount,
            reason=f"Auto-renewal for {plan.get_name_display()}",
            status="pending",
        )

        # 3. Attempt Payment Intent (Off-Session)
        try:
            intent = stripe_client.PaymentIntent.create(
                amount=int(amount * 100),
                currency="eur",
                customer=company.stripe_customer_id,
                payment_method=company.stripe_payment_method_id,
                off_session=True,
                confirm=True,
                metadata={
                    "payment_id": str(payment.id),
                    "company_id": str(company.id),
                    "plan_id": str(plan.id),
                    "type": "auto_renewal"
                }
            )

            if intent.status == 'succeeded':
                payment.status = "success"
                payment.transaction_id = intent.id
                payment.save()

                # 4. Deactivate old subscription
                subscription.active = False
                subscription.save()

                # 5. Create new subscription
                new_sub = Subscriptions.objects.create(
                    company=company,
                    plan=plan,
                    auto_renew=True,
                    active=True,
                    start=timezone.now()
                )
                
                print(f"✅ Successfully auto-renewed subscription for {company.user.email}")
                return new_sub, "Renewal successful"
            else:
                payment.status = "failed"
                payment.save()
                return None, f"Payment failed with status: {intent.status}"

        except stripe.error.CardError as e:
            payment.status = "failed"
            payment.save()
            return None, f"Card error: {str(e)}"
            
    except Exception as e:
        print(f"❌ Error during auto-renewal: {e}")
        return None, str(e)
