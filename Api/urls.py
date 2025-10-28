from django.urls import path,include
from .views import *
from rest_framework.routers import DefaultRouter
from Accounts.views import *
from Whatsapp.whatsapp import *
from Facebook.facebook import *
from Instagram.instagram import *
from Instagram.views import *
from Facebook.views import *
from Others.views import *


router = DefaultRouter()
router.register(r'users', UserViewSet)
urlpatterns = [
    path('', include(router.urls)),  
    path('message-stats/', MessageStatsAPIView.as_view(), name='message-stats'),
    path('get-otp/', GetOtp.as_view()),
    path('booking/', BookingView.as_view(), name='booking-create'),
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path('booking/<int:id>/', BookingView.as_view(), name='booking-detail'),
]