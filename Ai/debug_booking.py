import os
import sys
import logging

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from ai_service
try:
    from Ai.ai_service import get_ai_response
except ImportError:
    from ai_service import get_ai_response

logging.basicConfig(level=logging.ERROR) # Only show errors to keep output clean

def debug_booking():
    with open("debug_booking_output.txt", "w", encoding='utf-8') as f:
        sys.stdout = f
        
        company_id = 2
        
        print("\n--- Step 1: Check Availability ---")
        # Ask about date availability
        r1 = get_ai_response(company_id, "Are you available next Monday?", history=[])
        print(f"AI: {r1.get('content')}")
        
        # Also test with a specific date query if possible or let the AI resolve "next monday"
        
        print("\n--- Step 2: Create Booking ---")
        history = [{"role": "user", "content": "Are you available next Monday?"}, {"role": "assistant", "content": r1.get('content')}]
        query = "I want to book a Steam Bath for next Monday at 10am. My email is debug@example.com."
        print(f"User: {query}")
        r2 = get_ai_response(company_id, query, history=history)
        print(f"AI Response Full: {r2}")
        print(f"AI Content: {r2.get('content')}")

if __name__ == "__main__":
    debug_booking()
