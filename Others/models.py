# models.py
from django.db import models
from django.contrib.auth import get_user_model
from Accounts.models import * 
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
        return f'{self.user.email} - {self.start_time}'

class FAQ(models.Model):
    question = models.TextField()   
    answer = models.TextField()
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Company(models.Model):
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    open = models.TimeField(blank=True, null=True)
    close = models.TimeField(blank=True, null=True)
    is_24_hours_open = models.BooleanField(default=False)

    address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    # Map preview could be integrated later via coordinates
    latitude = models.CharField(max_length=100, blank=True, null=True)
    longitude = models.CharField(max_length=100, blank=True, null=True)

    # Dynamic service list
    services = models.JSONField(default=list, blank=True)  # e.g. [{"name": "SEO Setup", "price": 49.99}]

    # Tone & Personality
    formality_level = models.PositiveIntegerField(default=5)  # 1–10 scale

    # AI training
    training_files = models.FileField(upload_to='ai_training/', blank=True, null=True)

    # Website link
    website = models.URLField(blank=True, null=True)

    # Company summary
    summary = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
class PaymentMethod(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='payment_methods')
    stripe_public_key = models.CharField(max_length=255)
    stripe_secret_key = models.CharField(max_length=255)

    def __str__(self):
        return f'Payment method of {self.company}'
    
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

    def __str__(self):
        return f'{self.user.email} - {self.plan.name}'

