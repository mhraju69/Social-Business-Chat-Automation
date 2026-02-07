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
import traceback
from Accounts.utils import get_company_user

logger = logging.getLogger(__name__)
# Create your views here.

class GetPlans(APIView):
    permission_classes = [AllowAny]
    serializer_class = PlanSerializers

    def get(self, request):
        plans = Plan.objects.filter(custom=False)  
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
        target_user = get_company_user(request.user)
        company = Company.objects.filter(user=target_user).first()
        plan_id = request.data.get("plan_id")

        if not company:
            return Response({"error": "Company not found"}, status=404)

        # Call stripe function - returns Stripe Session object
        session = create_stripe_checkout_for_subscription(
            company.id,
            plan_id
        )

        return Response({"redirect_url": session.url}, status=status.HTTP_303_SEE_OTHER)

    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        return Response({"error": f"Internal error: {str(e)}"}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_stripe_connect(request):
    """API to start Stripe Connect onboarding."""
    # ... (same as before)
    target_user = get_company_user(request.user)
    company = getattr(target_user, 'company', None)
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
    return redirect(f"{settings.FRONTEND_URL}/user/settings")

@api_view(["GET"])
@permission_classes([AllowAny])
def stripe_connect_refresh(request):
    """Handle onboarding session refresh/retry."""
    return HttpResponse("The onboarding session expired. Please try again from your dashboard.", status=400)

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        logger.error(f"❌ Webhook verification failed: {str(e)}")
        return HttpResponse(status=400)

    data = event['data']['object']
    metadata = data.get('metadata', {})
    stripe.api_key = settings.STRIPE_SECRET_KEY

    # ----------------------------------------------------------------------
    # 1. INITIAL SUBSCRIPTION PURCHASE (Checkout Completed)
    # ----------------------------------------------------------------------
    if event['type'] == 'checkout.session.completed':
        session = data
        mode = session.get('mode')
        company_id = metadata.get('company_id')
        plan_id = metadata.get('plan_id')

        try:
            with transaction.atomic():
                company = Company.objects.get(id=company_id)
                
                # Update Company info
                customer_id = session.get('customer')
                if customer_id:
                    company.stripe_customer_id = customer_id
                    company._history_user = company.user
                    company.save()

                if mode == 'subscription':
                    plan = Plan.objects.get(id=plan_id)
                    subscription_id = session.get('subscription')
                    
                    # Create or Update Subscription record
                    sub_obj = Subscriptions.objects.filter(company=company).first()
                    if not sub_obj:
                        sub_obj = Subscriptions(
                            company=company,
                            plan=plan,
                            stripe_subscription_id=subscription_id,
                            active=True,
                            auto_renew=True,
                            start=timezone.now()
                        )
                    else:
                        sub_obj.plan = plan
                        sub_obj.stripe_subscription_id = subscription_id
                        sub_obj.active = True
                        sub_obj.start = timezone.now()
                    
                    sub_obj._history_user = company.user
                    sub_obj.save()
                    
                    logger.info(f"✅ Subscription {subscription_id} activated for company {company_id}")

                # Check if we have an existing payment (e.g. for services)
                payment_id = metadata.get('payment_id')
                existing_payment = None
                
                if payment_id:
                    existing_payment = Payment.objects.filter(id=payment_id).first()
                
                # Fetch Invoice URL and robust transaction ID
                invoice_id = session.get('invoice')
                invoice_url = None
                payment_intent = session.get('payment_intent')

                if invoice_id:
                    try:
                        inv = stripe.Invoice.retrieve(invoice_id)
                        invoice_url = inv.get('hosted_invoice_url')
                        if not payment_intent:
                            payment_intent = inv.get('payment_intent')
                    except Exception as e:
                        logger.error(f"Error fetching invoice {invoice_id}: {e}")
                
                final_txn_id = payment_intent or session.get('id')

                # Get Client Email
                client_email = session.get('customer_details', {}).get('email')
                if not client_email:
                    client_email = metadata.get('email')
                if not client_email and company:
                    client_email = company.user.email
                    
                # Get Session URL (Checkout URL)
                session_url = session.get('url')

                if existing_payment:
                    existing_payment.status = "success"
                    existing_payment.transaction_id = final_txn_id
                    existing_payment.invoice_url = invoice_url
                    if client_email:
                         existing_payment.client = client_email
                    if session_url and not existing_payment.url:
                         existing_payment.url = session_url
                    existing_payment._history_user = company.user
                    existing_payment.save()
                else:
                    # Create a Payment record for the initial charge
                    payment = Payment(
                        company=company,
                        client=client_email,
                        type="subscriptions" if mode == 'subscription' else "services",
                        amount=Decimal(session.get('amount_total', 0)) / 100,
                        status="success",
                        transaction_id=final_txn_id,
                        invoice_url=invoice_url,
                        url=session_url,
                        reason=f"Initial Subscription: {plan.name}" if mode == 'subscription' else "Service Payment",
                        payment_date=timezone.now()
                    )
                    payment._history_user = company.user
                    payment.save()

        except Exception as e:
            logger.error(f"Error processing checkout.session.completed: {e}")
            logger.error(traceback.format_exc())
            return HttpResponse(status=500)

    # ----------------------------------------------------------------------
    # 2. RENEWAL PAYMENT (Invoice Paid)
    # ----------------------------------------------------------------------
    elif event['type'] == 'invoice.paid':
        invoice = data
        subscription_id = invoice.get('subscription')
        
        # We only care if it's a subscription invoice
        if subscription_id:
            try:
                try:
                    sub_obj = Subscriptions.objects.get(stripe_subscription_id=subscription_id)
                    
                    with transaction.atomic():
                        # Extend the subscription end date in our DB
                        sub_obj.active = True
                        # In our model's save(), it calculates 'end' based on 'start'. 
                        # So we update 'start' to now (or period start) and 'end' to None to trigger recalculation.
                        sub_obj.start = timezone.now()
                        sub_obj.end = None 
                        sub_obj._history_user = sub_obj.company.user
                        sub_obj.save()

                        # Record the renewal payment
                        payment = Payment(
                            company=sub_obj.company,
                            type="subscriptions",
                            amount=Decimal(invoice.get('amount_paid', 0)) / 100,
                            status="success",
                            transaction_id=invoice.get('payment_intent'),
                            reason=f"Subscription Renewal: {sub_obj.plan.name}",
                            payment_date=timezone.now(),
                            invoice_url=invoice.get('hosted_invoice_url')
                        )
                        payment._history_user = sub_obj.company.user
                        payment.save()
                        send_alert(
                            [sub_obj.company],
                            "Subscription Renewed",
                            "Your subscription has been renewed.",
                            "info"
                            )
                        logger.info(f"🔄 Subscription {subscription_id} renewed via invoice.paid")
                except Subscriptions.DoesNotExist:
                    logger.warning(f"Invoice paid for unknown subscription: {subscription_id}")
            except Exception as e:
                logger.error(f"Error processing invoice.paid: {e}")
                logger.error(traceback.format_exc())
                return HttpResponse(status=500)

    # ----------------------------------------------------------------------
    # 3. SUBSCRIPTION CANCELLED OR EXPIRED
    # ----------------------------------------------------------------------
    elif event['type'] == 'customer.subscription.deleted':
        subscription_id = data.get('id')
        try:
            sub_obj = Subscriptions.objects.get(stripe_subscription_id=subscription_id)
            sub_obj.active = False
            sub_obj._history_user = sub_obj.company.user
            sub_obj.save()
            send_alert(
                [sub_obj.company],
                "Subscription Cancelled/Expired",
                "Your subscription has been cancelled/Expired.",
                "info"
                )
            logger.info(f"🚫 Subscription {subscription_id} deactivated (cancelled/expired)")
        except Subscriptions.DoesNotExist:
            pass

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

        paln = Subscriptions.objects.filter(company=company,active=True).select_related('plan','company')
        
        return Response(SubscriptionSerializer(paln,many=True).data)

class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        target_user = get_company_user(request.user)
        company = getattr(target_user, 'company', None)
        
        if not company:
            return Response({"error": "Company not found"}, status=404)

        immediate = request.data.get("immediate", False)
        subscription = Subscriptions.objects.filter(company=company, active=True).first()

        if not subscription or not subscription.stripe_subscription_id:
            return Response({"error": "No active Stripe subscription found"}, status=404)

        success, message = cancel_stripe_subscription(subscription.stripe_subscription_id, immediate=immediate)
        
        if success:
            if immediate:
                subscription.active = False
                subscription.auto_renew = False
            else:
                subscription.auto_renew = False
            
            subscription.save()
            return Response({"message": message}, status=200)
        else:
            return Response({"error": message}, status=400)
