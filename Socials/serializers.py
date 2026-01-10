from rest_framework.serializers import ModelSerializer
from .models import *

class ChatProfileSerializers(ModelSerializer):
    class Meta:
        model = ChatProfile
        fields = ['id', 'bot_active', 'profile_id', 'name', 'platform']
        read_only_fields = ["platform"]

class ChatMessageSerializer(ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = '__all__'

class TestChatSerializer(ModelSerializer):
    class Meta:
        model = TestChat
        fields = '__all__'
