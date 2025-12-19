from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Booking
from Finance.helper import create_stripe_checkout_for_service
from django.utils import timezone
from .task import send_booking_reminder
from .helper import *

@receiver(post_save, sender=Booking)
def create_payment_for_booking(sender, instance, created, **kwargs):
    if created and not instance.payment and instance.price:
        try:
            payment = create_stripe_checkout_for_service(
                company_id=instance.company.id,
                email=instance.client,
                amount=instance.price,
                reason=f"Payment for {instance.title}"
            )
            instance.payment = payment
            instance.save()
        except Exception as e:
            print("Stripe checkout error:", str(e))

@receiver(post_save, sender=Booking)
def schedule_booking_reminder(sender, instance, created, **kwargs):
    """Schedule reminder 1 hour before booking"""
    if not created:
        return
    
    try:
        # Get timezone offset
        tz_offset = instance.company.user.timezone or "+6"  # Default Bangladesh
        
        # Reminder hours before (default 1 hour)
        reminder_hours = getattr(instance, 'reminder_hours_before', 1)
        
        # Calculate reminder time
        remind_at_utc = get_reminder_time_utc(
            start_time_utc=instance.start_time,
            reminder_hours_before=reminder_hours,
            tz_offset=tz_offset
        )
        
        # Current time in UTC
        now_utc = timezone.now()
        
        # Check if reminder is in future
        if remind_at_utc > now_utc:
            # Schedule the task
            result = send_booking_reminder.apply_async(
                args=[instance.id],
                eta=remind_at_utc
            )
            print(f"✅ Reminder scheduled successfully!")
            print(f"   Task ID: {result.id}")
            print(f"   Will run at: {remind_at_utc} UTC")
        else:
            time_diff = now_utc - remind_at_utc
            print(f"✗ Reminder not scheduled (already passed by {time_diff})")
            print(f"   Reminder was for: {remind_at_utc} UTC")
            print(f"   Current time: {now_utc} UTC")
            
    except Exception as e:
        print(f"❌ Error scheduling reminder: {str(e)}")
        import traceback
        traceback.print_exc()