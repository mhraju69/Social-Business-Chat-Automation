from django.contrib import admin
from django.urls import path
from Whatsapp.whatsapp import *
from Facebook.facebook import *
from Instagram.instagram import *
from Instagram.views import *
from Facebook.views import *
from Others.views import *
from django.urls import path, include
from django.views.generic import RedirectView
    


urlpatterns = [
    path('admin/', admin.site.urls),    
    path('api/', include('Others.urls')),
    path('api/auth/', include('Accounts.urls')),
    path('connect/', Connect),
    path('webhook/wp/', whatsapp_webhook),
    path('webhook/fb/', facebook_webhook),
    path('webhook/ig/', instagram_webhook),
    path('facebook/callback/', facebook_callback),  
    path('instagram/callback/', instagram_callback),
    path('connect/fb/', FacebookConnectView.as_view(),name='facebook_connect'),
    path('connect/ig/', InstagramConnectView.as_view(),name='instagram_connect'),
    path('', RedirectView.as_view(url='/admin/', permanent=False)),

]
