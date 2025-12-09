from django.contrib import admin
from django.urls import path
from Socials.webhook import *
from Socials.views import *
from Others.views import *
from django.urls import path, include
from django.views.generic import RedirectView
    


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
    path('api/connect/fb/', FacebookConnectView.as_view(),name='facebook_connect'),
    path('api/connect/ig/', InstagramConnectView.as_view(),name='instagram_connect'),
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
    path('api/admin/', include('admin_dashboard.urls'))

]
