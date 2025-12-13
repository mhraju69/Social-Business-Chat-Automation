import os
import sys
import django
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

# Django Setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")
django.setup()

from Others.models import KnowledgeBase, AITrainingFile, Company
from django.conf import settings

# RAG / ML Imports
import openai
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# File Parsing
import pypdf
import docx
import pandas as pd
import io

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
QDRANT_URL = "https://deed639e-bc0e-43fe-8dc2-2edaed834f41.europe-west3-0.gcp.cloud.qdrant.io:6333"
# Ideally these should be in settings/env
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # Ensure this is set in .env
COLLECTION_NAME = "company_knowledge"

# Initialize Clients
# We use a global or lazy initialization to allow module import without immediate failure if keys are missing
def get_qdrant_client():
    if not QDRANT_API_KEY:
        logger.warning("QDRANT_API_KEY is not set. Connection might fail.")
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

def get_embedding_model():
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing via os.getenv")
    return OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)

# --- Text Extraction Helpers ---

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
        # Depending on storage, file_path might be a relative path from MEDIA_ROOT or a full path
        # Django 'FileField' usually stores relative to MEDIA_ROOT
        full_path = os.path.join(settings.MEDIA_ROOT, str(file_path))
        if not os.path.exists(full_path):
             logger.error(f"File not found: {full_path}")
             return ""
        
        with open(full_path, 'rb') as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + "\n"
    except Exception as e:
        logger.error(f"Error reading PDF {file_path}: {e}")
    return text

def extract_text_from_docx(file_path: str) -> str:
    text = ""
    try:
        full_path = os.path.join(settings.MEDIA_ROOT, str(file_path))
        if not os.path.exists(full_path):
             return ""
        
        doc = docx.Document(full_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        logger.error(f"Error reading DOCX {file_path}: {e}")
    return text

def extract_text_from_csv(file_path: str) -> str:
    text = ""
    try:
        full_path = os.path.join(settings.MEDIA_ROOT, str(file_path))
        if not os.path.exists(full_path):
             return ""
        
        df = pd.read_csv(full_path)
        # Convert to string representation or iterate
        text = df.to_string(index=False)
    except Exception as e:
        logger.error(f"Error reading CSV {file_path}: {e}")
    return text

def get_file_content(file_obj, file_type: str) -> str:
    """
    Dispatcher for file content extraction.
    file_obj: The Django model field file object (e.g., instance.file)
    """
    if not file_obj:
        return ""
    
    path = file_obj.name
    ext = os.path.splitext(path)[1].lower()
    
    if ext == '.pdf':
        return extract_text_from_pdf(path)
    elif ext in ['.doc', '.docx']:
        return extract_text_from_docx(path)
    elif ext == '.csv':
        return extract_text_from_csv(path)
    elif ext == '.txt':
        try:
            full_path = os.path.join(settings.MEDIA_ROOT, path)
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except:
            return ""
    return ""

# --- Pipeline Logic ---

def ensure_collection_exists(client: QdrantClient, vector_size: int = 1536):
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=rest.VectorParams(
                size=vector_size,
                distance=rest.Distance.COSINE
            )
        )
        logger.info(f"Created collection {COLLECTION_NAME}")

def process_company_knowledge(company_id: int):
    """
    Main function to sync company data to Qdrant.
    It identifies changes and updates the vector DB accordingly.
    """
    logger.info(f"Starting knowledge sync for Company ID: {company_id}")
    
    client = get_qdrant_client()
    embeddings = get_embedding_model()
    
    # 1. Ensure Collection Exists
    ensure_collection_exists(client)
    
    # 2. Fetch Data from SQL DB
    # KnowledgeBase
    kb_entries = KnowledgeBase.objects.filter(user__company__id=company_id)
    # AITrainingFile
    training_files = AITrainingFile.objects.filter(company__id=company_id)
    
    # Map of source_id -> content/metadata
    # source_id format: "kb_{id}" or "af_{id}"
    current_sources = {}
    
    # Process KnowledgeBase
    for kb in kb_entries:
        sid = f"kb_{kb.id}"
        text_content = ""
        if kb.details:
            text_content += f"Title: {kb.name}\nDetails: {kb.details}\n"
        if kb.file:
            text_content += get_file_content(kb.file, 'file')
        
        if text_content.strip():
            current_sources[sid] = {
                "text": text_content,
                "metadata": {"source": "KnowledgeBase", "name": kb.name, "company_id": company_id}
            }
            
    # Process AITrainingFile
    for tf in training_files:
        sid = f"af_{tf.id}"
        text_content = get_file_content(tf.file, 'file')
        if text_content.strip():
            current_sources[sid] = {
                "text": text_content,
                "metadata": {"source": "AITrainingFile", "filename": tf.file.name, "company_id": company_id}
            }

    # 3. Fetch Existing IDs from Qdrant for this Company
    # We use scroll to get all points with filter
    existing_ids = set()
    
    scroll_filter = rest.Filter(
        must=[
            rest.FieldCondition(key="company_id", match=rest.MatchValue(value=company_id))
        ]
    )
    
    # We need to know which 'source_ids' exist. 
    # Since Qdrant stores chunks, one source file = multiple points (chunks).
    # We store 'source_id' in payload to group them.
    
    # Efficient strategy:
    # Get all points (only payloads)
    points_iterator = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=scroll_filter,
        with_payload=True,
        with_vectors=False,
        limit=10000 # Assuming reasonable limit per company, else paginate loops
    )[0]
    
    # Map source_id -> list of point_ids
    source_to_point_ids = {} 
    
    for point in points_iterator:
        payload = point.payload or {}
        sid = payload.get("source_id")
        if sid:
            if sid not in source_to_point_ids:
                source_to_point_ids[sid] = []
            source_to_point_ids[sid].append(point.id)
            existing_ids.add(sid)
            
    logger.info(f"Found {len(existing_ids)} existing sources in Vector DB.")

    # 4. Compare and Sync
    
    # Identify Deleted
    to_delete_source_ids = existing_ids - set(current_sources.keys())
    
    # Identify New or Updated
    # Note: For strict 'updated' logic, we'd need a hash. 
    # For now, we can assume if it's in current_sources, we upsert it (overwrite).
    # To be extremely efficient, we could check 'updated_at' if we stored it in payload.
    # But overwriting active files is usually acceptable unless they are huge.
    
    to_upsert_source_ids = set(current_sources.keys())
    
    # DELETE OLD
    if to_delete_source_ids:
        logger.info(f"Deleting {len(to_delete_source_ids)} outdated sources.")
        # Flatten point IDs
        points_to_delete = []
        for sid in to_delete_source_ids:
            points_to_delete.extend(source_to_point_ids.get(sid, []))
        
        if points_to_delete:
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=points_to_delete)
            )

    # UPSERT NEW/UPDATED
    # We chunk and upload
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )
    
    logger.info(f"Upserting {len(to_upsert_source_ids)} sources.")
    
    for sid in to_upsert_source_ids:
        data = current_sources[sid]
        raw_text = data["text"]
        metadata = data["metadata"]
        
        # If we didn't delete the old chunks for this SID (because it's an update, not a delete),
        # we strictly should delete old chunks first to avoid duplication (e.g. if file got shorter).
        # Existing logic: 'to_delete_source_ids' only caught removed files.
        # So we MUST delete existing points for this SID before re-uploading.
        if sid in source_to_point_ids:
            old_points = source_to_point_ids[sid]
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=old_points)
            )
        
        # Chunking
        chunks = text_splitter.split_text(raw_text)
        
        if not chunks:
            continue
            
        # Embed
        # batch embed is better
        try:
            vectors = embeddings.embed_documents(chunks)
        except Exception as e:
            logger.error(f"Failed to embed source {sid}: {e}")
            continue
            
        points = []
        import uuid
        
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = str(uuid.uuid4())
            payload = {
                "source_id": sid,
                "text": chunk,
                "company_id": company_id,
                **metadata
            }
            points.append(rest.PointStruct(id=point_id, vector=vector, payload=payload))
            
        if points:
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            
    logger.info("Sync completed.")

if __name__ == "__main__":
    # Test with company_id 2 as per setup_db.py
    process_company_knowledge(2)
