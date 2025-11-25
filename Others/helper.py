import json
from django.http import JsonResponse
from Socials.models import *
from Socials.webhook import *
import json
import re
import pytz
from datetime import timedelta,datetime
from Socials.helper import send_message

def format_whatsapp_number(number):


    # Remove all non-digit characters
    digits = re.sub(r"\D", "", str(number))

    if digits.startswith("00"):
        # Remove international 00 prefix
        digits = digits[2:]

    if digits.startswith("+"):
        digits = digits[1:]

    return digits


def send_via_webhook_style(client_number, message_text):
    # Ensure the client exists
    client_obj, _ = ChatClient.objects.get_or_create(platform="whatsapp", client_id=client_number)
    
    # Get active WhatsApp profile
    profile = ChatProfile.objects.filter(platform="whatsapp", bot_active=True).first()
    if not profile:
        return {"error": "No active WhatsApp profile"}
    
    # Use the same send_message function your webhook uses
    print('☘️ Send successfuly')
    return send_message(profile, client_obj, message_text)


def parse_timezone_offset(tz_string):
    """Convert timezone string like '+6' to pytz FixedOffset"""
    try:
        offset_hours = float(tz_string)
        offset_minutes = int(offset_hours * 60)
        return pytz.FixedOffset(offset_minutes)
    except (ValueError, TypeError):
        return pytz.UTC

def get_reminder_time_utc(start_time_utc, reminder_hours_before, tz_offset):
    """
    Calculate reminder time in UTC
    start_time_utc: Already in UTC from DB
    """
    user_tz = parse_timezone_offset(tz_offset)
    
    # Convert to user local time
    start_local = start_time_utc.astimezone(user_tz)
    
    # Calculate reminder time in local timezone
    reminder_local = start_local - timedelta(hours=reminder_hours_before)
    
    # Convert to UTC for Celery
    reminder_utc = reminder_local.astimezone(pytz.UTC)
    
    # Debug logging
    print(f"🕐 Start time (UTC): {start_time_utc}")
    print(f"🌍 Start time (Local): {start_local}")
    print(f"⏰ Reminder time (Local): {reminder_local}")
    print(f"🌐 Reminder time (UTC): {reminder_utc}")
    print(f"⏱️  Current time (UTC): {timezone.now()}")
    
    return reminder_utc
