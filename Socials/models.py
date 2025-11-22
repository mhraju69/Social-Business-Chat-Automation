from django.db import models
from django.contrib.auth import get_user_model
from encrypted_model_fields.fields import EncryptedCharField

User = get_user_model()

# Create your models here.

class ChatProfile(models.Model):
    PLATFORM_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_profiles')
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)

    # Generic IDs
    name = models.CharField(max_length=150, blank=True, null=True)
    profile_id = models.CharField(max_length=150, unique=True)   # e.g. number_id, page_id, instagram_id
    access_token = EncryptedCharField(max_length=5000)
    bot_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chat Profile"
        verbose_name_plural = "Chat Profiles"
        unique_together = ('platform', 'profile_id')

    def __str__(self):
        return f"{self.user.email} [{self.platform}] - {self.profile_id}"
    

class ChatClient(models.Model):
    platform = models.CharField(max_length=20, choices=ChatProfile.PLATFORM_CHOICES)
    client_id = models.CharField(max_length=150, unique=True)  
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Chat Client"
        verbose_name_plural = "Chat Clients"
        unique_together = ('platform', 'client_id')

    def __str__(self):
        return f"{self.platform} - {self.client_id}"
    

class ChatRoom(models.Model):
    profile = models.ForeignKey(ChatProfile, related_name='rooms', on_delete=models.CASCADE)
    client = models.ForeignKey(ChatClient, related_name='rooms', on_delete=models.CASCADE)
    bot_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Chat Room"
        verbose_name_plural = "Chat Rooms"
        unique_together = ('profile', 'client')

    def __str__(self):
        return f"{self.profile.platform} Room: {self.profile.profile_id} ↔ {self.client.client_id}"


class ChatMessage(models.Model):
    MESSAGE_TYPE = [
        ('incoming', 'Incoming'),
        ('outgoing', 'Outgoing'),
    ]

    room = models.ForeignKey(ChatRoom, related_name='messages', on_delete=models.CASCADE)
    type = models.CharField(max_length=10, choices=MESSAGE_TYPE)
    text = models.TextField()
    message_id = models.CharField(max_length=150, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    send_by_bot = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"

    def __str__(self):
        return f"[{self.room.profile.platform}] {self.type} - {self.timestamp}"

