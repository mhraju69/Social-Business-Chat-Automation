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

# Re-use config from ingestion or define here 
# (Ideally, shared config file is better, but keeping in 'Ai/' as requested)
QDRANT_URL = "https://deed639e-bc0e-43fe-8dc2-2edaed834f41.europe-west3-0.gcp.cloud.qdrant.io:6333"
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COLLECTION_NAME = "company_knowledge"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_ai_response(company_id: int, query: str) -> str:
    """
    Generates an AI response for a specific company using RAG.
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
    
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        query_filter=search_filter,
        limit=5
    )
    
    logging.info(f"Found {len(results)} relevant chunks.")
    
    # 3. Construct Context
    context_text = "\n\n".join([res.payload.get('text', '') for res in results])
    
    if not context_text:
        context_text = "No specific company documents found."

    # 4. Generate Response
    # Using LangChain LCEL for clean chain
    template = """You are a helpful assistant for a specific company. 
    Use the following pieces of retrieved context to answer the user's question. 
    If you don't know the answer based on the context, say that you don't know, don't try to make up an answer.
    
    Context:
    {context}
    
    Question: {question}
    
    Answer:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    response = chain.invoke({"context": context_text, "question": query})
    
    return response

if __name__ == "__main__":
    # Test
    print(get_ai_response(2, "What is the training data about?"))
