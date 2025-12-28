import os
import sys
import django
from datetime import datetime, timedelta

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")

try:
    from django.conf import settings
    if not settings.configured:
        django.setup()
except ImportError:
    pass

from Others.models import OpeningHours, Booking
from Accounts.models import Company
from Ai.ai_service import get_available_slots

def debug_slots():
    with open("debug_output.txt", "w") as f:
        # Redirect stdout to file
        sys.stdout = f
        
        company_id = 2
        print(f"--- Debugging Slots for Company ID: {company_id} ---")

        # 1. Check Company
        try:
            company = Company.objects.get(id=company_id)
            print(f"Company Found: {company.name}")
        except Company.DoesNotExist:
            print("Company NOT found!")
            return

        # 2. Check Opening Hours
        print("\n--- Opening Hours ---")
        ohs = OpeningHours.objects.filter(company_id=company_id)
        if not ohs.exists():
            print("NO Opening Hours found for this company! loops will always return []")
        else:
            for oh in ohs:
                print(f"Day: {oh.day}, Start: {oh.start}, End: {oh.end}")

        # 3. Check Bookings
        print("\n--- Existing Bookings (Next 7 days) ---")
        now = datetime.now()
        bookings = Booking.objects.filter(company_id=company_id, start_time__gte=now)
        for b in bookings:
            print(f"Booking: {b.title}, Start: {b.start_time}, End: {b.end_time}")

        # 4. Test get_available_slots
        print("\n--- Testing get_available_slots ---")
        # Test today and next 3 days
        for i in range(4):
            date = now + timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            print(f"Checking date: {date_str}")
            slots = get_available_slots(company_id, date_str)
            print(f"Available Slots: {slots}")

if __name__ == "__main__":
    debug_slots()
