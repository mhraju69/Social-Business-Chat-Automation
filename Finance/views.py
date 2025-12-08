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
from datetime import timedelta
import stripe
from rest_framework.decorators import api_view,permission_classes
from Socials.consumers import send_alert
from decimal import Decimal
from .helper import *
import logging

logger = logging.getLogger(__name__)
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
        user = request.user
        if user.role == 'admin':
            plans = Plan.objects.all()  
        else:
            plans = Plan.objects.filter(custom=True).exclude(custom=True)

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

    logger.info(f"Received webhook event with signature: {sig_header[:20]}...")

    # Collect all webhook secrets
    webhook_secrets = [settings.STRIPE_WEBHOOK_SECRET]
    webhook_secrets += list(
        StripeCredential.objects.values_list('webhook_secret', flat=True)
    )

    event = None
    for secret in webhook_secrets:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
            logger.info(f"✅ Webhook verified with secret: {secret[:10]}...")
            break
        except Exception as e:
            logger.warning(f"Failed to verify with secret {secret[:10]}...: {str(e)}")
            continue

    if not event:
        logger.error("❌ Invalid Stripe signature for all known secrets.")
        return HttpResponse(status=400)

    logger.info(f"✅ Verified event: {event['type']}")

    data = event['data']['object']
    metadata = data.get('metadata', {})

    # Extract metadata
    payment_id = metadata.get('payment_id')
    company_id = metadata.get('company_id')
    plan_id = metadata.get('plan_id')

    logger.info(f"Webhook metadata - payment_id: {payment_id}, company_id: {company_id}, plan_id: {plan_id}")

    # Fetch objects
    payment = Payment.objects.filter(id=payment_id).first()
    company = Company.objects.filter(id=company_id).first()
    plan = Plan.objects.filter(id=plan_id).first() if plan_id else None

    # Validate
    if not payment:
        logger.error(f"❌ Payment not found with ID: {payment_id}")
        return HttpResponse(status=400)

    logger.info(f"Found payment: ID={payment.id}, Type={payment.type}, Current Status={payment.status}")

    if payment.type == "subscriptions" and not (company and plan):
        logger.error(f"❌ Missing company or plan for subscription payment. Company: {company}, Plan: {plan}")
        return HttpResponse(status=400)

    # ----------------------------------------------------------------------
    # ✔ SUCCESSFUL PAYMENT
    # ----------------------------------------------------------------------
    if event['type'] == 'checkout.session.completed':
        try:
            with transaction.atomic():
                # Update payment status
                payment.status = "success"
                payment.payment_date = timezone.now()
                payment.transaction_id = data.get('id')
                payment.save()
                
                logger.info(f"✅ Payment {payment.id} status updated to SUCCESS")

                # =================== SUBSCRIPTION PAYMENT =========================
                if payment.type == "subscriptions":
                    logger.info(f"Processing subscription payment for company: {company.id}")

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
                        logger.info(f"Updated existing subscription {subscription.id}")
                    else:
                        logger.info(f"Created new subscription {subscription.id}")

                    # Set end date automatically from plan duration
                    if hasattr(plan, "duration_days"):
                        subscription.end = subscription.start + timedelta(days=plan.duration_days)

                    subscription.save()

                    # Notify admins
                    for admin in User.objects.filter(is_staff=True):
                        send_alert(
                            admin,
                            "New subscription payment",
                            f"{payment.amount} USD received for {plan.get_name_display()} plan from {payment.company.user.email}",
                            "info"
                        )
                    
                    logger.info(f"✅ Subscription payment processed successfully")

                # =================== SERVICE PAYMENT =============================
                else:
                    logger.info(f"Processing service payment for company: {company.id}")
                    
                    send_alert(
                        payment.company.user,
                        "Payment Received",
                        f"{payment.amount} USD received for {payment.reason}",
                        "info"
                    )
                    
                    logger.info(f"✅ Service payment processed successfully")

        except Exception as e:
            logger.error(f"❌ Error processing successful payment: {str(e)}", exc_info=True)
            return HttpResponse(status=500)

    # ----------------------------------------------------------------------
    # ❌ FAILED PAYMENT
    # ----------------------------------------------------------------------
    elif event['type'] in [
        'payment_intent.payment_failed',
        'charge.failed',
        'checkout.session.async_payment_failed'
    ]:
        try:
            with transaction.atomic():
                payment.status = "failed"
                payment.payment_date = timezone.now()
                payment.save()
                
                logger.warning(f"⚠️ Payment {payment.id} marked as FAILED")

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
                        "Payment Failed",
                        f"{payment.amount} USD payment failed for {payment.reason}",
                        "warning"
                    )
        except Exception as e:
            logger.error(f"❌ Error processing failed payment: {str(e)}", exc_info=True)
            return HttpResponse(status=500)

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
    
