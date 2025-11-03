from django.contrib.auth import get_user_model
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField
User = get_user_model()


class FacebookProfile(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='facebook_profiles'
    )
    page_id = models.CharField(max_length=100, unique=True)           # Facebook Page ID
    page_access_token = EncryptedCharField(max_length=5000)                            # Page access token
    bot_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.page_id}"

    class Meta:
        verbose_name = 'Facebook Profile'
        verbose_name_plural = 'Facebook Profiles'

class FacebookClient(models.Model):
    user_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.user_id


class Incoming(models.Model):
    receiver = models.ForeignKey(
        FacebookProfile, on_delete=models.CASCADE, related_name='incoming_messages'
    )
    client =models.ForeignKey(FacebookClient, related_name='fbiclient', on_delete=models.CASCADE,null=True,blank=True)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"From {self.client.user_id} at {self.timestamp}"
    class Meta:
        verbose_name = 'Incoming Message'
        verbose_name_plural = 'Incoming Messages'

class Outgoing(models.Model):
    sender = models.ForeignKey(
        FacebookProfile, on_delete=models.CASCADE, related_name='outgoing_messages'
    )
    client =models.ForeignKey(FacebookClient, related_name='fboclient', on_delete=models.CASCADE,null=True,blank=True)
    text = models.TextField()
    message_id = models.CharField(max_length=100, blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.client.user_id} at {self.timestamp}"
    class Meta:
        verbose_name = 'Outgoing Message'
        verbose_name_plural = 'Outgoing Messages'


class FBRoom(models.Model):
    user = models.ForeignKey(FacebookProfile, related_name='room_user', on_delete=models.CASCADE)
    client = models.ForeignKey(FacebookClient, related_name='room_client', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'client')
