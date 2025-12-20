from django.urls import path
from .views import *


urlpatterns = [
    path('plans/', GetPlans.as_view(), name='stripe-list-create'),
    path('payments/stripe-webhook/', stripe_webhook, name='stripe-list-create'),
    path('create-checkout/', create_checkout_session_for_service, name='create_checkout'),
    path('payment/<int:payment_id>/', get_payment, name='get_payment'),
    path('check-plan/', CheckPlan.as_view()),
    path('create-subscriptions/', create_checkout_session_for_subscription, name='create_checkout'),
    path('connect/onboard/', start_stripe_connect, name='stripe_connect_onboard'),
    path('connect/success/', stripe_connect_success, name='stripe_connect_success'),
    path('connect/refresh/', stripe_connect_refresh, name='stripe_connect_refresh'),
]

