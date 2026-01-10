import os
import sys
import logging
import django
from datetime import datetime, timedelta

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")
try:
    from django.conf import settings
    if not settings.configured:
        django.setup()
except ImportError:
    pass

from Ai.ai_service import get_ai_response
from Accounts.models import Service

# Logging
logging.basicConfig(level=logging.INFO)

def run_test():
    company_id = 2 
    
    # OUTPUT FILE
    out_file = "verification_output.txt"
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"--- Automated Payment Flow Verification (Company {company_id}) ---\n")
        
        # 1. Get a Service
        service = Service.objects.filter(company_id=company_id).first()
        if not service:
            f.write("❌ No services found for company 2. Cannot test specific booking.\n")
            return

        service_name = service.name
        f.write(f"🎯 Target Service: {service_name}\n")
        
        history = []
        
        # 2. Step 1: Book the service
        tomorrow = datetime.now() + timedelta(days=1)
        date_str = tomorrow.strftime("%Y-%m-%d")
        time_str = "10:00"
        
        user_msg_1 = f"I want to book a {service_name} on {date_str} at {time_str}. My email is test@example.com."
        f.write(f"\n👤 User: {user_msg_1}\n")
        
        print(f"Sending booking request...")
        resp1 = get_ai_response(company_id, user_msg_1, history=history)
        content1 = resp1.get("content", "")
        f.write(f"🤖 AI: {content1}\n")
        
        history.append({"role": "user", "content": user_msg_1})
        history.append({"role": "assistant", "content": content1})
        
        # Check if AI asked for payment
        if "pay" in content1.lower() and ("online" in content1.lower() or "later" in content1.lower()):
            f.write("✅ PASS: AI asked for payment preference.\n")
        else:
            f.write("❌ FAIL: AI did not ask for payment preference explicitly.\n")
        
        # 3. Step 2: Pay Online
        user_msg_2 = "I want to pay online now."
        f.write(f"\n👤 User: {user_msg_2}\n")
        
        print(f"Sending payment request...")
        resp2 = get_ai_response(company_id, user_msg_2, history=history)
        content2 = resp2.get("content", "")
        f.write(f"🤖 AI: {content2}\n")
        
        if "stripe.com" in content2 or "http" in content2:
            f.write("✅ PASS: AI provided a link (likely Stripe).\n")
        else:
            f.write(f"⚠️ WARN: AI did not provide a link. Response was: {content2}\n")
            if resp2.get('token_usage'):
                 f.write(f"Token usage: {resp2['token_usage']}\n")

if __name__ == "__main__":
    run_test()
