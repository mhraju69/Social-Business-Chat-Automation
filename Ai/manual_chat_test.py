import os
import sys
import logging
from dotenv import load_dotenv
from typing import List, Dict, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Load environment variables
load_dotenv()

# Configuration (Mirrors ai_service.py)
QDRANT_URL = "https://deed639e-bc0e-43fe-8dc2-2edaed834f41.europe-west3-0.gcp.cloud.qdrant.io:6333"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COLLECTION_NAME = "company_knowledge"

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

def get_manual_rag_response(company_id: int, company_name: str, query: str, history: Optional[List[Dict]] = None, tone: str = "professional") -> str:
    """
    Standalone RAG function for manual testing.
    Directly queries Qdrant and OpenAI, bypassing Django models.
    """
    
    # 1. Initialize Clients
    if not QDRANT_API_KEY:
        return "System Error: Qdrant API Key missing in .env"
    if not OPENAI_API_KEY:
        return "System Error: OpenAI API Key missing in .env"
        
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)
    llm = ChatOpenAI(model="gpt-4o", openai_api_key=OPENAI_API_KEY, temperature=0.7)
    
    # 2. Embed Query & Search
    try:
        query_vector = embeddings.embed_query(query)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return "I'm having trouble understanding that right now."
        
    # Filter by company_id
    search_filter = rest.Filter(
        must=[
            rest.FieldCondition(key="company_id", match=rest.MatchValue(value=company_id))
        ]
    )
    
    print(f"Searching Qdrant for Company ID: {company_id}...")
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=search_filter,
        limit=5
    ).points
    
    print(f"Found {len(results)} relevant chunks.")
    # Optional: Print chunk previews for debugging
    # for i, res in enumerate(results):
    #     print(f"Chunk {i+1}: {res.payload.get('text', '')[:50]}...")

    # 3. Construct Context
    context_text = "\n\n".join([res.payload.get('text', '') for res in results])
    
    if not context_text:
        context_text = "No specific company documents found."
        print("WARNING: No context found for this query.")

    # Format History
    history_text = ""
    if history:
        for msg in history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            history_text += f"{role}: {content}\n"
    
    if not history_text:
        history_text = "No previous conversation."

    # 4. Generate Response using the same template as ai_service.py
    template = """
    You are a professional CRM chatbot representing the company "{company_name}".

    Your tone must be: {tone}.
    You always communicate as a real human representative of "{company_name}".

    Core Identity Rules:
    - Introduce yourself as a representative of "{company_name}" ONLY if this is the first message in the conversation (when Previous Conversation is "No previous conversation.").
    - Do NOT repeat greetings or introductions in follow-up messages.
    - Never mention AI, automation, language models, or technical systems.
    - Speak naturally like a real support or sales executive.
    - Be polite, warm, confident, and professional.
    - Sound conversational, not scripted.
    - Keep responses clear and concise.
    - Do not use any technical jargon or complex language.
    - Use simple and easy-to-understand language.
    - Do not use any emojis.

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
    
    Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    print("Generating response...")
    response = chain.invoke({
        "company_name": company_name,
        "context": context_text, 
        "question": query,
        "history": history_text,
        "tone": tone
    })
    
    return response

def main():
    print("--- Manual AI Chat Test (Direct Qdrant Connection) ---")
    
    # 1. Get Setup Info
    try:
        company_id_input = input("Enter Company ID (e.g., 2): ").strip()
        company_id = int(company_id_input)
    except ValueError:
        print("Invalid Company ID. Using default: 2")
        company_id = 2

    company_name = input("Enter Company Name (default: 'The Company'): ").strip()
    if not company_name:
        company_name = "The Company"

    tone = input("Enter Tone (default: professional): ").strip()
    if not tone:
        tone = "professional"

    print(f"\nStarting chat session.")
    print(f"Company: {company_name} (ID: {company_id})")
    print(f"Tone: {tone}")
    print("Type 'exit' or 'quit' to stop.\n")

    history = []

    # 2. Chat Loop
    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ["exit", "quit"]:
                print("Exiting chat...")
                break
            
            if not user_input:
                continue

            response = get_manual_rag_response(
                company_id=company_id,
                company_name=company_name,
                query=user_input,
                history=history,
                tone=tone
            )

            print(f"AI: {response}\n")

            # Update history
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})

        except KeyboardInterrupt:
            print("\nExiting chat...")
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
