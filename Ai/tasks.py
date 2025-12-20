from celery import shared_task
from Ai.rag_ingestion import process_company_knowledge
import logging

logger = logging.getLogger(__name__)

@shared_task(name="Ai.tasks.sync_company_knowledge_task")
def sync_company_knowledge_task(company_id):
    try:
        logger.info(f"CELERY: Starting knowledge sync for company {company_id}")
        process_company_knowledge(company_id)
        logger.info(f"CELERY: Successfully synced knowledge for company {company_id}")
        return f"Success: Company {company_id} synced"
    except Exception as e:
        logger.error(f"CELERY ERROR: Failed to sync knowledge for company {company_id}: {str(e)}")
        raise
