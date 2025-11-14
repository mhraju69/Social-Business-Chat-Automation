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
from rest_framework.decorators import api_view,permission_classes
from Chat.consumers import send_alert
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

@csrf_exempt
@api_view(["GET"])
@permission_classes([AllowAny])
def create_checkout_session(request,**kwargs):
    """Create Stripe Checkout session for subscription or one-time payment."""
    try:
        type = request.data.get("type")
        method = request.data.get("method")
        email =request.data.get("email")
        plan_id = request.data.get("plan_id")
        company_id = request.data.get("company_id")
        
        company = Company.objects.get(id=company_id)
        
        
    except (Company.DoesNotExist, StripeCredential.DoesNotExist):
        return HttpResponse("Company or Stripe credentials not found", status=404)

    # Determine if subscription
    is_subscription = bool(plan_id)

    if type == 'subscriptions':
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

        payment = Payment.objects.create(company=company,type="subscriptions",amount=str(plan.price),reason=f"Subscriptions for {plan.get_name_display()}",status="pending")

        metadata = {
            "payment_id" : payment.id
        }

    elif type == 'services':

        # One-time payment uses company credentials
        cred = StripeCredential.objects.get(company=company)
        stripe_client, api_key, webhook_secret = get_stripe_client(company=company)
        amount = request.data.get('amount', 5)
        reason = request.data.get('reason', 'One-time Payment')

        if not email:
             return HttpResponse("Email is required for service payments", status=404)
        
        price_data = {
            'currency': 'usd',
            'product_data': {'name': reason},
            'unit_amount': int(float(amount) * 100)
        }

        payment = Payment.objects.create(company=company,type="services",amount=amount,reason=reason,status="pending",client=email)

        metadata = {
            "payment_id" : payment.id
        }
    else:
        return Response("Invalid type", status=500)

    stripe_client.api_key = api_key

    if method == "app":
        success_url = "https://www.youtube.com"
        cancel_url = "https://www.facebook.com"
    else:
        success_url = "https://www.facebook.com"
        cancel_url = "https://www.youtube.com"
        
    # Create checkout session
    session = stripe_client.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{'price_data': price_data, 'quantity': 1}],
        mode='payment',
        success_url= success_url,
        cancel_url= cancel_url,
        metadata=metadata
    )

    return Response({"redirect_url":session.url}, status=303)

@csrf_exempt
def stripe_webhook(request):
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

    # Fetch company if metadata has company_id
    payment_id = None
    payment = metadata.get('payment_id')
    if payment:
        try:
            payment = Payment.objects.get(id=payment)
        except Payment.DoesNotExist:
            return HttpResponse("Payment not found", status=404)

    # ----- Successful payment -----
    if event['type'] == 'checkout.session.completed' and payment:
            payment.status = "success"  
            payment.payment_date = timezone.now()  
            payment.transaction_id = data.get('id') 
            payment.save()  # save the changes
            
            # Notify admins
            if payment.type == "subscriptions":
                for admin in User.objects.filter(is_staff=True):

                    send_alert(
                        admin,
                        "New payment received",
                        f"{payment.amount} USD received for {payment.reason if payment else 'Unknown'} subscription plan from {getattr(payment.company.user, 'name', None) or payment.company.user.email}",
                        "info"
                    )
            else:
                send_alert(
                    payment.company.user,
                    "New payment received",
                    f"{payment.amount} USD received for {payment.reason}",
                    "info"
                )

    # ----- Failed payment -----
    elif event['type'] in ['payment_intent.payment_failed', 'charge.failed', 'checkout.session.async_payment_failed']:

        payment.status = "failed"  
        payment.payment_date = timezone.now()  
        payment.save()  

        if payment.type == "subscriptions":
                for admin in User.objects.filter(is_staff=True):
                    send_alert(
                        admin,
                        "New payment received",
                        f"{payment.amount} USD received for {payment.reason if payment else 'Unknown'} subscription plan from {getattr(payment.company.user, 'name', None) or payment.company.user.email}",
                        "info"
                    )
        else:
            send_alert(
                    payment.company.user,
                    "New payment received",
                    f"{payment.amount} USD received for {payment.reason}",
                    "info"
            )
                

    return HttpResponse(status=200)
