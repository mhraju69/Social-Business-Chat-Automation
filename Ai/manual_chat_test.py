import os
import sys
import logging
from typing import List, Dict, Optional

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from ai_service (which handles django setup)
try:
    from Ai.ai_service import get_ai_response
except ImportError:
    from ai_service import get_ai_response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("--- Manual AI Chat Test (Integrated with ai_service) ---")
    
    # 1. Get Setup Info
    try:
        company_id_input = input("Enter Company ID (e.g., 2): ").strip()
        company_id = int(company_id_input)
    except ValueError:
        print("Invalid Company ID. Using default: 2")
        company_id = 2

    # Company name is fetched inside ai_service now, but tone is passed
    tone = input("Enter Tone (default: professional): ").strip()
    if not tone:
        tone = "professional"

    print(f"\nStarting chat session.")
    print(f"Company ID: {company_id}")
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

            # Call the actual service function
            response = get_ai_response(
                company_id=company_id,
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
