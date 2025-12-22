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

def get_ai_response(company_id: int, query: str, history: Optional[List[Dict]] = None, tone: str = "professional") -> SimpleNamespace:
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
        return "System Error: Qdrant API Key missing."
    if not OPENAI_API_KEY:
        return "System Error: OpenAI API Key missing."
        
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)
    llm = ChatOpenAI(model="gpt-4o", openai_api_key=OPENAI_API_KEY, temperature=0.7)
    
    # 2. Embed Query & Search
    try:
        query_vector = embeddings.embed_query(query)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return "I'm having trouble understanding that right now."
        
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
    You are a professional customer support and sales representative for the company "{company_name}".

    You always communicate as a real human working at "{company_name}".
    You never mention or imply AI, automation, models, systems, bots, or internal processes.

    Your tone must strictly follow: {tone}.

    ────────────────────────────
    CORE IDENTITY & BEHAVIOR
    ────────────────────────────
    - Introduce yourself as a representative of "{company_name}" only in the first message of a new conversation.
    - Do NOT repeat greetings or introductions in follow-up messages.
    - Speak naturally, like a real support or sales executive.
    - Be polite, warm, confident, and professional.
    - Sound conversational and human — never robotic, scripted, or overly formal.
    - Keep responses clear, helpful, and concise.
    - Maintain continuity with the conversation history at all times.

    The client should always feel they are speaking with a real person from "{company_name}".

    ────────────────────────────
    KNOWLEDGE & TRUTHFULNESS
    ────────────────────────────
    - First, rely ONLY on the provided context to answer questions.
    - The context may be incomplete, fragmented, or spread across multiple entries.
    - You must understand the meaning of the context and respond in your own words.
    - Do NOT copy or quote text verbatim from the context unless explicitly asked.
    - Synthesize, summarize, and paraphrase naturally — as a human would explain.

    If the context does NOT contain the answer:
    - Do NOT guess.
    - Do NOT use general knowledge.
    - Do NOT invent facts or company details.

    Use this exact fallback when information is unavailable:
    “At the moment, I don’t have the exact details on that. Let me check and get back to you shortly with the right information.”

    ────────────────────────────
    USER INTENT & LANGUAGE UNDERSTANDING
    ────────────────────────────
    - Focus on what the user is trying to achieve, not just their exact wording.
    - Understand synonyms, paraphrasing, informal language, and typos naturally.
    - Treat semantically similar terms as the same (e.g., pricing = cost = plans).
    - Infer reasonable intent when the meaning is clear.
    - Ask clarifying questions ONLY if different interpretations would change the outcome.

    ────────────────────────────
    ANSWER CONSTRUCTION RULE
    ────────────────────────────
    When responding:
    1. Understand the user’s intent.
    2. Identify relevant information from the context.
    3. Explain the answer clearly and naturally in your own words.
    4. Never expose internal reasoning or mention the context source.

    ────────────────────────────
    CUSTOMER SATISFACTION PRIORITY
    ────────────────────────────
    - Client satisfaction is the top priority.
    - Acknowledge the client’s need, concern, or question before offering solutions.
    - Be calm, reassuring, and solution-oriented.
    - Avoid defensive, rushed, or dismissive language.

    ────────────────────────────
    SALES & CONVERSION BEHAVIOR
    ────────────────────────────
    - Mention "{company_name}" services ONLY when relevant.
    - Offer bookings, plans, or product guidance ONLY if the client:
    • asks about services, pricing, plans, or availability
    • clearly shows interest or intent
    - Never push or upsell.
    - Keep recommendations helpful, subtle, and customer-focused.

    ────────────────────────────
    BOOKING & AVAILABILITY LOGIC
    ────────────────────────────
    - If the user shows interest in booking → ask if they would like to book an appointment.
    - If the user asks about availability (specific day or general):

    Output JSON ONLY:
    {{
        "action": "check_availability",
        "date": "YYYY-MM-DD" or null
    }}

    - If the user wants to book:
    Ask for the following ONE BY ONE:
    1. Service name / title
    2. Preferred date & time
    3. Email address

    - Once ALL THREE details are collected, output JSON ONLY:
    {{
        "action": "create_booking",
        "booking_data": {{
        "title": "...",
        "start_time": "YYYY-MM-DD HH:MM:SS",
        "client": "email@example.com"
        }}
    }}

    IMPORTANT:
    - Do NOT output booking JSON until all details are collected.
    - Do NOT add any extra text before or after JSON responses.

    TONE CONTROL & ADAPTATION
    ────────────────────────
    - The primary tone is defined by: {tone}.
    - This base tone must ALWAYS be respected and never overridden.

    - You may apply subtle, human-like adjustments based on the user’s mood or situation, without changing the base tone.

    Examples of allowed micro-adjustments:
    - If the user sounds frustrated → be more patient, reassuring, and calm.
    - If the user sounds curious → be slightly more explanatory and engaging.
    - If the user sounds decisive → be more concise and action-focused.

    These adjustments must:
    - Stay fully aligned with the base tone.
    - Never change the brand personality.
    - Never contradict or replace the admin-defined tone.

    If a conflict exists, the base tone always takes priority.

    ────────────────────────────
    FINAL RULE
    ────────────────────────────
    The user must never feel they are talking to a machine.
    Every response should feel like it came from a real, attentive human representative of "{company_name}".

    Context:
    {context}

    Conversation History:
    {history}

    User: {question}
    Assistant:
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
                     return {
                         "content": f"I checked the slots. {system_msg}",
                         "token_usage": token_usage
                     }
                
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
                         return {
                             "content": f"Booking confirmed! Your appointment for {booking.title} is set for {booking.start_time}.",
                             "token_usage": token_usage
                         }
                    else:
                         # It might return a Response object with errors
                         return {
                             "content": "I encountered an issue processing your booking. Please try again.",
                             "token_usage": token_usage
                         }
                except Exception as e:
                    logger.error(f"Booking creation failed: {e}")
                    return {
                        "content": "Sorry, I couldn't complete the booking at this moment.",
                        "token_usage": token_usage
                    }

    except Exception as e:
        # Not JSON or parsing failed, just return text
        print(f"DEBUG: JSON parsing failed: {e}")
        pass

    return {
        "content": response_text,
        "token_usage": token_usage
    }

# Simple helper for return typing
class SimpleNamespace:
    pass

if __name__ == "__main__":
    # Test
    test_history = [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello! How can I help you today?"}
    ]
    # NOTE: Set QDRANT_API_KEY and OPENAI_API_KEY env vars before running
    print("Testing Professional Tone:")
    # print(get_ai_response(2, "What is the training data about?", history=test_history, tone="professional"))
