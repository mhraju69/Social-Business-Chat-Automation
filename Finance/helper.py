from .models import Company, Payment, Plan
from django.http import Http404
from django.conf import settings
import stripe

def get_stripe_client():
    """Return platform Stripe client configuration."""
    return stripe, settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET

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

    stripe_client, api_key, webhook_secret = get_stripe_client()
    stripe_client.api_key = api_key

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
        "invoice_creation": {"enabled": True},
    }

    # If company has a connected account, we check if it's ready to receive money
    if company.stripe_connect_id:
        try:
            # Check account status on Stripe
            connected_acc = stripe_client.Account.retrieve(company.stripe_connect_id)
            
            # Only transfer if the account is verified for transfers
            if connected_acc.capabilities.get('transfers') == 'active':
                checkout_args["payment_intent_data"] = {
                    "transfer_data": {
                        "destination": company.stripe_connect_id,
                        "amount": int(float(amount) * 100),
                    }
                }
            else:
                print(f"⚠️ Warning: Company {company.id} has a connect_id but 'transfers' capability is NOT active yet.")
        except Exception as e:
            print(f"❌ Error checking connect account status: {e}")

    # Pass client email if provided
    if email:
        checkout_args["customer_email"] = email

    session = stripe_client.checkout.Session.create(**checkout_args)

    # Save Stripe session URL in Payment
    payment.url = session.url
    payment.save()

    return payment

def create_stripe_checkout_for_subscription(
    company_id,
    plan_id,
    auto_renew = True, # For native subscriptions, auto_renew is usually the default
    ):
    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        raise ValueError("Company not found")

    stripe_client, api_key, webhook_secret = get_stripe_client()
    plan = Plan.objects.filter(id=plan_id).first()

    if not plan:
        raise ValueError("Plan not found")

    stripe_client.api_key = api_key

    # ---------------- METADATA ----------------
    metadata = {
        "company_id": str(company.id),
        "type": "subscriptions",
        "plan_id": str(plan_id),
    }

    # Ensure company has a Stripe Customer ID
    if not company.stripe_customer_id:
        try:
            customer = stripe_client.Customer.create(
                email=company.user.email,
                name=company.name or "Unknown",
                metadata={"company_id": str(company.id)}
            )
            company.stripe_customer_id = customer.id
            company.save()
        except Exception as e:
            print(f"DEBUG: Error creating Stripe customer: {e}")

    # ---------------- STRIPE SUBSCRIPTION SETUP ----------------
    # If using Native Stripe Subscriptions, we use Price IDs
    # If stripe_price_id is missing, we create a temporary one (though usually these are pre-created)
    if not plan.stripe_price_id:
        # Fallback: create a recurring price on the fly if not exists
        # In a production app, you'd ideally have these IDs already in the Plan model
        try:
            # First ensure we have a product
            if not plan.stripe_product_id:
                product = stripe_client.Product.create(name=plan.get_name_display())
                plan.stripe_product_id = product.id
                plan.save()
            
            # Create a monthly recurring price (adjust interval based on plan.duration)
            interval = "month"
            if plan.duration == "years": interval = "year"
            elif plan.duration == "days": interval = "day"

            price = stripe_client.Price.create(
                unit_amount=int(float(plan.price) * 100),
                currency="eur",
                recurring={"interval": interval},
                product=plan.stripe_product_id,
            )
            plan.stripe_price_id = price.id
            plan.save()
        except Exception as e:
            raise ValueError(f"Failed to setup Stripe Price: {str(e)}")

    # ---------------- CREATE STRIPE CHECKOUT ----------------
    checkout_args = {
        "payment_method_types": ["card"],
        "line_items": [{"price": plan.stripe_price_id, "quantity": 1}],
        "mode": "subscription", # Changed from 'payment' to 'subscription'
        "success_url": "https://dashboard.talkfusion.ai/finance/success", # Update with your real URLs
        "cancel_url": "https://dashboard.talkfusion.ai/finance/cancel",
        "metadata": metadata,
        "subscription_data": {
            "metadata": metadata,
        },
        "customer": company.stripe_customer_id,
    }

    session = stripe_client.checkout.Session.create(**checkout_args)

    return session

def update_existing_subscriptions_to_new_price(plan_id):
    """
    Call this function whenever a Plan's price is updated in Django.
    It will find all active Stripe subscriptions for this plan and update them to the new price.
    """
    plan = Plan.objects.get(id=plan_id)
    if not plan.stripe_price_id:
        return False, "Plan has no Stripe Price ID"

    stripe_client, api_key, _ = get_stripe_client()
    stripe_client.api_key = api_key

    # Find all subscriptions in our DB using this plan that have a stripe_subscription_id
    active_subs = Subscriptions.objects.filter(plan=plan, active=True).exclude(stripe_subscription_id__isnull=True)
    
    success_count = 0
    fail_count = 0

    for sub in active_subs:
        try:
            # Retrieve the subscription from Stripe
            stripe_sub = stripe_client.Subscription.retrieve(sub.stripe_subscription_id)
            
            # Find the subscription item ID
            sub_item_id = stripe_sub['items']['data'][0]['id']

            # Update subscription with new price
            stripe_client.Subscription.modify(
                sub.stripe_subscription_id,
                items=[{
                    'id': sub_item_id,
                    'price': plan.stripe_price_id,
                }],
                proration_behavior='always_invoice', # Or 'create_prorations' depending on policy
            )
            success_count += 1
        except Exception as e:
            print(f"Error updating sub {sub.stripe_subscription_id}: {e}")
            fail_count += 1

    return True, f"Updated {success_count} subscriptions. Failed: {fail_count}."

def cancel_stripe_subscription(subscription_id, immediate=False):
    """
    Cancel a Stripe subscription.
    immediate=True -> Cancel right now.
    immediate=False -> Turn off auto-renew (cancel at period end).
    """
    stripe_client, api_key, _ = get_stripe_client()
    stripe_client.api_key = api_key

    try:
        if immediate:
            # Hard cancel
            deleted_subscription = stripe_client.Subscription.delete(subscription_id)
            return True, "Subscription cancelled immediately."
        else:
            # Turn off auto-renew (Stripe calls this 'cancel_at_period_end')
            updated_subscription = stripe_client.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
            return True, "Auto-renewal turned off. Access will continue until end of period."
    except Exception as e:
        return False, str(e)



def create_stripe_connect_account(company_id):
    """
    Create a Stripe Express account for a company and return an onboarding link.
    """
    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        raise ValueError("Company not found")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    # 1. Create the Connect Account if it doesn't exist
    if not company.stripe_connect_id:
        account = stripe.Account.create(
            type="express",
            country="DE", # বা আপনার ডিফল্ট কান্ট্রি
            email=company.user.email,
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            business_type="individual",
            metadata={"company_id": str(company.id)}
        )
        company.stripe_connect_id = account.id
        company.save()

    # 2. Create the Account Link (Onboarding URL)
    # এই লিঙ্কটি ৩-৫ মিনিট পর এক্সপায়ার হয়ে যায়, তাই এটি প্রতিবার নতুন জেনারেট করতে হয়
    account_link = stripe.AccountLink.create(
        account=company.stripe_connect_id,
        refresh_url="https://ape-in-eft.ngrok-free.app/api/finance/connect/refresh/", # ফেইল করলে বা এক্সপায়ার হলে এখানে যাবে
        return_url="https://ape-in-eft.ngrok-free.app/api/finance/connect/success/", # সাকসেস হলে এখানে যাবে
        type="account_onboarding",
    )

    return account_link.url

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
        stripe_client, api_key, _ = get_stripe_client()
        stripe_client.api_key = api_key

        # 2. Create Payment record
        payment = Payment.objects.create(
            company=company,
            type="subscriptions",
            amount=amount,
            reason=f"Auto-renewal for {plan.get_name_display()}",
            status="pending",
        )

        # 3. Create Invoice Item (This represents the line item on the invoice)
        try:
            stripe_client.InvoiceItem.create(
                customer=company.stripe_customer_id,
                amount=int(amount * 100),
                currency="eur",
                description=f"Auto-renewal for {plan.get_name_display()}",
                metadata={
                    "payment_id": str(payment.id),
                    "company_id": str(company.id),
                }
            )

            # 4. Create the Invoice
            invoice = stripe_client.Invoice.create(
                customer=company.stripe_customer_id,
                default_payment_method=company.stripe_payment_method_id,
                auto_advance=True, # Automatically attempt to pay
                metadata={
                    "payment_id": str(payment.id),
                    "type": "auto_renewal"
                }
            )

            # 5. Pay the Invoice
            finalized_invoice = stripe_client.Invoice.pay(invoice.id)

            if finalized_invoice.status == 'paid':
                payment.status = "success"
                payment.transaction_id = finalized_invoice.payment_intent
                payment.invoice_url = finalized_invoice.hosted_invoice_url # PDF/Hosted link
                payment.save()

                # 6. Deactivate old subscription
                subscription.active = False
                subscription.save()

                # 7. Create new subscription
                new_sub = Subscriptions.objects.create(
                    company=company,
                    plan=plan,
                    auto_renew=True,
                    active=True,
                    start=timezone.now()
                )
                
                print(f"✅ Successfully auto-renewed with Invoice for {company.user.email}")
                return new_sub, "Renewal successful"
            else:
                payment.status = "failed"
                payment.save()
                return None, f"Invoice payment failed with status: {finalized_invoice.status}"

        except stripe.error.CardError as e:
            payment.status = "failed"
            payment.save()
            return None, f"Card error: {str(e)}"
        except Exception as e:
            payment.status = "failed"
            payment.save()
            return None, f"Stripe Error: {str(e)}"
            
    except Exception as e:
        print(f"❌ Error during auto-renewal: {e}")
        return None, str(e)
