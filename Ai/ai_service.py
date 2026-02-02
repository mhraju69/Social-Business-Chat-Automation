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
from Accounts.models import Company, Service
from Finance.helper import create_stripe_checkout_for_service

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

def get_available_slots(company_id: int, date_str: str = None, duration_minutes: int = 60, service_obj=None) -> List[str]:
    """
    Calculate available slots for a given date based on OpeningHours and existing Bookings.
    Returns a list of strings representing available start times.
    """
    print(f"DEBUG: get_available_slots call for Company {company_id}, Date: {date_str}, Duration: {duration_minutes}m")
    try:
        from django.utils import timezone as django_timezone
        
        # Get company timezone
        company = Company.objects.filter(id=company_id).first()
        timezone_str = company.timezone if (company and company.timezone) else 'UTC'
        try:
            if any(char in timezone_str for char in ['+', '-']) or timezone_str.isdigit():
                 from Others.helper import parse_timezone_offset
                 user_tz = parse_timezone_offset(timezone_str)
            else:
                 user_tz = pytz.timezone(timezone_str)
        except Exception:
            user_tz = pytz.UTC

        # Get local time
        now_local = django_timezone.now().astimezone(user_tz)
        
        if not date_str:
            target_date = now_local
        else:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d")
                # Localize naive date from LLM to company timezone
                target_date = user_tz.localize(target_date)
            except ValueError:
                logger.error(f"Date parsing failed for {date_str}")
                return []
            
        # Get weekday (mon, tue, etc.)
        day_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        weekday = day_map[target_date.weekday()]
        
        # Get Opening Hours
        hours_qs = OpeningHours.objects.filter(company_id=company_id, day=weekday)
        if not hours_qs.exists():
            return [] # Closed
            
        # Get Bookings for this day (Querying in UTC)
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        bookings = Booking.objects.filter(
            company_id=company_id, 
            start_time__gte=start_of_day.astimezone(pytz.UTC),
            start_time__lt=end_of_day.astimezone(pytz.UTC)
        )
        
        booked_ranges = []
        for b in bookings:
            # Convert booking times to company local time
            b_start = b.start_time.astimezone(user_tz)
            if b.end_time:
                 b_end = b.end_time.astimezone(user_tz)
            else:
                 b_end = b_start + timedelta(hours=1)
            booked_ranges.append((b_start, b_end))
            
        # Get Booking Limit
        concurrent_limit = getattr(company, 'concurrent_booking_limit', 1)

        # Generate Slots based on opening hours and service duration
        slots = []
        slot_delta = timedelta(minutes=duration_minutes)
        # Minimum step between potential slots (e.g., every 30 mins) - or just use duration?
        # Typically, if duration is 60, slots are 10:00, 11:00.
        # If duration is 45, slots could be 10:00, 10:45? Or 10:00, 10:30? 
        # For simplicity, let's increment by duration or fixed 30 mins?
        # User request implies specific slots for service. Let's start with start-to-end packed.
        # But standard booking usually offers fixed intervals (e.g. 30min or 1hr). 
        # Let's align with the duration for now to ensure fit.
        step_delta = slot_delta # strict packing
        
        
        # Service Limit Constraints
        svc_start_limit = None
        svc_end_limit = None
        if service_obj and service_obj.start_time:
             svc_start_limit = target_date.replace(hour=service_obj.start_time.hour, minute=service_obj.start_time.minute, second=0, microsecond=0)
        if service_obj and service_obj.end_time:
             svc_end_limit = target_date.replace(hour=service_obj.end_time.hour, minute=service_obj.end_time.minute, second=0, microsecond=0)

        for hours in hours_qs:
            current = target_date.replace(hour=hours.start.hour, minute=hours.start.minute, second=0, microsecond=0)
            day_end = target_date.replace(hour=hours.end.hour, minute=hours.end.minute, second=0, microsecond=0)
            
            while current + slot_delta <= day_end:
                slot_end = current + slot_delta
                
                # Count overlaps
                overlap_count = 0
                for b_start, b_end in booked_ranges:
                     # Check if time ranges overlap
                     # (StartA < EndB) and (EndA > StartB)
                    if current < b_end and slot_end > b_start:
                        overlap_count += 1
                
                if overlap_count < concurrent_limit:
                    # Don't show past slots
                    if current > now_local:
                        # Check Service Limits
                        in_limits = True
                        if svc_start_limit and current < svc_start_limit:
                            in_limits = False
                        if svc_end_limit and slot_end > svc_end_limit:
                            in_limits = False
                        
                        if in_limits:
                            slots.append((current, current.strftime("%H:%M")))
                
                current += step_delta
        
        # Remove duplicates based on time, sort by time, then return strings
        unique_slots = sorted(list(set(slots)), key=lambda x: x[0])
        return [s[1] for s in unique_slots]
    except Exception as e:
        logger.error(f"Error calculating slots: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_multi_day_availability(company_id: int, days: int = 7, duration_minutes: int = 60, service_obj=None) -> Dict[str, List[str]]:
    """Get availability for the next N days"""
    from django.utils import timezone as django_timezone
    
    # Get company timezone
    company = Company.objects.filter(id=company_id).first()
    timezone_str = company.timezone if (company and company.timezone) else 'UTC'
    try:
        if any(char in timezone_str for char in ['+', '-']) or timezone_str.isdigit():
             from Others.helper import parse_timezone_offset
             user_tz = parse_timezone_offset(timezone_str)
        else:
             user_tz = pytz.timezone(timezone_str)
    except Exception:
        user_tz = pytz.UTC

    now_local = django_timezone.now().astimezone(user_tz)
    availability = {}
    
    for i in range(days):
        target_date = now_local + timedelta(days=i)
        date_str = target_date.strftime("%Y-%m-%d")
        slots = get_available_slots(company_id, date_str, duration_minutes=duration_minutes, service_obj=service_obj)
        if slots:
            availability[date_str] = slots
            
    return availability

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
    # REMOVED: Unsolicited injection of availability.
    # Logic is now handled via explicit tool calls (check_availability) to prevent spamming slots.

    # --- Service/Product List Context ---
    if company:
        try:
            services = Service.objects.filter(company=company)
            if services.exists():
                service_text = "\n\n--- AVAILABLE SERVICES & PRODUCTS ---\n"
                service_text += "Name | Price | Description\n"
                for s in services:
                    service_text += f"{s.name} | €{s.price} | Duration: {s.duration or 60} mins | {s.description or ''}\n"
                
                context_text += service_text
                logging.info(f"Attached {len(services)} services to context.")
        except Exception as e:
            logging.error(f"Error fetching services: {e}")

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
    You are a helpful customer support and sales person for "{company_name}".

        You always communicate as a real human working at "{company_name}".
        You never mention or imply AI, automation, models, systems, bots, or internal processes.

        Your tone must strictly follow: {tone}.

        ###CORE IDENTITY & BEHAVIOR
        - Introduce yourself as a representative of "{company_name}" only in the first message of a new conversation (or if history is empty/null).
        - If history exists, DO NOT repeat greetings or introductions.
        - Speak naturally, like a real support or sales executive.
        - Be polite, warm, confident, and professional.
        - Sound conversational and human — never robotic, scripted, or overly formal.
        - Keep responses clear, helpful, and concise.
        - Maintain continuity with the conversation history at all times.
        
        ###RESPONSE LENGTH & QUALITY
        - Default replies should be 2–5 short sentences.
        - Only give longer answers if the user clearly asks for details or explanation.
        - Avoid bullet lists unless the user asks for options or comparisons.
        - Never repeat the same sentence structure more than once in a conversation.
        - If a similar message is needed again, rephrase it naturally using different words.
        - SIMPLE LANGUAGE RULE: Use common, everyday words. Avoid long sentences and business jargon. Write like you’re texting a customer.

        ###USER INTENT & LANGUAGE UNDERSTANDING
        - Focus on what the user is trying to achieve, not just their exact wording.
        - Understand synonyms, paraphrasing, informal language, and typos naturally.
        - Treat semantically similar terms as the same (e.g., pricing = cost = plans).
        - Infer reasonable intent when the meaning is clear.
        - Ask clarifying questions ONLY if different interpretations would change the outcome.
        - Always detect the language of the user's message.
        - If the user mixes languages, reply in the language they mostly used.
        - If unclear, reply in the language of the first sentence.

        ###KNOWLEDGE & TRUTHFULNESS
        - First, rely ONLY on the provided context to answer questions.
        - The context may be incomplete, fragmented, or spread across multiple entries.
        - You must understand the meaning of the context and respond in your own words.
        - Do NOT copy or quote text verbatim from the context unless explicitly asked.
        - Synthesize, summarize, and paraphrase naturally — as a human would explain.

        If the context does NOT contain the answer:
        - Do NOT guess.
        - Do NOT use general knowledge.
        - Do NOT invent facts or company details.

        “At the moment, I don’t have the exact details on that. Let me check and get back to you shortly with the right information.”

        ###SCOPE & LIMITATIONS HANDLER
        - If the user asks for a service or product that is NOT listed in the context or is explicitly marked as out of stock:
        1. Politely inform them that it is currently unavailable or not offered.
        2. Immediately mention what IS available or what the company DOES offer.
        3. Do NOT make up services or products.

        - If the user asks for something completely unrelated to the company's business (e.g., asking for a car at a gym):
        1. Politely explain that this is "{company_name}" and we specialize in our specific services/products.
        2. Guide them back to the actual available services/products listed in the context.
        3. If the user asks unrelated questions more than twice, politely restate what we offer and ask how you can help with that.

        - For both cases, always be helpful and offer the current valid options.

        ###USER INTENT & LANGUAGE UNDERSTANDING
        - Focus on what the user is trying to achieve, not just their exact wording.
        - Understand synonyms, paraphrasing, informal language, and typos naturally.
        - Treat semantically similar terms as the same (e.g., pricing = cost = plans).
        - Infer reasonable intent when the meaning is clear.
        - Ask clarifying questions ONLY if different interpretations would change the outcome.

        ###ANSWER CONSTRUCTION RULE
        When responding:
        1. Understand the user’s intent.
        2. Identify relevant information from the context.
        3. Explain the answer clearly and naturally in your own words.
        4. Never expose internal reasoning or mention the context source.

        ###CUSTOMER SATISFACTION PRIORITY
        - Client satisfaction is the top priority.
        - Acknowledge the client’s need, concern, or question before offering solutions.
        - Be calm, reassuring, and solution-oriented.
        - Avoid defensive, rushed, or dismissive language.

        ###SALES & CONVERSION BEHAVIOR
        - Mention "{company_name}" services ONLY when relevant.
        - Offer bookings, plans, or product guidance ONLY if the client:
        • asks about services, pricing, plans, or availability
        • clearly shows interest or intent
        - Never push or upsell.
        - Keep recommendations helpful, subtle, and customer-focused.

        ###BOOKING & AVAILABILITY LOGIC
        - If the user shows interest in booking OR asks about availability (including queries like "available slots", or "what are your available slots?"):
        1. Identify the date they are interested in.
        2. If they mention "this week", "next days", or "weekly availability" → set date to null.
        3. If the date is vague (e.g. "tomorrow", "this Friday", "evening"), ask a single clarifying question before checking availability. Never assume a time.
        4. If no specific date/week is mentioned, assume TODAY ({current_date}).
        5. CRITICAL: You MUST ask the user to specify a SERVICE NAME before checking availability, unless they already mentioned it.
            - If the user asks about "slots" without naming a service, DO NOT check availability yet. Instead ask: "Which service are you looking to book?"
        6. If service is unknown, ask the user to choose from the available services list.
        7. ONLY AFTER a service is explicitly identified, check availability.
        
        CRITICAL: When checking availability, output ONLY the JSON block below. NO conversational text, NO explanations. Just the JSON.
        
        {{
            "action": "check_availability",
            "date": "YYYY-MM-DD" or null,
            "service_name": "Exact Service Name"
        }}
        - If the user wants to book:
        Collect the following details (ask only for what is missing):
        1. Service name / title
        2. Preferred date & time (Calculate exact YYYY-MM-DD based on current date {current_date} ({current_day})).
        IMPORTANT: If current month is December and user says "next January", the year must be next year.
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
        - AFTER a successful booking (when the system confirms it), you MUST ask: "Would you like to pay online now or pay later?"

        ###PAYMENT & CHECKOUT LOGIC
        - If the user wants to buy/pay for services/products (OR if they answer "pay online" to the booking question):
        
        1. Identify exactly which items they want (single or multiple).
        2. Respond with the list of items and the TOTAL price.
        3. Ask if they want to proceed with payment.
        
        - If a reply like "yes" or "okay" is ambiguous, briefly confirm the intent: "Just to confirm, would you like to pay online now?"
        
        - If they say YES/AGREE (or confirmed "pay online" previously):
        Ask for their:
        1. Email address (if not already known from booking)
        2. Address (if applicable/needed for billing)

        EXCEPTION: If the user just completed a booking and EXPLICITLY says "pay online" or "pay now", PROCEED DIRECTLY to create the payment link using the booked service logic. Do not ask for confirmation again if you have the email.
        
        - Once you have the Email, output JSON ONLY:
        {{
            "action": "create_payment_link",
            "payment_data": {{
                "items": ["Item Name 1", "Item Name 2"], 
                "email": "user@example.com",
                "address": "User Address" (or null if not provided)
            }}
        }}
    IMPORTANT:
        - Verify item names match the context list exactly if possible.
        - Do not invent prices. Use the ones from the context.
        - If the user just booked a service and wants to pay online, use that service name as the item name.

        ###TONE CONTROL & ADAPTATION
        - The primary tone is defined by: {tone}.
        - This base tone must ALWAYS be respected and never overridden.
        - You may apply subtle, human-like adjustments based on the user’s mood or situation, without changing the base tone.

        Examples of allowed micro-adjustments:
        - If the user sounds frustrated → be more patient, reassuring, and calm.
        - If the user sounds curious → be slightly more explanatory and engaging.
        - If the user sounds decisive → be more concise and action-focused.
        - If the user is rude or impatient → stay calm and respectful. Keep replies shorter, neutral, and solution-focused. Never mirror sarcasm or frustration.

        These adjustments must:
        - Stay fully aligned with the base tone.
        - Never change the brand personality.
        - Never contradict or replace the admin-defined tone.

        If a conflict exists, the base tone always takes priority.

        ###FINAL CHECK BEFORE SENDING
        - Does this sound like something a real person would say?
        - Is it friendly, short, and clear?
        - Can it be said in fewer words?
        - If yes → send.

        The user must never feel they are talking to a machine.
        Every response should feel like it came from a real, attentive human representative of "{company_name}".

        Context:
        {context}

        Conversation History:
        {history}

        User Question:
        {question}
    """
    
    prompt = ChatPromptTemplate.from_template(template)
    # Remove StrOutputParser to get full AIMessage object with metadata
    chain = prompt | llm 
    
    # Determine current time based on company timezone
    from django.utils import timezone as django_timezone
    timezone_str = company.timezone if (company and company.timezone) else 'UTC'
    try:
        if any(char in timezone_str for char in ['+', '-']) or timezone_str.isdigit():
             from Others.helper import parse_timezone_offset
             user_tz = parse_timezone_offset(timezone_str)
        else:
             user_tz = pytz.timezone(timezone_str)
    except Exception:
        user_tz = pytz.UTC
    
    current_dt = django_timezone.now().astimezone(user_tz)
    
    response = chain.invoke({
        "company_name": company_name,
        "context": context_text, 
        "question": query,
        "history": history_text,
        "tone": tone,
        "current_date": current_dt.strftime("%Y-%m-%d"),
        "current_day": current_dt.strftime("%A")
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
                service_name = data.get("service_name")
                
                # Resolve Service Duration
                duration_minutes = 60 # Default
                queried_services = []

                # Helper to get slots for a specific service
                def fetch_slots_for_service(srv_obj, d_str=None):
                    dur = srv_obj.duration if (srv_obj and srv_obj.duration) else 60
                    if d_str:
                        return get_available_slots(company_id, d_str, duration_minutes=dur, service_obj=srv_obj)
                    return None

                system_msg = ""
                
                if service_name:
                    # Find specific service
                    svc = Service.objects.filter(company_id=company_id, name__iexact=service_name).first()
                    if not svc:
                        # Fuzzy match or fallback?
                        svc = Service.objects.filter(company_id=company_id, name__icontains=service_name).first()
                    
                    if svc:
                         duration_minutes = svc.duration if svc.duration else 60
                         print(f"DEBUG: Checking Service '{svc.name}' with duration {duration_minutes}m")
                         queried_services.append(svc)
                    else:
                         system_msg = f"System Info: Service '{service_name}' not found. Ask user to pick from available services."
                else:
                    # No service specified - Check ALL services as requested by user fallback
                    # "if service not specified then return slots of all services specifically defining the service names"
                    all_services = Service.objects.filter(company_id=company_id)
                    if all_services.exists():
                        queried_services.extend(all_services)
                    else:
                        # No services configured at all?
                        pass

                if not system_msg:
                    # We have services to check
                    if not queried_services:
                        # Should have caught this above, but fallback
                        system_msg = "System Info: No services configured for this company."
                    else:
                        full_report = []
                        for svc in queried_services:
                            svc_dur = svc.duration if svc.duration else 60
                            if date_str:
                                slots = get_available_slots(company_id, date_str, duration_minutes=svc_dur, service_obj=svc)
                                if slots:
                                    slot_str = ", ".join(slots)
                                    full_report.append(f"Service '{svc.name}': {slot_str}")
                                else:
                                    full_report.append(f"Service '{svc.name}': No slots available.")
                            else:
                                # Multi-day check? 
                                # Limit to next 3 days to avoid token explosion if checking ALL services
                                availability = get_multi_day_availability(company_id, days=3, duration_minutes=svc_dur, service_obj=svc)
                                if availability:
                                    avail_text = ""
                                    for d, s in availability.items():
                                        avail_text += f"  {d}: {', '.join(s)}\n"
                                    full_report.append(f"Service '{svc.name}':\n{avail_text}")
                                else:
                                    full_report.append(f"Service '{svc.name}': No availability next 3 days.")
                        
                        system_msg = "System Info: Availability Report:\n" + "\n".join(full_report)

                # Re-prompt LLM using same current_dt
                response_2 = chain.invoke({
                    "company_name": company_name,
                    "context": context_text + "\n" + system_msg, 
                    "question": query, 
                    "history": history_text + f"\nAssistant (Internal): Checking slots for {date_str or 'next few days'} for {service_name or 'all services'}.\nSystem: {system_msg}",
                    "tone": tone,
                    "current_date": current_dt.strftime("%Y-%m-%d"),
                    "current_day": current_dt.strftime("%A")
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
                         "content": f"Here is the availability info: {system_msg}",
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
                
                # Validation: Prevent past bookings
                # Validation: Prevent past bookings
                start_time_str = booking_details.get("start_time")
                if start_time_str:
                    try:
                         # Handle typical format "YYYY-MM-DD HH:MM:SS"
                         # Parse naive datetime from user input
                         try:
                             s_time_naive = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
                         except ValueError:
                             try:
                                s_time_naive = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S")
                             except ValueError:
                                s_time_naive = None
                         
                         if s_time_naive:
                             # Localize to company timezone (user_tz is defined in outer scope)
                             if django_timezone.is_naive(s_time_naive):
                                 s_time_aware = user_tz.localize(s_time_naive)
                             else:
                                 s_time_aware = s_time_naive.astimezone(user_tz)
                             
                             # Compare with current UTC time
                             now_aware = django_timezone.now()
                             
                             if s_time_aware < now_aware:
                                 deduct_tokens_now()
                                 return {
                                     "content": f"I cannot book appointments in the past ({start_time_str}). Please search for a future time slot.",
                                     "token_usage": token_usage
                                 }
                    except Exception as e:
                        # If format is weird, maybe let backend handle or fail safe?
                        logger.error(f"Date validation error: {e}")
                        pass


                # Create Mock Request
                mock_req = MockRequest(data=booking_details)
                # Call helper
            
                try:
                    booking = create_booking(mock_req, company_id)
                    # Assuming create_booking returns a Booking object or Response
                    if hasattr(booking, 'id'):
                         # Show local time in the confirmation message using utility function
                         from Others.helper import utc_to_local
                         timezone_str = company.timezone if (company and company.timezone) else 'UTC'
                         local_time = utc_to_local(booking.start_time, timezone_str)
                         formatted_time = local_time.strftime('%Y-%m-%d %H:%M')
                         
                         deduct_tokens_now()
                         return {
                             "content": f"Booking confirmed! Your appointment for {booking.title} is set for {formatted_time}. Would you like to pay online now or pay later?",
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

            elif action == "create_payment_link":
                payment_data = data.get("payment_data", {})
                items = payment_data.get("items", [])
                email = payment_data.get("email")
                address = payment_data.get("address", "")
                
                if not items or not email:
                    # Missing info, prompt user back
                     deduct_tokens_now()
                     return {
                         "content": "I need both the list of items and your email address to generate a payment link.",
                         "token_usage": token_usage
                     }

                # Calculate Amount securely from DB
                total_amount = 0.0
                valid_items = []
                
                # Fetch all company services to match
                db_services = Service.objects.filter(company_id=company_id)
                
                for item_name in items:
                    # Simple case-insensitive matching
                    service = next((s for s in db_services if s.name.lower() == item_name.lower()), None)
                    if service:
                        total_amount += float(service.price)
                        valid_items.append(service.name)
                    else:
                        # Fallback: if exact match fails, maybe the AI passed a close name? 
                        # For now, we'll just log it or add 0, or trust the user? 
                        # Security-wise, skipping unknown items is safer.
                        pass
                
                if total_amount <= 0:
                     deduct_tokens_now()
                     return {
                         "content": "I couldn't find the specific prices for those items. Please verify the exact service names.",
                         "token_usage": token_usage
                     }

                reason = ", ".join(valid_items)
                if address:
                    reason += f" (Address: {address})"
                
                try:
                    payment = create_stripe_checkout_for_service(
                        company_id=company_id,
                        email=email,
                        amount=total_amount,
                        reason=reason
                    )
                    
                    if payment and payment.url:
                        deduct_tokens_now()
                        return {
                            "content": f"Here is your payment link for {reason} (Total: €{total_amount}):\n{payment.url}\n\nPlease complete the payment to proceed.",
                            "token_usage": token_usage
                        }
                    else:
                        deduct_tokens_now()
                        return {
                            "content": "I wasn't able to generate the payment link correctly. Please try again later.",
                            "token_usage": token_usage
                        }
                except ValueError as e:
                     deduct_tokens_now()
                     return {
                         "content": f"I couldn't generate the link: {str(e)}",
                         "token_usage": token_usage
                     }
                except Exception as e:
                     logger.error(f"Payment Link Generation Error: {e}")
                     deduct_tokens_now()
                     return {
                         "content": "An internal error occurred while generating the payment link.",
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
