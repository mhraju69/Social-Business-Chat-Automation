# models.py
from django.db import models
from django.contrib.auth import get_user_model
from Accounts.models import * 
User = get_user_model()
from django.utils import timezone
from datetime import  timedelta
import pytz
from Finance.models import *
import string

class Booking(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)
    title = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(blank=True, null=True)
    client = models.EmailField(blank=True, null=True)
    location = models.CharField(max_length=255,blank=True, null=True)
    price = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    reminder_hours_before = models.IntegerField(default=1)
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
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='faqs')
    question = models.TextField()   
    answer = models.TextField()
    category = models.CharField(max_length=100, blank=True,null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
class GoogleCalendar(models.Model):
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='google_account')
    access_token = models.TextField(blank=True,null=True)
    refresh_token = models.TextField(blank=True,null=True)
    token_uri = models.TextField(default='https://oauth2.googleapis.com/token')
    scopes = models.JSONField(default=list)
    client_id = models.TextField(blank=True,null=True)
    client_secret = models.TextField(blank=True,null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company.name} - Google Connected"
           
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

class KnowledgeBase(models.Model):  
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='knowledge_base',  on_delete=models.CASCADE,)
    name = models.CharField(max_length=255,null=True, blank=True)
    details = models.TextField(null=True, blank=True)
    file = models.FileField(upload_to='knowledge_files/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Knowledge Base"
        verbose_name_plural = "Knowledge Base Entries"

    def __str__(self):
        return self.name
    
class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=255,blank=True,null=True)
    ticket_id = models.CharField(max_length=20)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.subject
    
    def generate_ticket_id(self):
        while True:
            ticket_id = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(random.randint(10,20)))
            if not SupportTicket.objects.filter(ticket_id=ticket_id).exists():
                return ticket_id

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            self.ticket_id = self.generate_ticket_id()
        super().save(*args, **kwargs)

class UserSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    device = models.CharField(max_length=200)
    browser = models.CharField(max_length=200)
    ip_address = models.GenericIPAddressField()
    location = models.CharField(max_length=200, blank=True, null=True)
    token = models.CharField(max_length=500)  # store JWT
    last_active = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.device}"

class AITrainingFile(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='ai_training_files')
    file = models.FileField(upload_to='ai_training_files/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company.name} - {self.file.name}"
