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
from Socials.consumers import send_alert
from decimal import Decimal
from .helper import *
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
    
@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def create_checkout_session(request):
    try:
        payment = create_stripe_checkout(
            type=request.data.get("type"),
            company_id=request.data.get("company_id"),
            email=request.data.get("email"),
            plan_id=request.data.get("plan_id"),
            amount=request.data.get("amount"),
            reason=request.data.get("reason"),
            method=request.data.get("method", "web")
        )
        return Response({"redirect_url": payment.url}, status=303)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except StripeCredential.DoesNotExist:
        return Response({"error": "Stripe credentials not found"}, status=404)
    
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

@csrf_exempt
@api_view(["GET"])
@permission_classes([AllowAny])
def get_payment(request,payment_id):
    try:
        payment =Payment.objects.get(id=payment_id)
        return Response(PaymentSerializer(payment).data, status=200)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Payment.DoesNotExist:
        return Response({"error": "Payment not found"}, status=404)
 