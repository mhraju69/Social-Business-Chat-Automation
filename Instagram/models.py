from django.contrib.auth import get_user_model
from django.db import models
from Facebook.models import *
User = get_user_model()


# ============================
# 🔹 Instagram Profile Model
# ============================
class InstagramProfile(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='instagram_profiles'
    )
    instagram_id = models.CharField(max_length=100, unique=True)          # Instagram Business Account ID
    username = models.CharField(max_length=150, blank=True, null=True)    # IG Username (optional)
    page = models.ForeignKey(
        FacebookProfile, on_delete=models.CASCADE,
        related_name='connected_instagram_accounts',
        null=True, blank=True, help_text="Linked Facebook Page"
    )
    access_token = models.TextField()                                     # Page access token with IG permissions
    bot_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.username or self.instagram_id}"

    class Meta:
        verbose_name = 'Instagram Profile'
        verbose_name_plural = 'Instagram Profiles'


# ============================
# 🔹 Incoming Instagram Messages
# ============================
class Incoming(models.Model):
    receiver = models.ForeignKey(
        InstagramProfile, on_delete=models.CASCADE, related_name='incoming_messages'
    )
    from_user_id = models.CharField(max_length=100)                       # Sender (Instagram User ID)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"From {self.from_user_id} at {self.timestamp}"

    class Meta:
        verbose_name = 'Instagram Incoming Message'
        verbose_name_plural = 'Incoming Messages'


# ============================
# 🔹 Outgoing Instagram Messages
# ============================
class Outgoing(models.Model):
    sender = models.ForeignKey(
        InstagramProfile, on_delete=models.CASCADE, related_name='outgoing_messages'
    )
    to_user_id = models.CharField(max_length=100)                         # Recipient (Instagram User ID)
    text = models.TextField()
    message_id = models.CharField(max_length=150, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.to_user_id} at {self.timestamp}"

    class Meta:
        verbose_name = 'Instagram Outgoing Message'
        verbose_name_plural = 'Outgoing Messages'
