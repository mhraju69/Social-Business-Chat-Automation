from django.urls import path
from .views import *


urlpatterns = [
    path('chat-profile/', ChatProfileView.as_view()),
    path('question-leaderboard/', CommonAskedLeaderboard.as_view()),

]