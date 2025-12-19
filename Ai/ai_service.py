import os
import sys
import django
import logging
from dotenv import load_dotenv

load_dotenv()

# Django Setup (if run standalone)
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
from typing import List, Dict, Optional
from Accounts.models import Company
import json
from datetime import datetime, timedelta
import pytz

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
    from Others.models import OpeningHours, Booking
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
        # Note: Booking times are stored in UTC usually, need to handle timezone carefully.
        # For simplicity in this mock, we assume naive or inconsistent times are aligned.
        # In production, use strict timezone handling.
        bookings = Booking.objects.filter(
            company_id=company_id, 
            start_time__date=target_date.date()
        )
        
        booked_ranges = []
        for b in bookings:
            # We assume booking start/end are datetime objects
            # Convert to naive for comparison if needed
            b_start = b.start_time.replace(tzinfo=None) if b.start_time.tzinfo else b.start_time
            b_end = b.end_time.replace(tzinfo=None) if b.end_time and b.end_time.tzinfo else (b.end_time or (b_start + timedelta(hours=1)))
            booked_ranges.append((b_start, b_end))
            
        # Generate Slots (Hourly)
        slots = []
        current = start_time
        while current + timedelta(hours=1) <= end_time:
            slot_end = current + timedelta(hours=1)
            is_taken = False
            for b_start, b_end in booked_ranges:
                # Check overlap: (StartA <= EndB) and (EndA >= StartB)
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
# Re-use config from ingestion or define here 
# (Ideally, shared config file is better, but keeping in 'Ai/' as requested)
QDRANT_URL = "https://deed639e-bc0e-43fe-8dc2-2edaed834f41.europe-west3-0.gcp.cloud.qdrant.io:6333"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COLLECTION_NAME = "company_knowledge"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from typing import List, Dict, Optional

# ... imports ...

def get_ai_response(company_id: int, query: str, history: Optional[List[Dict]] = None, tone: str = "professional") -> str:
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
    
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=search_filter,
        limit=5
    ).points

    company = Company.objects.get(id=company_id)
    
    logging.info(f"Found {len(results)} relevant chunks.")
    
    # 3. Construct Context
    context_text = "\n\n".join([res.payload.get('text', '') for res in results])
    
    if not context_text:
        context_text = "No specific company documents found."

    # Format History
    history_text = ""
    if history:
        for msg in history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            history_text += f"{role}: {content}\n"
    
    if not history_text:
        history_text = "No previous conversation."
    company_name = company.name or "Unknown"
    # 4. Generate Response
    # Using LangChain LCEL
    template = """
    You are a professional CRM chatbot representing the company "{company_name}".

    Your tone must be: {tone}.
    You always communicate as a real human representative of "{company_name}".
    
    Core Identity Rules:
    - Introduce yourself as a representative of "{company_name}" only in the first message of a new conversation.
    - Do not repeat greetings or introductions in follow-up messages.
    - Never mention AI, automation, language models, or technical systems.
    - Speak naturally like a real support or sales executive.
    - Be polite, warm, confident, and professional.
    - Sound conversational, not scripted.
    - Keep responses clear and concise.

    Knowledge & Answering Rules:
    - First, rely on the provided context to answer questions.
    - If the context does not contain the answer, use only safe general knowledge.
    - Never invent facts or specific details about "{company_name}".
    - If information is unavailable, respond politely:
    "At the moment, I don’t have the exact details on that. Let me check and get back to you shortly with the right information."

    Customer Satisfaction Priority:
    - Client satisfaction is the top priority.
    - Acknowledge the client’s needs or concerns before providing solutions.
    - Be helpful, calm, and solution-oriented.

    Sales & Conversion Behavior:
    - Mention "{company_name}" services only when relevant.
    - Offer booking or product guidance only if the client:
    • asks about services, pricing, plans, or availability
    • shows clear interest or intent
    - Keep offers helpful and never pushy.
    
    Booking & Availability Logic:
    - If user shows interest -> Ask if they want to book an appointment.
    - If user asks for availability/slots for a specific day or generally -> Output JSON: {{"action": "check_availability", "date": "YYYY-MM-DD" (or null)}}. **Do this even if they haven't picked a service yet.**
    - If user wants to book -> Ask for "Service Name/Title", "Date & Time", and "Email" one by one.
    - Once ALL details (Title, Time, Email) are collected, output JSON:
      {{
        "action": "create_booking",
        "booking_data": {{
          "title": "...",
          "start_time": "YYYY-MM-DD HH:MM:SS",
          "client": "email@example.com"
        }}
      }}
    - IMPORTANT: Do NOT output JSON until you have all 3 fields. Ask clarifying questions first.


    Conversation Style:
    - Maintain continuity with the conversation history.
    - Avoid repeating greetings, phrases, or explanations.
    - Ask natural follow-up questions only when helpful.
    - Stay aligned with "{company_name}" brand voice.

    Tone Control:
    - Follow the specified tone strictly.
    - Adapt tone slightly based on the client’s mood when appropriate.

    Final Rule:
    - The client should always feel they are speaking with a real representative of "{company_name}".

    
    Context:
    {context}
    
    Previous Conversation:
    {history}
    
    Current Question: {question}
    Current Date: {current_date}
    
    Answer:"""
    
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
        # Check for JSON block
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            print(f"DEBUG: Found JSON: {json_match.group(0)}")
            data = json.loads(json_match.group(0))
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
        pass

    return {
        "content": response_text,
        "token_usage": token_usage
    }

if __name__ == "__main__":
    # Test
    # Simulate a history
    test_history = [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello! How can I help you today?"}
    ]
    print("Testing Professional Tone:")
    print(get_ai_response(2, "What is the training data about?", history=test_history, tone="professional"))
    print("\nTesting Friendly Tone:")
    print(get_ai_response(2, "What is the training data about?", history=test_history, tone="friendly"))
