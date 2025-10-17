from django.contrib import admin
from django.urls import path
from Whatsapp.whatsapp import *
from Whatsapp.views import *
urlpatterns = [
    path('admin/', admin.site.urls),
    path('webhook/', whatsapp_webhook),
]
