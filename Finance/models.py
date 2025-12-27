from django.db import models
from Accounts.models import *
from django.utils import timezone
from datetime import  timedelta
import pytz 
from simple_history.models import HistoricalRecords
from django.db.models import Sum
from django.utils.timezone import now
from django.db.models import Avg
from dateutil.relativedelta import relativedelta
# Create your models here.

class Plan(models.Model):
    PLAN = [
        ("essential", "Essential"),
        ("growth", "Growth"),
        ("enterprise", "Enterprise Custom"),
    ]
    DURATION = [
        ("days", "Daily"),
        ("months", "Monthly"),
        ("years", "Yearly"),
    ]

    name = models.CharField(max_length=20, choices=PLAN)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    msg_limit = models.IntegerField(default=0)
    duration = models.CharField(max_length=20, choices=DURATION)
    user_limit = models.IntegerField(default=0)
    token_limit = models.IntegerField(default=0)
    stripe_product_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)
    custom = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.get_name_display()} ({self.get_duration_display()})"

    def save(self, *args, **kwargs):
        if self.name in ["essential", "growth"]:
            existing = Plan.objects.filter(
                name=self.name,
                custom=False
            ).exclude(id=self.id)

            if existing.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    f"A default plan with name '{self.name}' already exists."
                )

        super().save(*args, **kwargs)


class Subscriptions(models.Model):
    company = models.ForeignKey(Company, related_name='subscriptions', on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE)
    start = models.DateTimeField(blank=True, null=True)
    end = models.DateTimeField(blank=True, null=True)
    active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    token_count = models.IntegerField(default=0)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        if not self.start:
            self.start = timezone.now()

        # Fetch plan safely
        plan_obj = self.plan

        # Auto-set end date based on plan.duration
        if not self.end and plan_obj:

            if plan_obj.duration == 'days':
                self.end = self.start + timedelta(days=1)

            elif plan_obj.duration == 'months':
                self.end = self.start + relativedelta(months=1)

            elif plan_obj.duration == 'years':
                self.end = self.start + relativedelta(years=1)
        
        # Initialize token_count from Plan if not set (new subscription)
        if self.token_count == 0 and plan_obj and not self.pk:
             # If we want to allow carry-over, logic would be different. 
             # Assuming reset on new subscription/renewal.
             self.token_count = plan_obj.token_limit

        super().save(*args, **kwargs)

        # Deactivate previous active subscriptions
        self.company.subscriptions.exclude(id=self.id).filter(
            active=True,
            end__gte=timezone.now()
        ).update(active=False)

    def deduct_tokens(self, amount):
        """
        Deduct tokens from the subscription and update Redis cache.
        """
        if amount <= 0:
            return

        self.token_count -= amount
        self.save(update_fields=['token_count'])

        # Update Redis to keep it in sync with Socials/helper.py
        try:
            from django_redis import get_redis_connection
            redis = get_redis_connection("default")
            cache_key = f"company_token_{self.company.id}"
            redis.set(cache_key, self.token_count)
        except ImportError:
            pass # django_redis might not be installed or configured in all envs
        except Exception as e:
            print(f"Error updating redis cache: {e}")

    def __str__(self):
        return f"{self.company} - {self.plan.name}"

class DailyUsage(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='daily_usage')
    date = models.DateField(default=timezone.now)
    msg_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ('company', 'date')

    def __str__(self):
        return f"{self.company} - {self.date} - {self.msg_count}"

    
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
    url = models.URLField(null=True,blank=True)
    invoice_url = models.URLField(null=True,blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"Payment by {self.company.user.email} for {self.type}"
    
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
 
    def success_payment_change_percentage(company):

        now = timezone.now()
        
        # Current month range
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_end = (current_month_start + timedelta(days=32)).replace(day=1)  # start of next month
        
        # Last month range
        last_month_end = current_month_start
        last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        
        # Sum successful payments
        current_total = Payment.objects.filter(
            company=company,
            status='success',
            payment_date__gte=current_month_start,
            payment_date__lt=current_month_end
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        last_total = Payment.objects.filter(
            company=company,
            status='success',
            payment_date__gte=last_month_start,
            payment_date__lt=last_month_end
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Calculate percentage change
        if last_total == 0:
            percent_change = 100 if current_total > 0 else 0
        else:
            percent_change = ((current_total - last_total) / last_total) * 100

        return {
            "current_month": current_total,
            "difference": round(percent_change, 2)
        }
    
    def get_failed_payment_counts(company):
        today = timezone.now()

        # Current month range
        current_month_start = today.replace(day=1)
        next_month = (current_month_start + timedelta(days=32)).replace(day=1)

        # Last month range
        last_month_end = current_month_start
        last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)

        # Query failed payments for each period
        current_month_failed = Payment.objects.filter(
            company=company,
            status="failed",
            payment_date__gte=current_month_start,
            payment_date__lt=next_month
        ).count()

        last_month_failed = Payment.objects.filter(
            company_id=company,
            status="failed",
            payment_date__gte=last_month_start,
            payment_date__lt=last_month_end
        ).count()

        return {
            "current_month": current_month_failed,
            "last_month": last_month_failed
        }
    
    def pending_payment_stats(company):
        today = now()
        first_day_current_month = today.replace(day=1)
        
        # Last month calculation
        if first_day_current_month.month == 1:
            first_day_last_month = first_day_current_month.replace(year=today.year-1, month=12)
        else:
            first_day_last_month = first_day_current_month.replace(month=today.month-1)
        
        # Last day of last month
        last_day_last_month = first_day_current_month - timedelta(seconds=1)

        # Total pending payments for last month (services only)
        last_month_total = Payment.objects.filter(
            company=company,
            type="services",
            status="pending",
            payment_date__gte=first_day_last_month,
            payment_date__lte=last_day_last_month
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Total pending payments for current month (services only)
        current_month_total = Payment.objects.filter(
            company=company,
            type="services",
            status="pending",
            payment_date__gte=first_day_current_month,
            payment_date__lte=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Percentage difference calculation
        if last_month_total == 0:
            percent_diff = 100 if current_month_total > 0 else 0
        else:
            percent_diff = ((current_month_total - last_month_total) / last_month_total) * 100

        return {
            "current_month": current_month_total,
            "difference": percent_diff
        }
    
    def average_order_value_change(company):
        now = timezone.now()
        
        # Current month range
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_month_end = (current_month_start + timedelta(days=32)).replace(day=1)  # start of next month
        
        # Last month range
        last_month_end = current_month_start
        last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        
        # Calculate average successful payments
        current_avg = Payment.objects.filter(
            company=company,
            status='success',
            payment_date__gte=current_month_start,
            payment_date__lt=current_month_end
        ).aggregate(avg=Avg('amount'))['avg'] or 0

        last_avg = Payment.objects.filter(
            company=company,
            status='success',
            payment_date__gte=last_month_start,
            payment_date__lt=last_month_end
        ).aggregate(avg=Avg('amount'))['avg'] or 0
        
        # Calculate percentage change
        if last_avg == 0:
            percent_change = 100 if current_avg > 0 else 0
        else:
            percent_change = ((current_avg - last_avg) / last_avg) * 100

        return {
            "current_month": round(current_avg, 2),
            "difference": round(percent_change, 2)
        }