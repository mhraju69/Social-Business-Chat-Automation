import os
import sys
import django
import logging
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
import pytz
import re
from typing import List, Dict, Optional
from types import SimpleNamespace


load_dotenv()

# Django Setup (if run standalone)
# Ensure project root is in path relative to this file
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")

try:
    from django.conf import settings
    if not settings.configured:
        django.setup()
except ImportError:
    pass

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from Others.models import OpeningHours, Booking
from Accounts.models import Company

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
QDRANT_URL = "https://deed639e-bc0e-43fe-8dc2-2edaed834f41.europe-west3-0.gcp.cloud.qdrant.io:6333"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COLLECTION_NAME = "company_knowledge"

class MockRequest:
    """Mock Django Request object for reusing create_booking logic"""
    def __init__(self, data=None, query_params=None):
        self.data = data or {}
        self.query_params = query_params or {}

def get_available_slots(company_id: int, date_str: str = None) -> List[str]:
    """
    Calculate available slots for a given date based on OpeningHours and existing Bookings.
    Returns a list of strings representing available start times.
    """
    try:
        if not date_str:
            target_date = datetime.now()
        else:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
            
        # Get weekday (mon, tue, etc.)
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        weekday = day_map[target_date.weekday()]
        
        # Get Opening Hours
        hours = OpeningHours.objects.filter(company_id=company_id, day=weekday).first()
        if not hours:
            return [] # Closed
            
        # Define working hours
        start_time = datetime.combine(target_date, hours.start)
        end_time = datetime.combine(target_date, hours.end)
        
        # Get Bookings for this day
        bookings = Booking.objects.filter(
            company_id=company_id, 
            start_time__date=target_date.date()
        )
        
        booked_ranges = []
        for b in bookings:
            # We assume booking start/end are datetime objects
            # Convert to naive for comparison if needed
            b_start = b.start_time.replace(tzinfo=None) if b.start_time.tzinfo else b.start_time
            if b.end_time:
                 b_end = b.end_time.replace(tzinfo=None) if b.end_time.tzinfo else b.end_time
            else:
                 b_end = b_start + timedelta(hours=1)
            
            booked_ranges.append((b_start, b_end))
            
        # Generate Slots (Hourly)
        slots = []
        current = start_time
        while current + timedelta(hours=1) <= end_time:
            slot_end = current + timedelta(hours=1)
            is_taken = False
            for b_start, b_end in booked_ranges:
                # Check overlap: (StartA < EndB) and (EndA > StartB)
                if current < b_end and slot_end > b_start:
                    is_taken = True
                    break
            
            if not is_taken and current > datetime.now(): # Only future slots
                slots.append(current.strftime("%H:%M"))
            
            current += timedelta(hours=1)
            
        return slots
    except Exception as e:
        logger.error(f"Error calculating slots: {e}")
        return []

def get_ai_response(company_id: int, query: str, history: Optional[List[Dict]] = None, tone: str = "professional") -> dict:
    print(f"\n🚀 --- get_ai_response started (Company: {company_id}, Tone: {tone}) ---")
    """
    Generates an AI response for a specific company using RAG.
    
    Args:
        company_id: The ID of the company.
        query: The user's question.
        history: List of dictionaries representing conversation history. 
                 Example: [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        tone: The desired tone of the response (e.g., "professional", "friendly", "rude").
    """
    
    # 1. Initialize Clients
    if not QDRANT_API_KEY:
        return {"content": "System Error: Qdrant API Key missing.", "token_usage": {}}
    if not OPENAI_API_KEY:
        return {"content": "System Error: OpenAI API Key missing.", "token_usage": {}}
        
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)
    llm = ChatOpenAI(model="gpt-4o", openai_api_key=OPENAI_API_KEY, temperature=0.7)
    
    # 2. Embed Query & Search
    try:
        query_vector = embeddings.embed_query(query)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return {"content": "I'm having trouble understanding that right now.", "token_usage": {}}
        
    search_filter = rest.Filter(
        must=[
            rest.FieldCondition(key="company_id", match=rest.MatchValue(value=company_id))
        ]
    )
    
    # 3. Retrieve Mandatory Context (Company Profile)
    # We always want the company profile to be present so the AI knows who it is.
    forced_context = ""
    try:
        profile_filter = rest.Filter(
            must=[
                rest.FieldCondition(key="company_id", match=rest.MatchValue(value=company_id)),
                rest.FieldCondition(key="source_id", match=rest.MatchValue(value=f"cmp_{company_id}"))
            ]
        )
        profile_results = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=profile_filter,
            limit=1,
            with_payload=True,
            with_vectors=False
        )[0]
        
        if profile_results:
            forced_context = profile_results[0].payload.get('text', '') + "\n\n"
            logging.info("Attached Company Profile to context.")
    except Exception as e:
        logger.error(f"Failed to fetch profile: {e}")

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=search_filter,
        limit=5, # Reduced from 10 for token optimization
        score_threshold=0.2 
    ).points

    # Filter out Booking vectors (Ghost data) ONLY
    # DO NOT filter out 'af_' (Training Files) as they are now legitimate sources.
    retrieved_items = []
    for res in results:
        payload = res.payload or {}
        sid = payload.get("source_id", "")
        # Only exclude bookings from vector results (should be empty anyway if cleaned)
        if sid.startswith("bk_"):
            continue
        retrieved_items.append(payload.get('text', ''))
    
    retrieved_text = "\n\n".join(retrieved_items)
    context_text = forced_context + retrieved_text
    
    try:
        company = Company.objects.get(id=company_id)
        company_name = company.name or "Unknown"
    except:
        company = None
        company_name = "Unknown"

    # --- Realtime Booking Data (SQLite) ---
    # Fetch recent/future bookings to strictly provide availability info without leaking details.
    if company:
        try:
            # Check if query implies booking/availability
            booking_keywords = ['book', 'schedule', 'appointment', 'available', 'occupied', 'time', 'slot', 'day', 'week']
            if any(w in query.lower() for w in booking_keywords):
                from django.utils import timezone
                now = timezone.now()
                # Fetch bookings for next 7 days
                end_date = now + timedelta(days=7)
                
                realtime_bookings = Booking.objects.filter(
                    company=company,
                    start_time__gte=now,
                    start_time__lte=end_date
                ).order_by('start_time')
                
                if realtime_bookings.exists():
                    schedule_text = "\n\n--- REALTIME AVAILABILITY DATA ---\n"
                    schedule_text += "Use this to answer availability questions. DO NOT reveal client names.\n"
                    
                    # Group by day
                    grouped = {}
                    for bk in realtime_bookings:
                        # Convert to company timezone if possible, but standard is often UTC or server time.
                        # Assuming usage of naive or standardized time here for simplicity.
                        day = bk.start_time.strftime('%Y-%m-%d (%A)')
                        if day not in grouped:
                            grouped[day] = []
                        # Just show time as 'Occupied'
                        grouped[day].append(f"{bk.start_time.strftime('%H:%M')} - {bk.end_time.strftime('%H:%M')}: Occupied")
                    
                    for day, slots in grouped.items():
                        schedule_text += f"{day}:\n" + "\n".join(f"  - {s}" for s in slots) + "\n"
                    
                    context_text += schedule_text
                    logging.info(f"Attached {len(realtime_bookings)} realtime booking slots to context.")
        except Exception as e:
            logging.error(f"Error fetching realtime bookings: {e}")

    # print(f"DEBUG: Retrieved Context:\n{context_text}\n-------------------")
    
    if not context_text:
        context_text = "No specific company documents found."

    # Format History
    history_text = ""
    if history:
        # Optimization: Limit to last 5 interaction turns to manage token usage
        recent_history = history[-10:] 
        for msg in recent_history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            history_text += f"{role}: {content}\n"
    
    if not history_text:
        history_text = "No previous conversation."
    
    # 4. Generate Response
    # Using LangChain LCEL
    template = """
    You are a real customer support and sales representative working at "{company_name}".
    You must always sound like a real human employee of "{company_name}" — never like AI, automation, or a system.

    LANGUAGE RULE
    - Detect the user’s language automatically.
    - Reply in the same language unless the user asks otherwise.
    - Sound natural and native in that language.

    IDENTITY & TONE
    - Introduce yourself as a representative of "{company_name}" only in the first reply of a new conversation.
    - Never repeat introductions.
    - Always follow this tone exactly: {tone}.
    - Be warm, polite, confident, and conversational.
    - Never sound robotic, scripted, or overly formal.

    KNOWLEDGE & ACCURACY
    - Use ONLY the provided context to answer.
    - Paraphrase naturally; never quote context unless asked.
    - If the answer is not in the context, never guess or invent.

    Use this exact sentence when information is missing:
    “At the moment, I don’t have the exact details on that. Let me check and get back to you shortly with the right information.”

    USER UNDERSTANDING
    - Focus on intent, not exact wording.
    - Treat similar meanings as the same (pricing = cost = plans).
    - Ask clarifying questions only if the answer would change.

    CUSTOMER EXPERIENCE
    - Acknowledge the user’s need first.
    - Be calm, reassuring, and solution-focused.
    - Never sound defensive or rushed.
    - Maintain full conversation continuity.

    SALES BEHAVIOR
    - Mention "{company_name}" services only when relevant.
    - Offer bookings or plans only if the user shows interest or asks.
    - Never push or upsell.

    BOOKING LOGIC
    - If the user asks about availability, respond with JSON only:
    {
    "action": "check_availability",
    "date": "YYYY-MM-DD" or null
    }

    - If the user wants to book, ask ONE BY ONE:
    1. Service name
    2. Preferred date & time
    3. Email address

    - Once all three are collected, respond with JSON only:
    {
    "action": "create_booking",
    "booking_data": {
        "title": "...",
        "start_time": "YYYY-MM-DD HH:MM:SS",
        "client": "email@example.com"
    }
    }

    FINAL RULE
    - Never mention AI, systems, automation, or internal processes.
    - The user must always feel they are speaking with a real person from "{company_name}".
    """
    
    prompt = ChatPromptTemplate.from_template(template)
    # Remove StrOutputParser to get full AIMessage object with metadata
    chain = prompt | llm 
    
    response = chain.invoke({
        "company_name": company_name,
        "context": context_text, 
        "question": query,
        "history": history_text,
        "tone": tone,
        "current_date": datetime.now().strftime("%Y-%m-%d")
    })
    
    response_text = response.content
    
    # Initialize token stats
    token_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0
    }
    
    if hasattr(response, 'response_metadata'):
        usage = response.response_metadata.get('token_usage', {})
        token_usage["input_tokens"] += usage.get('prompt_tokens', 0)
        token_usage["output_tokens"] += usage.get('completion_tokens', 0)
        token_usage["total_tokens"] += usage.get('total_tokens', 0)
    print("token_usage:😁😁😁😁😁", token_usage)

    # Define helper to deduct tokens
    def deduct_tokens_now():
        try:
            input_tokens = token_usage.get("input_tokens", 0)
            output_tokens = token_usage.get("output_tokens", 0)
            total = token_usage.get("total_tokens", 0)

            print(f"--- 📊 AI TOKEN USAGE DEBUG (Company: {company_id}) ---")
            print(f"🔹 Input Tokens:  {input_tokens}")
            print(f"🔹 Output Tokens: {output_tokens}")
            print(f"🔹 Total Tokens:  {total}")
            print(f"--------------------------------------------------")

            if total > 0:
                from Finance.models import Subscriptions 
                sub = Subscriptions.objects.filter(company_id=company_id, active=True).first()
                if sub:
                    sub.deduct_tokens(total)
                    print(f"✅ Successfully deducted {total} tokens from subscription for company {company_id}")
                    logger.info(f"Deducted {total} tokens for company {company_id}")
                else:
                    print(f"⚠️ Warning: No active subscription found to deduct tokens for company {company_id}")
        except Exception as e:
            print(f"❌ Error deducting tokens: {e}")
            logger.error(f"Error deducting tokens: {e}")

    # 5. Intent Handling (JSON Parsing)
    try:
        # Try to extract JSON from markdown code blocks first
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Fallback to finding first { and last }
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            json_str = json_match.group(0) if json_match else ""

        if json_str:
            print(f"DEBUG: Found JSON String: {json_str}")
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # Try correcting common LLM errors
                import ast
                try:
                    # Valid python dictionary? (e.g. 'None' instead of 'null', single quotes)
                    data = ast.literal_eval(json_str)
                except:
                    # Last ditch: simple cleanup
                    cleaned = json_str.replace("'", '"').replace("None", "null").replace("True", "true").replace("False", "false")
                    data = json.loads(cleaned)
            
            action = data.get("action")
            print(f"DEBUG: Action: {action}")
            
            if action == "check_availability":
                # checking logic
                date_str = data.get("date")
                slots = get_available_slots(company_id, date_str)
                if slots:
                    slot_str = ", ".join(slots)
                    system_msg = f"System Info: Available slots for {date_str or 'today'}: {slot_str}. Present these to the user nicely."
                else:
                    system_msg = f"System Info: No slots available for {date_str or 'today'}."
                
                # Re-prompt LLM
                response_2 = chain.invoke({
                    "company_name": company_name,
                    "context": context_text + "\n" + system_msg, 
                    "question": query, 
                    "history": history_text + f"\nAssistant (Internal): Checking slots for {date_str}.\nSystem: {system_msg}",
                    "tone": tone,
                    "current_date": datetime.now().strftime("%Y-%m-%d")
                })
                
                response_text = response_2.content
                
                # Accumulate tokens from second call
                if hasattr(response_2, 'response_metadata'):
                    usage = response_2.response_metadata.get('token_usage', {})
                    token_usage["input_tokens"] += usage.get('prompt_tokens', 0)
                    token_usage["output_tokens"] += usage.get('completion_tokens', 0)
                    token_usage["total_tokens"] += usage.get('total_tokens', 0)

                # Check if it returned JSON again (loop), if so, force text
                if "action" in response_text and "check_availability" in response_text:
                     deduct_tokens_now()
                     return {
                         "content": f"I checked the slots. {system_msg}",
                         "token_usage": token_usage
                     }
                
                deduct_tokens_now()
                return {
                    "content": response_text,
                    "token_usage": token_usage
                }
                
            elif action == "create_booking":
                from Others.helper import create_booking
                booking_details = data.get("booking_data")
                # Create Mock Request
                mock_req = MockRequest(data=booking_details)
                # Call helper
                try:
                    booking = create_booking(mock_req, company_id)
                    # Assuming create_booking returns a Booking object or Response
                    if hasattr(booking, 'id'):
                         deduct_tokens_now()
                         return {
                             "content": f"Booking confirmed! Your appointment for {booking.title} is set for {booking.start_time}.",
                             "token_usage": token_usage
                         }
                    else:
                         # It might return a Response object with errors
                         deduct_tokens_now()
                         return {
                             "content": "I encountered an issue processing your booking. Please try again.",
                             "token_usage": token_usage
                         }
                except Exception as e:
                    logger.error(f"Booking creation failed: {e}")
                    deduct_tokens_now()
                    return {
                        "content": "Sorry, I couldn't complete the booking at this moment.",
                        "token_usage": token_usage
                    }

    except Exception as e:
        # Not JSON or parsing failed, just return text
        print(f"DEBUG: JSON parsing failed: {e}")
        pass

    deduct_tokens_now()
    print(f"✅ --- get_ai_response finished (Company: {company_id}) ---\n")
    return {
        "content": response_text,
        "token_usage": token_usage
    }



if __name__ == "__main__":
    # Test
    test_history = [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello! How can I help you today?"}
    ]
    # NOTE: Set QDRANT_API_KEY and OPENAI_API_KEY env vars before running
    print("Testing Professional Tone:")
    # print(get_ai_response(2, "What is the training data about?", history=test_history, tone="professional"))
