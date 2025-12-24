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
def create_checkout_session_for_service(request):
    try:
        company_id = request.data.get("company_id")
        email = request.data.get("email")
        amount = request.data.get("amount")
        reason = request.data.get("reason")

        # Call stripe function
        payment = create_stripe_checkout_for_service(
            company_id,
            email,
            amount,
            reason
        )

        return Response({"redirect_url": payment.url}, status=status.HTTP_303_SEE_OTHER)

    except ValueError as e:
        return Response({"error": str(e)}, status=400)

@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_checkout_session_for_subscription(request):
    try:
        company = Company.objects.filter(user=request.user).first()
        plan_id = request.data.get("plan_id")
        auto_renew = request.data.get("auto_renew")

        # Call stripe function
        payment = create_stripe_checkout_for_subscription(
            company.id,
            plan_id,
            auto_renew
        )

        return Response({"redirect_url": payment.url}, status=status.HTTP_303_SEE_OTHER)

    except ValueError as e:
        return Response({"error": str(e)}, status=400)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_stripe_connect(request):
    """API to start Stripe Connect onboarding."""
    company = getattr(request.user, 'company', None)
    if not company:
        return Response({"error": "Company not found for this user"}, status=404)
        
    try:
        onboarding_url = create_stripe_connect_account(company.id)
        return Response({"onboarding_url": onboarding_url}, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=400)

@api_view(["GET"])
@permission_classes([AllowAny])
def stripe_connect_success(request):
    """Handle successful onboarding redirect."""
    return Response({"message": "Successfully connected Stripe account. You can now receive payments."}, status=200)

@api_view(["GET"])
@permission_classes([AllowAny])
def stripe_connect_refresh(request):
    """Handle onboarding session refresh/retry."""
    return Response({"message": "The onboarding session expired. Please try again from your dashboard."}, status=400)

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    logger.info(f"Received webhook event with signature: {sig_header[:20]}...")

    # Use platform secret for verification
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        logger.info(f"✅ Webhook verified with secret: {webhook_secret[:10]}...")
    except Exception as e:
        logger.error(f"❌ Webhook verification failed: {str(e)}")
        return HttpResponse(status=400)

    logger.info(f"✅ Verified event: {event['type']}")

    data = event['data']['object']
    metadata = data.get('metadata', {})

    # Extract metadata
    payment_id = metadata.get('payment_id')
    company_id = metadata.get('company_id')
    plan_id = metadata.get('plan_id')
    auto_renew_meta = metadata.get('auto_renew')
    
    # Convert auto_renew string to boolean
    auto_renew = str(auto_renew_meta).lower() == 'true'

    logger.info(f"Webhook metadata - payment_id: {payment_id}, company_id: {company_id}, plan_id: {plan_id}, auto_renew: {auto_renew}")

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
        # Use platform API key
        stripe.api_key = settings.STRIPE_SECRET_KEY

        try:
            with transaction.atomic():
                # Update payment status
                payment.status = "success"
                payment.payment_date = timezone.now()
                # Store PaymentIntent ID as transaction_id if available
                payment.transaction_id = data.get('payment_intent') or data.get('id')
                
                # Capture Invoice URL if generated (available in mode="payment" with invoice_creation enabled)
                invoice_id = data.get('invoice')
                if invoice_id:
                    try:
                        inv = stripe.Invoice.retrieve(invoice_id)
                        payment.invoice_url = inv.hosted_invoice_url
                        logger.info(f"📄 Saved Invoice URL for Payment {payment.id}")
                    except Exception as e:
                        logger.error(f"Error retrieving invoice {invoice_id}: {e}")

                payment.save()
                
                logger.info(f"✅ Payment {payment.id} status updated to SUCCESS")

                # Save Stripe Customer and Payment Method for future auto-renewal
                customer_id = data.get('customer')
                if customer_id and company:
                    company.stripe_customer_id = customer_id
                    
                    # Try to get payment method from the session or payment intent
                    payment_intent_id = data.get('payment_intent')
                    if payment_intent_id:
                        try:
                            # Use the same API key used for the session
                            pi = stripe.PaymentIntent.retrieve(payment_intent_id, api_key=stripe.api_key)
                            if pi.get('payment_method'):
                                company.stripe_payment_method_id = pi.get('payment_method')
                                logger.info(f"💳 Saved Payment Method {pi.get('payment_method')} for Company {company.id}")
                            else:
                                logger.warning(f"⚠️ PaymentMethod not found on PaymentIntent {payment_intent_id}")
                        except Exception as e:
                            logger.error(f"Error retrieving PaymentIntent {payment_intent_id} for PM: {e}")
                    
                    company.save()
                    logger.info(f"👥 Saved Stripe Customer {customer_id} for Company {company.id}")
                else:
                    logger.warning(f"⚠️ No customer_id found in Stripe data for company {company_id if company_id else 'unknown'}")

                # =================== SUBSCRIPTION PAYMENT =========================
                if payment.type == "subscriptions":
                    logger.info(f"Processing subscription payment for company: {company.id}")

                    # Create or update subscription
                    subscription, created = Subscriptions.objects.get_or_create(
                        company=company,
                        defaults={
                            "plan": plan,
                            "auto_renew": auto_renew,
                        }
                    )

                    if not created:
                        # Subscription already exists → upgrade/renew
                        subscription.plan = plan
                        subscription.auto_renew = auto_renew
                        subscription.start = timezone.now()
                        subscription.active = True # Ensure it is active
                        logger.info(f"Updated existing subscription {subscription.id}")
                    else:
                        logger.info(f"Created new subscription {subscription.id}")

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
