# models.py
from django.db import models
from django.contrib.auth import get_user_model
from Accounts.models import * 
User = get_user_model()
from django.utils import timezone
from datetime import  timedelta
import pytz

class Booking(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)
    title = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)
    client = models.CharField(max_length=255,blank=True, null=True)
    location = models.CharField(max_length=255,blank=True, null=True)
    price = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    google_event_id = models.CharField(max_length=255, blank=True, null=True)
    event_link = models.URLField(blank=True, null=True)
    
    def __str__(self):
        return f'{self.company.name} - {self.start_time}'

    @classmethod
    def meetings_today(cls, company, timezone_name=None):

        
        # Use provided timezone or fall back to company timezone
        tz_name = timezone_name or getattr(company, 'timezone', 'UTC')
        company_tz = pytz.timezone(tz_name)

        # Get current time in company timezone
        now_utc = timezone.now()
        now_local = now_utc.astimezone(company_tz)
        
        # Calculate start and end of day in local time
        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        # Convert to UTC for database query
        start_utc = start_of_day.astimezone(pytz.UTC)
        end_utc = end_of_day.astimezone(pytz.UTC)

        # Query bookings
        qs = cls.objects.filter(
            company=company,
            start_time__gte=start_utc,
            start_time__lt=end_utc
        )

        if qs.exists():
            for booking in qs:
                local_time = booking.start_time.astimezone(company_tz)
        
        return qs

    @classmethod
    def new_meetings(cls, company, timezone_name=None):

        
        # Use provided timezone or fall back to company timezone
        tz_name = timezone_name or getattr(company, 'timezone', 'UTC')
        company_tz = pytz.timezone(tz_name)

        # Get current time in company timezone
        now_utc = timezone.now()
        now_local = now_utc.astimezone(company_tz)
        
        # Calculate start of tomorrow in local time
        tomorrow_start = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start_utc = tomorrow_start.astimezone(pytz.UTC)


        # Query bookings
        qs = cls.objects.filter(
            company=company,
            start_time__gte=tomorrow_start_utc
        )

        if qs.exists():
            for booking in qs:
                local_time = booking.start_time.astimezone(company_tz)
        
        return qs    

class FAQ(models.Model):
    question = models.TextField()   
    answer = models.TextField()
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
class GoogleAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_uri = models.TextField(default='https://oauth2.googleapis.com/token')
    client_id = models.TextField()
    client_secret = models.TextField()
    scopes = models.JSONField(default=list)

    def __str__(self):
        return f"{self.user.email} - Google Connected"
    
class ChatBot(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        related_name='chat_bots',  
        on_delete=models.CASCADE
    )
    name = models.CharField(max_length=100, verbose_name="Bot Name")
    language = models.CharField(max_length=50,default='English', verbose_name="Bot Language")
    description = models.TextField(blank=True, null=True, verbose_name="Bot Description")
    is_active = models.BooleanField(default=False, verbose_name="Is Bot Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.user.email}"
       
class OpeningHours(models.Model):
    DAYS_OF_WEEK = [
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='opening_hours')
    day = models.CharField(max_length=3, choices=DAYS_OF_WEEK)
    start = models.TimeField(verbose_name="Opening Time")
    end = models.TimeField(verbose_name="Closing Time")

    class Meta:
        unique_together = ('company', 'day','start')

    def __str__(self):
        return f"{self.company.name} - {self.get_day_display()}: {self.start} - {self.end}"
    
class Alert(models.Model):
    ALERT_TYPES = [
        ("info", "Info"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("error", "Error"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="alerts")
    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255, blank=True, null=True)
    time = models.DateTimeField(auto_now_add=True)
    type = models.CharField(max_length=20, choices=ALERT_TYPES, default="info")
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.email} - {self.title}"
    
