from rest_framework.serializers import ModelSerializer,ValidationError
from .models import *
from Ai.tasks import analyze_company_data
from Accounts.models import Company
class ChatProfileSerializers(ModelSerializer):
    class Meta:
        model = ChatProfile
        fields = ['id', 'bot_active', 'profile_id', 'name', 'platform']
        read_only_fields = ["platform"]
    
    def update(self, instance, validated_data):
        company = Company.objects.get(user=instance.user)
        analysis = analyze_company_data(company.id)

        if validated_data.get('bot_active') == True and analysis["dataHealth"]["score"] < 80:
            raise ValidationError(
                f"You need to complete at least 80% of the knowledge base to activate the bot. "
                f"Current knowledge base score is {analysis['dataHealth']['score']}%."
            )
        else:
            instance.bot_active = validated_data.get('bot_active', instance.bot_active)
        instance.save()
        
        return instance

class ChatMessageSerializer(ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = '__all__'

class TestChatSerializer(ModelSerializer):
    class Meta:
        model = TestChat
        fields = '__all__'
