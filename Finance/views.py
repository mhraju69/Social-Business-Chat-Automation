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
        type = request.data.get("type")
        company_id = request.data.get("company_id")
        email = request.data.get("email")
        plan_id = request.data.get("plan_id")
        amount = request.data.get("amount")
        reason = request.data.get("reason")
        method = request.data.get("method", "web")

        # Call stripe function
        payment = create_stripe_checkout(
            type,
            company_id,
            email,
            plan_id,
            amount,
            reason,
            method
        )

        # Validate company
        if not Company.objects.filter(id=company_id).exists():
            return Response({"error": "Company not found"}, status=404)

        # Validate plan only for subscription payments
        if type == "subscriptions":
            if not Plan.objects.filter(id=plan_id).exists():
                return Response({"error": "Plan not found"}, status=404)

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
    webhook_secrets += list(
        StripeCredential.objects.values_list('webhook_secret', flat=True)
    )

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

    # Extract metadata
    payment_id = metadata.get('payment_id')
    company_id = metadata.get('company_id')
    plan_id = metadata.get('plan_id')

    # Fetch objects
    payment = Payment.objects.filter(id=payment_id).first()
    company = Company.objects.filter(id=company_id).first()
    plan = Plan.objects.filter(id=plan_id).first()

    # Validate
    if not payment:
        print("❌ Payment not found in webhook metadata.")
        return HttpResponse(status=400)

    if payment.type == "subscriptions" and not (company and plan):
        print("❌ Missing company or plan for subscription payment.")
        return HttpResponse(status=400)

    # ----------------------------------------------------------------------
    # ✔ SUCCESSFUL PAYMENT
    # ----------------------------------------------------------------------
    if event['type'] == 'checkout.session.completed':
        payment.status = "success"
        payment.payment_date = timezone.now()
        payment.transaction_id = data.get('id')
        payment.save()

        # =================== SUBSCRIPTION PAYMENT =========================
        if payment.type == "subscriptions":

            # Create or update subscription
            subscription, created = Subscriptions.objects.get_or_create(
                company=company,
                defaults={
                    "plan": plan,
                }
            )

            if not created:
                # Subscription already exists → upgrade/renew
                subscription.plan = plan
                subscription.start = timezone.now()

            # Set end date automatically from plan duration
            if hasattr(plan, "duration_days"):
                subscription.end = subscription.start + timedelta(days=plan.duration_days)

            subscription.save()

            # Notify admins
            for admin in User.objects.filter(is_staff=True):
                send_alert(
                    admin,
                    "New subscription payment",
                    f"{payment.amount} USD received for subscription plan from {payment.company.user.email}",
                    "info"
                )

        # =================== SERVICE PAYMENT =============================
        else:
            send_alert(
                payment.company.user,
                "New service payment",
                f"{payment.amount} USD received for {payment.reason}",
                "info"
            )

    # ----------------------------------------------------------------------
    # ❌ FAILED PAYMENT
    # ----------------------------------------------------------------------
    elif event['type'] in [
        'payment_intent.payment_failed',
        'charge.failed',
        'checkout.session.async_payment_failed'
    ]:
        payment.status = "failed"
        payment.payment_date = timezone.now()
        payment.save()

        if payment.type == "subscriptions":
            for admin in User.objects.filter(is_staff=True):
                send_alert(
                    admin,
                    "Subscription payment failed",
                    f"{payment.amount} USD payment failed for subscription from {payment.company.user.email}",
                    "warning"
                )
        else:
            send_alert(
                payment.company.user,
                "Service payment failed",
                f"{payment.amount} USD payment failed for {payment.reason}",
                "warning"
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
 
class CheckPlan(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        company = getattr(request.user, 'company', None)

        paln = Subscriptions.objects.filter(company=company,active=True)
        
        return Response(SubscriptionSerializer(paln,many=True).data)
    
