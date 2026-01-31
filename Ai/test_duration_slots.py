
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, time
import pytz
import sys
import os

# Setup Django correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")
import django
try:
    if not django.conf.settings.configured:
        django.setup()
except Exception as e:
    pass

# Import after setup
from Ai.ai_service import get_available_slots

class TestDurationSlots(unittest.TestCase):
    
    @patch('Ai.ai_service.Company')
    @patch('Ai.ai_service.OpeningHours')
    @patch('Ai.ai_service.Booking')
    def test_slots_generation(self, MockBooking, MockOpeningHours, MockCompany):
        print("\n--- Testing Duration Logic with Mocks ---")
        
        # 1. Setup Mock Company
        mock_company = MagicMock()
        mock_company.timezone = 'UTC'
        mock_company.concurrent_booking_limit = 1
        
        # Setup the chain: Company.objects.filter(...).first() -> mock_company
        mock_qs = MagicMock()
        mock_qs.first.return_value = mock_company
        MockCompany.objects.filter.return_value = mock_qs
        
        # 2. Setup Mock Opening Hours (Mon 09:00 - 12:00 for simplicity)
        hours = MagicMock()
        hours.start = time(9, 0)
        hours.end = time(12, 0)
        # OpeningHours.objects.filter(...).exists() -> True
        # OpeningHours.objects.filter(...) -> [hours]
        mock_hours_qs = MagicMock()
        mock_hours_qs.exists.return_value = True
        mock_hours_qs.__iter__.return_value = [hours]
        MockOpeningHours.objects.filter.return_value = mock_hours_qs
        
        # 3. Setup Mock Bookings (None)
        mock_bookings_qs = MagicMock()
        mock_bookings_qs.__iter__.return_value = []
        MockBooking.objects.filter.return_value = mock_bookings_qs
        
        # Use a future date to ensure slots aren't filtered out as "past"
        # 2030-01-07 is a Monday
        test_date = "2030-01-07" 
        
        # CASE A: Default Duration (should be 60)
        print("Case A: Duration=None (Default 60)")
        slots = get_available_slots(1, test_date, duration_minutes=None)
        print(f"Slots: {slots}")
        # Expected: 09:00, 10:00, 11:00. (12:00 is end, so 11:00-12:00 is last slot)
        self.assertIn("09:00", slots)
        self.assertIn("10:00", slots)
        self.assertIn("11:00", slots)
        self.assertNotIn("09:30", slots) 
        
        # CASE B: Duration 30
        print("\nCase B: Duration=30")
        slots_30 = get_available_slots(1, test_date, duration_minutes=30)
        print(f"Slots: {slots_30}")
        # Expected: 09:00, 09:30, 10:00, 10:30, 11:00, 11:30
        self.assertIn("09:00", slots_30)
        self.assertIn("09:30", slots_30)
        self.assertIn("10:00", slots_30)
        self.assertIn("11:30", slots_30)
        
        # CASE C: Duration 45
        print("\nCase C: Duration=45")
        slots_45 = get_available_slots(1, test_date, duration_minutes=45)
        print(f"Slots: {slots_45}")
        # Expected: 09:00, 09:45, 10:30, 11:15
        self.assertIn("09:00", slots_45)
        self.assertIn("09:45", slots_45)
        self.assertIn("10:30", slots_45)
        self.assertIn("11:15", slots_45)
        self.assertNotIn("10:00", slots_45)

        print("\nPASS: All mock cases passed.")

if __name__ == '__main__':
    unittest.main()
