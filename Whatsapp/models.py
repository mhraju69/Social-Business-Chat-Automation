from django.contrib.auth import get_user_model
from django.db import models
User = get_user_model()
# Create your models here.

class WhatsAppProfile(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='whatsapp_profiles'
    )
    number_id = models.CharField(max_length=50, unique=True)
    access_token = models.TextField()
    bot_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.number_id}"

    class Meta:
        verbose_name = 'WhatsApp Profile'
        verbose_name_plural =  'WhatsApp Profiles'


class Incoming(models.Model):
    receiver = models.ForeignKey(
        WhatsAppProfile, on_delete=models.CASCADE, related_name='incoming_messages'
    )
    from_number = models.CharField(max_length=20)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"From {self.from_number} at {self.timestamp}"
    class Meta:
        verbose_name = 'Incoming Message'
        verbose_name_plural = 'Incoming Messages'


class Outgoing(models.Model):
    sender = models.ForeignKey(
        WhatsAppProfile, on_delete=models.CASCADE, related_name='outgoing_messages'
    )
    to_number = models.CharField(max_length=20)
    text = models.TextField()
    message_id = models.CharField(max_length=100, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.to_number} at {self.timestamp}"
    class Meta:
        verbose_name = 'Outgoing Message'
        verbose_name_plural = 'Outgoing Messages'
