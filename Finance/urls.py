from django.urls import path
from .views import *


urlpatterns = [
    path('plans/', GetPlans.as_view(), name='stripe-list-create'),
    path('payments/stripe-webhook/', stripe_webhook, name='stripe-list-create'),
    path('create-checkout/', create_checkout_session, name='create_checkout'),
    # path('create-checkout/<int:company_id>/<int:plan_id>/', create_checkout_session, name='create_checkout_plan'),
    path('stripe/', StripeListCreateView.as_view(), name='stripe-list-create'),
    path('stripe/update/', StripeUpdateView.as_view(), name='stripe-list-create'),
]

