from celery import shared_task
from Ai.rag_ingestion import process_company_knowledge
from Ai.data_analysis import analyze_company_data
import logging

logger = logging.getLogger(__name__)

@shared_task(name="Ai.tasks.sync_company_knowledge_task")
def sync_company_knowledge_task(company_id):
    try:
        logger.info(f"CELERY: Starting knowledge sync for company {company_id}")
        process_company_knowledge(company_id)
        logger.info(f"CELERY: Successfully synced knowledge for company {company_id}")
        
        # Refresh the analysis cache immediately after sync
        logger.info(f"CELERY: Refreshing analysis cache for company {company_id}")
        analyze_company_data(company_id, force_refresh=True)
        
        return f"Success: Company {company_id} synced and analysis refreshed"
    except Exception as e:
        logger.error(f"CELERY ERROR: Failed to sync knowledge for company {company_id}: {str(e)}")
        raise

@shared_task(name="Ai.tasks.analyze_company_data_task")
def analyze_company_data_task(company_id):
    try:
        # Just calling it will populate the cache if missing (force_refresh=False default handling in function)
        # But if we want to FORCE refresh on login, we could pass True.
        # User said "load it while login". If it's already cached, we don't need to do anything.
        # So we just call it (force_refresh=False default inside function logic I implemented).
        # Wait, I implemented: if not force_refresh: check cache.
        # So calling with default False is perfect for pre-warming.
        analyze_company_data(company_id)
        return f"Success: Analysis pre-warmed for company {company_id}"
    except Exception as e:
        logger.error(f"CELERY ERROR: Failed to analyze data for company {company_id}: {str(e)}")
        # We don't raise here to prevent login flow errors if it was triggered from there (though it's async)
        return str(e)
