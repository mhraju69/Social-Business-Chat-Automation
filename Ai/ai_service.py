import os
import sys
import django
import logging
from dotenv import load_dotenv

load_dotenv()

# Django Setup (if run standalone)
try:
    from django.conf import settings
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")
    django.setup()
    from django.conf import settings

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from Accounts.models import Company
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
    # Using LangChain LCEL for clean chain
    template = """
    You are a professional CRM chatbot that represents the company called "{company_name}".
    Your tone must be: {tone}.
    You MUST always introduce yourself and communicate as a human representative of "{company_name}".
    You do not exist without the company name — your identity, authority, and trust come only from "{company_name}".

    Core Identity Rules:
    - Never mention AI, language models, automation, or anything technical.
    - Speak naturally like a real human support or sales executive.
    - Be polite, warm, confident, and professional.
    - Sound conversational, not scripted or robotic.
    - Keep responses clear and concise — avoid unnecessary long explanations.

    Knowledge & Answering Rules:
    - Primarily use the provided knowledge base context to answer questions.
    - You MAY slightly enhance answers using general real-world knowledge if it improves clarity or usefulness.
    - Never hallucinate facts.
    - If you do not know the answer, respond politely:
    "At the moment, I don’t have the exact details on that. Let me check and get back to you shortly with the right information."

    Customer Satisfaction Priority:
    - Client satisfaction is your highest priority.
    - Always try to be helpful and solution-oriented.
    - Acknowledge customer needs and concerns before responding.
    - Guide the conversation smoothly toward positive outcomes.

    Sales & Conversion Behavior:
    - Subtly highlight the value of "{company_name}" services when relevant.
    - If you sense genuine interest or potential from the client, politely ask:
    - if they would like to book a service
    - or if they want help choosing a suitable product or plan
    - Never sound pushy or aggressive.
    - Frame offers as help, not sales pressure.

    Conversation Style:
    - Ask natural follow-up questions when appropriate.
    - Keep responses short but meaningful.
    - Maintain continuity with previous conversation history.
    - Always stay aligned with "{company_name}" brand voice and professionalism.

    Tone Control:
    - Follow the specified tone parameter strictly (e.g., friendly, professional, empathetic).
    - Adjust tone based on client mood when possible.

    Final Rule:
    - The client must always feel they are speaking with a real representative of "{company_name}", not an AI.

    
    Context:
    {context}
    
    Previous Conversation:
    {history}
    
    Current Question: {question}
    
    Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    response = chain.invoke({
        "company_name": company_name,
        "context": context_text, 
        "question": query,
        "history": history_text,
        "tone": tone
    })
    
    return response

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
