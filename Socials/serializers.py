from rest_framework.serializers import ModelSerializer
from .models import *

class ChatProfileSerializers(ModelSerializer):
    class Meta:
        model = ChatProfile
        fields = ['bot_active']
        read_only_fields = ["user","platform"]