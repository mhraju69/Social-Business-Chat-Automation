import json
from django.http import JsonResponse
from Socials.models import *
from Socials.webhook import *
import json
import re

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
    return send_message(profile, client_obj, message_text)
