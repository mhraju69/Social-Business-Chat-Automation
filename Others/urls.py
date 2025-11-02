from django.urls import path
from Accounts.views import *
from Whatsapp.whatsapp import *
from Facebook.facebook import *
from Instagram.instagram import *
from Instagram.views import *
from Facebook.views import *
from Others.views import *


urlpatterns = [
    path('message-stats/', MessageStatsAPIView.as_view(), name='message-stats'),
    path('get-otp/', GetOtp.as_view()),
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path('booking/', BookingAPIView.as_view()),  # POST to create
    path('booking/<int:booking_id>/', BookingAPIView.as_view()),  
    path("google/booking/", SocialAuthCallbackView.as_view()),
    path("boking/today/<int:company_id>", SocialAuthCallbackView.as_view()),
    path('stripe/', StripeListCreateView.as_view(), name='stripe-list-create'),
    path('stripe/update/', StripeUpdateView.as_view(), name='stripe-list-create'),
]