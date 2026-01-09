from django.urls import path
from .views import *


urlpatterns = [
    path('chat-profile/', ChatProfileView.as_view()),
    path('question-leaderboard/', CommonAskedLeaderboard.as_view()),
    path('old-message/<str:platform>/<int:room_id>/', GetOldMessage.as_view()),
    path('test-chat/old-message/', GetTestChatOldMessage.as_view()),
    path('subscribe-facebook-page/', SubscribeFacebookPageToWebhook.as_view()),
]   