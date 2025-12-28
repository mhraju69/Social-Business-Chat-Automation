from django.contrib import admin
from django.urls import path
from Socials.webhook import *
from Socials.views import *
from Others.views import *
from django.urls import path, include
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView  


urlpatterns = [
    path('admin/', admin.site.urls),    
    path('api/', include('Others.urls')),
    path('api/auth/', include('Accounts.urls')),
    path('api/finance/', include('Finance.urls')),
    path('api/chat/', include('Socials.urls')),
    path('connect/', Connect),
    path("webhook/<str:platform>/", unified_webhook, name="unified_webhook"),
    path('facebook/callback/', facebook_callback),  
    path('instagram/callback/', instagram_callback),
    path('whatsapp/callback/', whatsapp_callback),
    path('api/connect/fb/', FacebookConnectView.as_view(),name='facebook_connect'),
    path('api/connect/ig/', InstagramConnectView.as_view(),name='instagram_connect'),
    path('api/connect/wa/', ConnectWhatsappView.as_view(),name='whatsapp_connect'),
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
    path('api/admin/', include('admin_dashboard.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

]
