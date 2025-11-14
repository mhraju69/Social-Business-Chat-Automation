from django.db import models
from Accounts.models import *
from django.utils import timezone
from datetime import  timedelta
import pytz 
from simple_history.models import HistoricalRecords

# Create your models here.
class Plan(models.Model):
    PLAN = [("basic", "Basic"),("business", "Business"),("premium", "Premium"),]
    DURATION = [("monthly", "Monthly"),("yearly", "Yearly")]
    name = models.CharField(choices=PLAN)
    price = models.CharField(max_length=10)
    duration = models.CharField(choices=DURATION)

    class Meta:
        unique_together = ('name', 'duration')  
        verbose_name = "Plan"
        verbose_name_plural = "Plans"

    def __str__(self):
        return f"{self.get_name_display()} ({self.get_duration_display()})"

class PlanValue(models.Model):
    plan = models.ForeignKey(Plan,on_delete=models.CASCADE,related_name='plan_value')
    value = models.CharField(max_length=100) 

    def __str__(self):
        return f"{self.plan.name} - {self.value}"
    
class StripeCredential(models.Model):
    company = models.OneToOneField(Company,related_name='stripe',  on_delete=models.CASCADE)
    api_key = models.CharField(max_length=255, verbose_name="Stripe API Key")
    publishable_key = models.CharField(max_length=255, verbose_name="Stripe Publishable Key")
    webhook_secret = models.CharField(max_length=255, verbose_name="Stripe Webhook Secret")

    history = HistoricalRecords()

    def __str__(self):
        return self.company.user.email
    
class Payment(models.Model):
    TYPE = [("subscriptions","Subscriptions"),("services","Services")]
    STATUS = [("pending","Pending"),("success","Success"),("failed","Failed")]
    company = models.ForeignKey(
        Company,
        related_name='payments',  
        on_delete=models.CASCADE
    )
    client = models.EmailField(max_length=100,blank=True,null=True)
    type = models.CharField(max_length=20,choices=TYPE,default="services")
    reason = models.CharField(max_length=255, verbose_name="Payment Reason",blank=True,null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Payment Amount")
    transaction_id = models.CharField(max_length=100, verbose_name="Transaction ID",blank=True,null=True)
    payment_date = models.DateTimeField(auto_now_add=True, verbose_name="Payment Date")
    status = models.CharField(max_length=20,choices=STATUS,default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Payment by {self.company.user.email} for {self.type}"
    
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
 
