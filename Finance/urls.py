from django.urls import path
from .views import *


urlpatterns = [
    path('plans/', GetPlans.as_view(), name='stripe-list-create'),
    path('stripe/', StripeListCreateView.as_view(), name='stripe-list-create'),
    path('stripe/update/', StripeUpdateView.as_view(), name='stripe-list-create'),
]

