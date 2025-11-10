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
    
class SubscriptionPlan(models.Model):
    CYCLE = {
        'monthly': 'Monthly',
        'yearly': 'Yearly',
    }
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='subscription_plans')
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2,default=0.00)
    billing_cycle = models.CharField(max_length=50,choices=CYCLE)  # e.g. 'monthly', 'yearly'
    features = models.JSONField(default=list, blank=True)  # e.g. ["Feature 1", "Feature 2"]

    def __str__(self):
        return f'{self.name} - {self.company}'
    
class Subscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='subscriptions')
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=True)
    def __str__(self):
        return f'{self.user.email} - {self.plan.name}'

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
    
class Stripe(models.Model):
    company = models.OneToOneField(Company,related_name='stripe',  on_delete=models.CASCADE)
    api_key = models.CharField(max_length=255, verbose_name="Stripe API Key")
    publishable_key = models.CharField(max_length=255, verbose_name="Stripe Publishable Key")
    webhook_secret = models.CharField(max_length=255, verbose_name="Stripe Webhook Secret")

class Payment(models.Model):
    company = models.ForeignKey(
        Company,
        related_name='payments',  
        on_delete=models.CASCADE
    )
    reason = models.CharField(max_length=255, verbose_name="Payment Reason")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Payment Amount")
    transaction_id = models.CharField(max_length=100, verbose_name="Transaction ID")
    payment_date = models.DateTimeField(auto_now_add=True, verbose_name="Payment Date")

    def __str__(self):
        return f"Payment {self.transaction_id} by {self.company.name}"
    
    @classmethod
    def payments_today(cls, company, timezone_name=None):        
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

        # Query payments
        qs = cls.objects.filter(
            company=company,
            payment_date__gte=start_utc,
            payment_date__lt=end_utc
        )

        if qs.exists():
            total_amount = 0
            for payment in qs:
                local_time = payment.payment_date.astimezone(company_tz)
                total_amount += payment.amount
        
        return qs
    
class OpeningHours(models.Model):
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='opening_hours')
    start = models.TimeField(verbose_name="Opening Time")
    end = models.TimeField(verbose_name="Closing Time")

    def __str__(self):
        return f"Opening Hours for {self.company.name}"
    
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
    
