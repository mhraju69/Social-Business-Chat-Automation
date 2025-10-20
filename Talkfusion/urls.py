from django.contrib import admin
from django.urls import path
from Whatsapp.whatsapp import *
from Facebook.facebook import *
from Whatsapp.views import *
urlpatterns = [
    path('admin/', admin.site.urls),
    path('webhook/wp/', whatsapp_webhook),
    path('webhook/fb/', facebook_webhook),
]
