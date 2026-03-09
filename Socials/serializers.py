from rest_framework.serializers import ModelSerializer,ValidationError
from .models import *
from Ai.tasks import analyze_company_data
from Accounts.models import Company
from Socials.consumers import send_alert
from Finance.models import Subscriptions
from django.utils import timezone

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
        elif validated_data.get('bot_active') == True and instance.is_approved == False:
            raise ValidationError(
                "Your account is not approved by the admin. Please wait for the approval."
            )
        elif validated_data.get('bot_active') == True and not Subscriptions.objects.filter(company=company, end__gt=timezone.now()).exists():
            raise ValidationError(
                "You don't have any active subscription. Please subscribe to continue using our automation services."
            )
        else:
            instance.bot_active = validated_data.get('bot_active', instance.bot_active)

            if instance.bot_active:
                send_alert(company,"Your bot is now active.")
            else:
                send_alert(company,"Your bot is now deactivated.")

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
