import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")

import django
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import Chat.routing

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": 
        URLRouter(
            Chat.routing.websocket_urlpatterns
        )
    ,
})
