from django.utils import timezone
from django.conf import settings
from .models import *
from openai import OpenAI
from .consumers import broadcast_message
import requests

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.AI_TOKEN,
)


def generate_ai_response(user_message, platform):

    """AI উত্তর তৈরি করে"""
    try:
        system_text = f"You are a helpful {platform.capitalize()} chat assistant."
        res = client.chat.completions.create(
            model="google/gemini-2.5-flash-lite-preview-09-2025",
            messages=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_message},
            ]
        )
        return res.choices[0].message.content or "Sorry, I couldn't generate a response."
    except Exception as e:
        print("⚠️ AI Error:", e)
        return "Sorry, something went wrong while generating a reply."


def send_message(profile: ChatProfile, client_obj: ChatClient, message_text):
    """Outgoing message handle করে সব প্ল্যাটফর্মের জন্য"""
    try:
        res_data = {}
        if profile.platform == "whatsapp":
            url = f"https://graph.facebook.com/v17.0/{profile.profile_id}/messages"
            headers = {"Authorization": f"Bearer {profile.access_token}", "Content-Type": "application/json"}
            payload = {
                "messaging_product": "whatsapp",
                "to": client_obj.client_id,
                "type": "text",
                "text": {"body": message_text},
            }
            response = requests.post(url, headers=headers, json=payload)
            res_data = response.json()

        elif profile.platform == "facebook":
            url = "https://graph.facebook.com/v19.0/me/messages"
            params = {"access_token": profile.access_token}
            payload = {"recipient": {"id": client_obj.client_id}, "message": {"text": message_text}}
            response = requests.post(url, params=params, json=payload)
            res_data = response.json()

        elif profile.platform == "instagram":
            url = f"https://graph.facebook.com/v20.0/{profile.profile_id}/messages"
            params = {"access_token": profile.access_token}
            payload = {"recipient": {"id": client_obj.client_id}, "message": {"text": message_text}}
            response = requests.post(url, params=params, json=payload)
            res_data = response.json()

        else:
            raise Exception("Unknown platform")

        # Save outgoing message
        room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)
        ChatMessage.objects.create(
            room=room,
            type="outgoing",
            text=message_text,
            message_id=res_data.get("message_id") or res_data.get("messages", [{}])[0].get("id"),
            send_by_bot=True,
        )
        room.last_outgoing_time = timezone.now()
        room.last_message_time = ''
        room.save()

        # Broadcast
        broadcast_message(profile, client_obj, message_text, 'outgoing',room.id)
        return res_data

    except Exception as e:
        print(f"❌ Error sending message: {e}")
        room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)
        ChatMessage.objects.create(room=room, type="outgoing", text=message_text)
        return {"error": str(e)}

