from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
        re_path(r'ws/(?P<platform>\w+)/room/(?P<room_id>\d+)/$', consumers.Consumer.as_asgi())
    ]