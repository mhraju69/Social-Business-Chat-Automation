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
    except StripeCredential.DoesNotExist:
        return Response({"error": "Stripe credentials not found"}, status=404)

@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def create_checkout_session_for_subscription(request):
    try:
        company_id = request.data.get("company_id")
        plan_id = request.data.get("plan_id")
        auto_renew = request.data.get("auto_renew")

        # Call stripe function
        payment = create_stripe_checkout_for_subscription(
            company_id,
            plan_id,
            auto_renew
        )

        return Response({"redirect_url": payment.url}, status=status.HTTP_303_SEE_OTHER)

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
        # Set API key for retrieval - use system key as default
        stripe.api_key = settings.STRIPE_SECRET_KEY
        if payment.type == "services":
            try:
                cred = StripeCredential.objects.get(company=company)
                stripe.api_key = cred.api_key
            except StripeCredential.DoesNotExist:
                pass

        try:
            with transaction.atomic():
                # Update payment status
                payment.status = "success"
                payment.payment_date = timezone.now()
                # Store PaymentIntent ID as transaction_id if available
                payment.transaction_id = data.get('payment_intent') or data.get('id')
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
                            pi = stripe.PaymentIntent.retrieve(payment_intent_id)
                            if pi.get('payment_method'):
                                company.stripe_payment_method_id = pi.get('payment_method')
                                logger.info(f"💳 Saved Payment Method {pi.get('payment_method')} for Company {company.id}")
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
    
class CreateSubscriptionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)
        plan = request.data.get('plan_id')
        if not plan:
            return Response({"error": "Plan ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        plan = Plan.objects.filter(id=plan).first()
        if not plan:
            return Response({"error": "Plan not found"}, status=status.HTTP_404_NOT_FOUND)
        subscriptions = Subscriptions.objects.create(company=company, plan=plan)
        serializer = SubscriptionSerializer(subscriptions)
        return Response(serializer.data)