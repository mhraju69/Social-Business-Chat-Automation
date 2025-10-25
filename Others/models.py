# models.py
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    google_event_id = models.CharField(max_length=255, blank=True, null=True)
    event_link = models.URLField(blank=True, null=True)
    
    def __str__(self):
        return f'{self.title} - {self.start_time}'
