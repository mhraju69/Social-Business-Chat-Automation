from django.contrib import admin
from django.urls import path
from Whatsapp.whatsapp import *
from Facebook.facebook import *
from Instagram.instagram import *
from Facebook.views import *
urlpatterns = [
    path('admin/', admin.site.urls),
    path('connect/', Connect),
    path('webhook/wp/', whatsapp_webhook),
    path('webhook/fb/', facebook_webhook),
    path('webhook/ig/', instagram_webhook),
    path('connect/fb/', FacebookConnectView.as_view(),name='facebook_connect'),
    path('facebook/callback/', facebook_callback),

]
