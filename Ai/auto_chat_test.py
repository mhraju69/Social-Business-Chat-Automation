import os
import sys
import logging
from typing import List, Dict

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from ai_service
try:
    from Ai.ai_service import get_ai_response
except ImportError:
    from ai_service import get_ai_response

# Configure Logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Test Scenarios
TEST_SCENARIOS = [
    {
        "step": "Introduction",
        "input": "Hello",
        "expected_keywords": ["IronPulse Fitness", "representative"]
    },
    {
        "step": "Company Info",
        "input": "What does your company do?",
        "expected_keywords": ["fitness", "gym", "wellness"]
    },
    {
        "step": "Opening Hours",
        "input": "When are you open?",
        "expected_keywords": ["open", "am", "pm"]
    },
    {
        "step": "Services List",
        "input": "What services do you offer?",
        "expected_keywords": ["Steam Bath", "Zumba", "Yoga"] 
    },
    {
        "step": "Booking Availability",
        "input": "Are you available next Monday?",
        "expected_keywords": ["System Info", "slots", "available"] # AI should check slots
    },
    {
        "step": "Booking Creation",
        "input": "I want to book a Session for next Monday at 10am. My email is auto_test@example.com.",
        "expected_keywords": ["Booking confirmed", "auto_test@example.com"]
    },
    {
        "step": "Payment Intent (Multiple Items)",
        "input": "I want to buy a Steam Bath and Zumba classes.",
        "expected_keywords": ["Steam Bath", "Zumba", "total", "proceed"]
    },
    {
        "step": "Payment Confirmation",
        "input": "Yes",
        "expected_keywords": ["email"]
    },
    {
        "step": "Payment Details",
        "input": "auto_pay@example.com, Test Address 123",
        "expected_keywords": ["checkout.stripe.com", "payment link"]
    }
]

def run_tests():
    print("\n🚀 --- STARTING AUTOMATED CHATBOT TEST --- 🚀\n")
    
    company_id = 2  # Default test company
    tone = "professional"
    history = []
    
    passed_steps = 0
    total_steps = len(TEST_SCENARIOS)

    for i, scenario in enumerate(TEST_SCENARIOS):
        step_name = scenario["step"]
        user_input = scenario["input"]
        expected_keywords = scenario.get("expected_keywords", [])
        
        print(f"🔹 [Step {i+1}/{total_steps}] {step_name}")
        print(f"   User: {user_input}")
        
        try:
            # Call AI Service
            response_data = get_ai_response(
                company_id=company_id,
                query=user_input,
                history=history,
                tone=tone
            )
            
            # Extract content
            ai_content = response_data.get("content", "")
            token_usage = response_data.get("token_usage", {})
            
            print(f"   AI: {ai_content}")
            print(f"   [Tokens] {token_usage}")
            
            # Update History
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": ai_content})
            
            # Validation
            missing_keywords = [kw for kw in expected_keywords if kw.lower() not in ai_content.lower()]
            
            if missing_keywords:
                print(f"   ❌ FAILED: Missing keywords: {missing_keywords}")
            else:
                print(f"   ✅ PASSED")
                passed_steps += 1
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()

        print("-" * 50 + "\n")

    print(f"📊 TEST SUMMARY: {passed_steps}/{total_steps} Steps Passed.\n")

if __name__ == "__main__":
    run_tests()
