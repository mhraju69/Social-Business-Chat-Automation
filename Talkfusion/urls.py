from django.contrib import admin
from django.urls import path
from Whatsapp.whatsapp import *
from Facebook.facebook import *
from Instagram.instagram import *
from Instagram.views import *
from Facebook.views import *
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from Accounts.views import *
from Others.views import *
from django.views.generic import RedirectView
    
router = DefaultRouter()
router.register(r'users', UserViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),  
    path('connect/', Connect),
    path('get-otp/', GetOtp.as_view()),
    path('webhook/wp/', whatsapp_webhook),
    path('webhook/fb/', facebook_webhook),
    path('webhook/ig/', instagram_webhook),
    path('facebook/callback/', facebook_callback),  
    path('instagram/callback/', instagram_callback),
    path('connect/fb/', FacebookConnectView.as_view(),name='facebook_connect'),
    path('connect/ig/', InstagramConnectView.as_view(),name='instagram_connect'),
    path('api/booking/', BookingView.as_view(), name='booking-create'),
    path('api/login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
    path('api/booking/<int:id>/', BookingView.as_view(), name='booking-detail'),

]
