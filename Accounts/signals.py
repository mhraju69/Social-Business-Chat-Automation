from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from django.db import transaction
from .models import Company, Service

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_company_for_new_user(sender, instance, created, **kwargs):
    if not created:
        return  

    # Check user role
    if instance.role == "user": 
        Company.objects.create(user=instance)

def trigger_sync(company_id):
    from Ai.tasks import sync_company_knowledge_task
    transaction.on_commit(lambda: sync_company_knowledge_task.delay(company_id))

@receiver(post_save, sender=Company)
def sync_knowledge_on_company_save(sender, instance, **kwargs):
    trigger_sync(instance.id)

@receiver(post_save, sender=Service)
def sync_knowledge_on_service_save(sender, instance, **kwargs):
    trigger_sync(instance.company.id)

@receiver(post_delete, sender=Service)
def sync_knowledge_on_service_delete(sender, instance, **kwargs):
    trigger_sync(instance.company.id)
