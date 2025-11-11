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
from .models import Plan, CompanyPlan, StripeCredential, Payment, Company
import stripe
from datetime import timedelta
import pytz
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
        

    


def get_stripe_client(company):
    """Return stripe client for a specific company."""
    cred = StripeCredential.objects.get(company=company)
    return stripe, cred.api_key, cred.webhook_secret

def create_checkout_session(request, company, plan=None, amount=None, reason=None):
    """Create a Stripe checkout session for subscription or one-time payment."""
    stripe_client, api_key, webhook_secret = get_stripe_client(company)
    stripe_client.api_key = api_key

    # For subscription
    if plan:
        price_data = {
            'currency': 'usd',
            'product_data': {'name': f"{plan.name} ({plan.duration})"},
            'unit_amount': int(plan.price) * 100
        }
        mode = 'payment'
        metadata = {
            'company_id': company.id,
            'plan_id': plan.id
        }
        success_url = request.build_absolute_uri('/payment-success/')
        cancel_url = request.build_absolute_uri('/payment-cancel/')
    # For normal payment
    elif amount and reason:
        price_data = {
            'currency': 'usd',
            'product_data': {'name': reason},
            'unit_amount': int(amount * 100)
        }
        mode = 'payment'
        metadata = {
            'company_id': company.id,
            'reason': reason,
            'amount': amount
        }
        success_url = request.build_absolute_uri('/payment-success/')
        cancel_url = request.build_absolute_uri('/payment-cancel/')
    else:
        return HttpResponse("Invalid payment data", status=400)

    session = stripe_client.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            'price_data': price_data,
            'quantity': 1
        }],
        mode=mode,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata
    )
    return redirect(session.url, code=303)

def payment_success(request):
    return HttpResponse("✅ Payment successful!")

def payment_cancel(request):
    return HttpResponse("❌ Payment cancelled.")

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    print("📥 Stripe webhook received!")

    # We assume company is passed in metadata
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        print("❌ Webhook error:", str(e))
        return HttpResponse(status=400)

    # Handle checkout session completed
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session.get('metadata', {})
        company_id = metadata.get('company_id')

        if not company_id:
            print("❌ No company_id in metadata")
            return HttpResponse(status=400)

        try:
            company = Company.objects.get(id=company_id)
            # Subscription
            plan_id = metadata.get('plan_id')
            if plan_id:
                plan = Plan.objects.get(id=plan_id)
                CompanyPlan.objects.update_or_create(
                    company=company,
                    plan=plan,
                    defaults={'start_date': timezone.now(), 'end_date': None}
                )
                print(f"✅ {company.name} subscribed to {plan.name}")
            # One-time payment
            elif metadata.get('reason') and metadata.get('amount'):
                Payment.objects.create(
                    company=company,
                    reason=metadata['reason'],
                    amount=metadata['amount'],
                    transaction_id=session['id']
                )
                print(f"✅ Payment recorded for {company.name}")
        except Exception as e:
            print("💥 Error handling payment:", str(e))

    return HttpResponse(status=200)
