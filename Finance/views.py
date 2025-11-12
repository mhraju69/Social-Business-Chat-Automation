from rest_framework.response import Response
from rest_framework import status,permissions,generics
from rest_framework.views import APIView 
from rest_framework.permissions import IsAuthenticated,AllowAny
from .models import *
from .serializers import *
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
import stripe
from decimal import Decimal
from django.http import Http404
# Create your views here.

class StripeListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StripeSerializer

    def get_queryset(self):
        user = self.request.user
        company = getattr(user, 'company', None)
        if hasattr(company, 'first'):
            company = company.first()  # get actual Company instance
        return StripeCredential.objects.filter(company=company)

class StripeUpdateView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StripeSerializer

    def get_object(self):
        user = self.request.user
        company_qs = getattr(user, 'company', None)

        if hasattr(company_qs, 'first'):
            company = company_qs.first()
        else:
            company = company_qs

        if not company:
            raise serializers.ValidationError("User has no associated company.")

        try:
            stripe_obj = company.stripe  # OneToOneField reverse
        except ObjectDoesNotExist:
            raise serializers.ValidationError("Stripe object does not exist for this company.")

        return stripe_obj

class GetPlans(APIView):
    permission_classes = [AllowAny]
    serializer_class = PlanSerializers

    def get(self, request):
        plans = Plan.objects.all()  
        serializer = self.serializer_class(plans, many=True)  
        return Response(serializer.data)
    
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

def create_checkout_session(request, company_id, plan_id=None):
    """Create Stripe Checkout session for subscription or one-time payment."""
    try:
        company = Company.objects.get(id=company_id)
        cred = StripeCredential.objects.get(company=company)
    except (Company.DoesNotExist, StripeCredential.DoesNotExist):
        return HttpResponse("Company or Stripe credentials not found", status=404)

    # Determine if subscription
    is_subscription = bool(plan_id)

    if is_subscription:
        try:
            plan = Plan.objects.get(id=plan_id)
        except Plan.DoesNotExist:
            return HttpResponse("Plan not found", status=404)

        # Subscription uses ENV credentials
        stripe_client, api_key, webhook_secret = get_stripe_client(use_env=True)

        price_data = {
            'currency': 'usd',
            'product_data': {'name': f"{plan.get_name_display()} ({plan.get_duration_display()})"},
            'unit_amount': int(plan.price) * 100
        }

        metadata = {
            'type': 'subscription',
            'company_id': str(company.id),
            'plan_id': str(plan.id),
            'amount': str(plan.price)  # important for webhook
        }

    else:
        # One-time payment uses company credentials
        stripe_client, api_key, webhook_secret = get_stripe_client(company=company)
        amount = request.GET.get('amount', 5)
        reason = request.GET.get('reason', 'One-time Payment')

        price_data = {
            'currency': 'usd',
            'product_data': {'name': reason},
            'unit_amount': int(float(amount) * 100)
        }

        metadata = {
            'type': 'payment',
            'company_id': str(company.id),
            'reason': reason,
            'amount': str(amount)
        }

    stripe_client.api_key = api_key

    # Create checkout session
    session = stripe_client.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{'price_data': price_data, 'quantity': 1}],
        mode='payment',
        success_url=request.build_absolute_uri('/payment-success/'),
        cancel_url=request.build_absolute_uri('/payment-cancel/'),
        metadata=metadata
    )

    return redirect(session.url, code=303)

def payment_success(request):
    return HttpResponse("✅ Payment successful!")


def payment_cancel(request):
    return HttpResponse("❌ Payment cancelled.")

@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook for subscriptions and one-time payments."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    # Collect all webhook secrets
    webhook_secrets = [settings.STRIPE_WEBHOOK_SECRET]
    webhook_secrets += list(StripeCredential.objects.values_list('webhook_secret', flat=True))

    event = None
    for secret in webhook_secrets:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
            break
        except Exception:
            continue

    if not event:
        print("❌ Invalid Stripe signature for all known secrets.")
        return HttpResponse(status=400)

    print("✅ Verified event:", event['type'])
    data = event['data']['object']
    metadata = data.get('metadata', {})

    company_id = metadata.get('company_id')
    if not company_id:
        print("⚠️ Missing company_id in metadata.")
        return HttpResponse("Missing company_id", status=400)

    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        print(f"⚠️ Company {company_id} not found.")
        return HttpResponse("Company not found", status=404)

    # Amount handling
    raw_amount = metadata.get('amount', None)
    if raw_amount is not None:
        try:
            amount = Decimal(raw_amount)
        except Exception:
            amount = Decimal('0')
    else:
        # Fallback: get amount from Stripe session (in cents)
        amount_cents = data.get('amount_total') or data.get('amount')
        if amount_cents:
            amount = Decimal(amount_cents) / 100
        else:
            amount = Decimal('0')

    if event['type'] == 'checkout.session.completed':
        meta_type = metadata.get('type', '')

        if meta_type == 'subscription':
            plan_id = metadata.get('plan_id')
            plan = None
            if plan_id:
                try:
                    plan = Plan.objects.get(id=plan_id)
                except Plan.DoesNotExist:
                    print(f"⚠️ Plan {plan_id} not found.")
                    
            # Record payment
            Payment.objects.create(
                company=company,
                reason=f"Subscription: {plan.get_name_display() if plan else 'Unknown'}",
                amount=amount,
                type = 'subscriptions',
                transaction_id=data['id'],
                payment_date=timezone.now()
            )

            print(f"✅ Subscription activated for {company.name}, amount: {amount}")

        elif meta_type == 'payment':
            Payment.objects.create(
                company=company,
                reason=metadata.get('reason', 'Payment'),
                amount=amount,
                transaction_id=data['id'],
                payment_date=timezone.now()
            )
            print(f"✅ One-time payment recorded for {company.name}, amount: {amount}")

        else:
            print(f"⚠️ Unknown metadata type: {meta_type}")

    return HttpResponse(status=200)