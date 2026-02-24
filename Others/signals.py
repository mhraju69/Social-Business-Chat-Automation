from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from .models import Booking, KnowledgeBase, FAQ, OpeningHours, AITrainingFile, Company
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
        # Get company timezone (prefer company.timezone, then user.timezone, then default +6)
        tz_offset = instance.company.timezone or instance.company.user.timezone or "+6"
        
        # Reminder hours before (default 1 hour)
        reminder_hours = getattr(instance, 'reminder_hours_before', 1)
        
        # Calculate reminder time
        # get_reminder_time_utc in helper now handles both objects and strings,
        # but here we pass the string or name found in Company/User.
        remind_at_utc = get_reminder_time_utc(
            start_time_utc=instance.start_time,
            reminder_hours_before=reminder_hours,
            tz_info=tz_offset
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

def trigger_ai_sync(company_id):
    if not company_id:
        return
    from Ai.tasks import sync_company_knowledge_task
    transaction.on_commit(lambda: sync_company_knowledge_task.delay(company_id))

def get_company_id_for_user(user):
    company = Company.objects.filter(user=user).first()
    return company.id if company else None

# Signals for AI Knowledge Sync
@receiver(post_save, sender=KnowledgeBase)
def sync_on_kb_save(sender, instance, **kwargs):
    trigger_ai_sync(get_company_id_for_user(instance.user))

@receiver(post_delete, sender=KnowledgeBase)
def sync_on_kb_delete(sender, instance, **kwargs):
    trigger_ai_sync(get_company_id_for_user(instance.user))

@receiver(post_save, sender=FAQ)
def sync_on_faq_save(sender, instance, **kwargs):
    trigger_ai_sync(instance.company.id)

@receiver(post_delete, sender=FAQ)
def sync_on_faq_delete(sender, instance, **kwargs):
    trigger_ai_sync(instance.company.id)

@receiver(post_save, sender=OpeningHours)
def sync_on_hours_save(sender, instance, **kwargs):
    trigger_ai_sync(instance.company.id)

@receiver(post_delete, sender=OpeningHours)
def sync_on_hours_delete(sender, instance, **kwargs):
    trigger_ai_sync(instance.company.id)

@receiver(post_save, sender=AITrainingFile)
def sync_on_ai_file_save(sender, instance, **kwargs):
    trigger_ai_sync(instance.company.id)

@receiver(post_delete, sender=AITrainingFile)
def sync_on_ai_file_delete(sender, instance, **kwargs):
    trigger_ai_sync(instance.company.id)