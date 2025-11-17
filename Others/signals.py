from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Booking
from Finance.helper import create_stripe_checkout
from datetime import timedelta
from django.utils import timezone
from .task import send_booking_reminder


@receiver(post_save, sender=Booking)
def create_payment_for_booking(sender, instance, created, **kwargs):
    if created and not instance.payment and instance.price:
        try:
            payment = create_stripe_checkout(
                type="services",
                company_id=instance.company.id,
                email=instance.client,
                amount=instance.price,
                reason=f"Payment for {instance.title}",
                method="app"
            )
            instance.payment = payment
            instance.save()
        except Exception as e:
            print("Stripe checkout error:", str(e))


@receiver(post_save, sender=Booking)
def schedule_booking_reminder(sender, instance, created, **kwargs):
    if created:
        remind_at = instance.start_time - timedelta(hours=instance.reminder_hours_before)

        # If remind_at already passed, skip
        if remind_at > timezone.now():
            send_booking_reminder.apply_async(
                args=[instance.id],
                eta=remind_at
            )
        print("Booking reminder scheduled")