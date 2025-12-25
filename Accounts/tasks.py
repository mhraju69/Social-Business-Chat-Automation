from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from Others.models import UserSession 
import logging

logger = logging.getLogger(__name__)

@shared_task(name="Accounts.tasks.cleanup_inactive_sessions")
def cleanup_inactive_sessions():
    """
    Remove sessions that have been inactive (blocked/logged out) for more than 15 days.
    """
    try:
        threshold = timezone.now() - timedelta(days=7)
        # Filter for inactive sessions older than threshold
        deleted_count, _ = UserSession.objects.filter(is_active=False, updated_at__lt=threshold).delete()
        logger.info(f"Cleaned up {deleted_count} old inactive sessions.")
        return f"Cleaned up {deleted_count} old inactive sessions."
    except Exception as e:
        logger.error(f"Error checking token count: {str(e)}")
        return f"Error: {str(e)}"
