from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Booking
from Finance.helper import create_stripe_checkout

@receiver(post_save, sender=Booking)
def create_payment_for_booking(sender, instance, created, **kwargs):
    if created and not instance.payment:
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
