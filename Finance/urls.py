from django.urls import path
from .views import *


urlpatterns = [
    path('plans/', GetPlans.as_view(), name='stripe-list-create'),
    path('payments/stripe-webhook/', stripe_webhook, name='stripe-list-create'),
    path('create-checkout/', create_checkout_session_for_service, name='create_checkout'),
    path('payment/<int:payment_id>/', get_payment, name='get_payment'),
    path('stripe/', StripeListCreateView.as_view(), name='stripe-list-create'),
    path('stripe/update/', StripeUpdateView.as_view(), name='stripe-list-create'),
    path('check-plan/', CheckPlan.as_view()),
    path('create-subscriptions/', create_checkout_session_for_subscription, name='create_checkout')
]

