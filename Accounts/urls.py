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
    path('get-otp/', GetOtp.as_view()),
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path("google/callback/", SocialAuthCallbackView.as_view()),
    path('company/', CompanyDetailUpdateView.as_view(), name='company-detail-update'),
]