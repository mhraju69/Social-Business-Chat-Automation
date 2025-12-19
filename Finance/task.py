from celery import shared_task
from .models import Company, Subscriptions
from django.utils import timezone
from .helper import process_auto_renewal

@shared_task(ignore_result=True)
def check_subscription_renewals():
    """
    Find all active subscriptions that have expired and have auto-renew turned on,
    then attempt to renew them.
    """
    expired_subs = Subscriptions.objects.filter(
        active=True,
        auto_renew=True,
        end__lt=timezone.now()
    ).values_list('company_id', flat=True).distinct()

    for company_id in expired_subs:
        print(f"🔄 Attempting auto-renewal for company {company_id}...")
        new_sub, message = process_auto_renewal(company_id)
        if new_sub:
            print(f"✅ Renewal successful for company {company_id}")
        else:
            print(f"❌ Renewal failed for company {company_id}: {message}")

    return f"Processed {len(expired_subs)} renewal attempts."
