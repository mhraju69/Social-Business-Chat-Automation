from django.urls import re_path,path
from . import consumers

websocket_urlpatterns = [
        re_path(r'ws/(?P<platform>\w+)/room/(?P<room_id>\d+)/$', consumers.Consumer.as_asgi()),
        re_path(r'ws/alerts/$', consumers.AlertConsumer.as_asgi()),
        re_path(r"ws/testchat/$", consumers.TestChatConsumer.as_asgi()),
    ]