import os
import sys
import django
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Scan up 3 levels to find .env (Ai -> Social-Business-Chat-Automation -> wahejan_working)
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
load_dotenv(dotenv_path=env_path)

# Django Setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")
django.setup()

from Others.models import KnowledgeBase, AITrainingFile, Booking, OpeningHours
from Accounts.models import Company, User, Service
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
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") 
COLLECTION_NAME = "company_knowledge"

# Initialize Clients
def get_qdrant_client():
    if not QDRANT_API_KEY:
        logger.warning("QDRANT_API_KEY is not set. Connection might fail.")
    return QdrantClient(
        url=QDRANT_URL, 
        api_key=QDRANT_API_KEY,
        timeout=120
    )

def get_embedding_model():
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing via os.getenv")
    return OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)

# --- Text Extraction Helpers ---

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    try:
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
        text = df.to_string(index=False)
    except Exception as e:
        logger.error(f"Error reading CSV {file_path}: {e}")
    return text

def get_file_content(file_obj, file_type: str) -> str:
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
        
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="company_id",
            field_schema=rest.PayloadSchemaType.INTEGER
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="source_id",
            field_schema=rest.PayloadSchemaType.KEYWORD
        )
    except Exception as e:
        pass

def process_company_knowledge(company_id: int):
    print("Processing company knowledge for company_id: ", company_id)
    logger.info(f"Starting knowledge sync for Company ID: {company_id}")
    
    client = get_qdrant_client()
    embeddings = get_embedding_model()
    
    ensure_collection_exists(client)
    
    # Map of source_id -> content/metadata
    current_sources = {}
    
    # 1. KnowledgeBase
    kb_entries = KnowledgeBase.objects.filter(user__company__id=company_id)
    for kb in kb_entries:
        sid = f"kb_{kb.id}"
        text_content = ""
        text_content += f"Title: {kb.name}\n"
        if kb.details:
            text_content += f"Details: {kb.details}\n"
        if kb.file:
            text_content += get_file_content(kb.file, 'file')
        
        if text_content.strip():
            current_sources[sid] = {
                "text": text_content,
                "metadata": {"source": "KnowledgeBase", "name": kb.name, "company_id": company_id}
            }
            
    # 2. AITrainingFile
    training_files = AITrainingFile.objects.filter(company__id=company_id)
    for tf in training_files:
        sid = f"af_{tf.id}"
        text_content = get_file_content(tf.file, 'file')
        if text_content.strip():
            current_sources[sid] = {
                "text": text_content,
                "metadata": {"source": "AITrainingFile", "filename": tf.file.name, "company_id": company_id}
            }

    # 3. Services
    services = Service.objects.filter(company__id=company_id)
    for svc in services:
        sid = f"svc_{svc.id}"
        text_content = f"Service: {svc.name}\n"
        if svc.description:
            text_content += f"Description: {svc.description}\n"
        text_content += f"Price: {svc.price}\n"
        if svc.start_time and svc.end_time:
            text_content += f"Duration/Time: {svc.start_time} - {svc.end_time}\n"
        
        current_sources[sid] = {
            "text": text_content,
            "metadata": {"source": "Service", "name": svc.name, "company_id": company_id}
        }

    # 4. Company Profile & Owner
    try:
        company = Company.objects.get(id=company_id)
        
        # Company Profile
        sid_cmp = f"cmp_{company.id}"
        cmp_text = f"Company Profile: {company.name}\n"
        if company.industry:
            cmp_text += f"Industry: {company.industry}\n"
        if company.description:
            cmp_text += f"Description: {company.description}\n"
        
        addr_parts = [p for p in [company.address, company.city, company.country] if p]
        if addr_parts:
            cmp_text += f"Address: {', '.join(addr_parts)}\n"
            
        if company.website:
            cmp_text += f"Website: {company.website}\n"
        
        if company.is_24_hours_open:
            cmp_text += "Hours: Open 24 Hours\n"
        elif company.open and company.close:
             cmp_text += f"Hours: {company.open} - {company.close}\n"

        if company.language:
             cmp_text += f"Language: {company.language}\n"

        if company.summary:
             cmp_text += f"Summary: {company.summary}\n"
             
        if company.tone:
             cmp_text += f"Brand Tone: {company.tone}\n"
             
        current_sources[sid_cmp] = {
            "text": cmp_text,
            "metadata": {"source": "CompanyProfile", "name": company.name, "company_id": company.id}
        }

        # Owner Profile
        owner = company.user
        sid_usr = f"usr_{owner.id}"
        text_content = f"Company Owner/Profile: {owner.name or owner.email}\n"
        text_content += f"Email: {owner.email}\n"
        if owner.phone:
            text_content += f"Phone: {owner.phone}\n"
        
        current_sources[sid_usr] = {
            "text": text_content,
            "metadata": {"source": "User", "name": owner.name or "Owner", "company_id": company_id}
        }
    except Company.DoesNotExist:
        logger.warning(f"Company {company_id} not found.")

    # 5. Opening Hours
    opening_hours = OpeningHours.objects.filter(company__id=company_id)
    if opening_hours.exists():
        sid = f"opening_{company_id}"
        text_content = "Opening Hours:\n"
        for oh in opening_hours:
            text_content += f"{oh.get_day_display()}: {oh.start} - {oh.end}\n"
        
        current_sources[sid] = {
            "text": text_content,
            "metadata": {"source": "OpeningHours", "company_id": company_id}
        }

    # Fetch Existing IDs from Qdrant
    existing_ids = set()
    scroll_filter = rest.Filter(
        must=[
            rest.FieldCondition(key="company_id", match=rest.MatchValue(value=company_id))
        ]
    )
    
    points_iterator = client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=scroll_filter,
        with_payload=True,
        with_vectors=False,
        limit=10000 
    )[0]
    
    source_to_point_ids = {} 
    
    for point in points_iterator:
        payload = point.payload or {}
        sid = payload.get("source_id")
        # IGNORE booking points if they still exist (bk_) so we don't accidentally delete them if we want to keep them, 
        # OR better: if we want to CLEAN them, we should track them. 
        # The user said "clean_bookings_vectors.py" is unused so maybe we should just ignore them or delete them?
        # User said "remove unnecessary parts". If 'bk_' data is in DB, it's unnecessary. 
        # But let's stick to syncing what's in 'current_sources'. 
        
        if sid:
            if sid not in source_to_point_ids:
                source_to_point_ids[sid] = []
            source_to_point_ids[sid].append(point.id)
            existing_ids.add(sid)
            
    logger.info(f"Found {len(existing_ids)} existing sources in Vector DB.")

    # Sync Logic
    to_delete_source_ids = existing_ids - set(current_sources.keys())
    to_upsert_source_ids = set(current_sources.keys())
    
    # Force cleanup of any 'bk_' (booking) sources if found in existing_ids
    # This effectively does what clean_bookings_vectors did.
    for eid in list(to_delete_source_ids):
        if eid.startswith("bk_"):
            logger.info(f"Cleaning up legacy booking source: {eid}")
    
    if to_delete_source_ids:
        logger.info(f"Deleting {len(to_delete_source_ids)} outdated sources.")
        points_to_delete = []
        for sid in to_delete_source_ids:
            points_to_delete.extend(source_to_point_ids.get(sid, []))
        
        if points_to_delete:
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=points_to_delete)
            )

    # Upsert
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=150,
        length_function=len
    )
    
    logger.info(f"Upserting {len(to_upsert_source_ids)} sources.")
    
    for sid in to_upsert_source_ids:
        data = current_sources[sid]
        raw_text = data["text"]
        metadata = data["metadata"]
        
        if sid in source_to_point_ids:
            old_points = source_to_point_ids[sid]
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=old_points)
            )
        
        chunks = text_splitter.split_text(raw_text)
        if not chunks:
            continue
            
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
            batch_size = 100
            total_batches = (len(points) + batch_size - 1) // batch_size
            
            for batch_idx in range(0, len(points), batch_size):
                batch = points[batch_idx:batch_idx + batch_size]
                try:
                    client.upsert(
                        collection_name=COLLECTION_NAME,
                        points=batch,
                        wait=True
                    )
                except Exception as e:
                    logger.error(f"  Failed to upsert batch: {e}")
                    continue
            
            logger.info(f"Successfully processed {len(points)} chunks for source {sid}.")
            
    logger.info("Sync completed.")

if __name__ == "__main__":
    # Test with company_id 2
    process_company_knowledge(2)
