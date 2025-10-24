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

router = DefaultRouter()
router.register(r'users', UserViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),  # /api/users/ কাজ করবে
    path('connect/', Connect),
    path('get-otp/', GetOtp.as_view()),
    path('webhook/wp/', whatsapp_webhook),
    path('webhook/fb/', facebook_webhook),
    path('webhook/ig/', instagram_webhook),
    path('facebook/callback/', facebook_callback),
    path('instagram/callback/', instagram_callback),
    path('connect/fb/', FacebookConnectView.as_view(),name='facebook_connect'),
    path('connect/ig/', InstagramConnectView.as_view(),name='instagram_connect'),

]
