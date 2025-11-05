from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import json, requests
from openai import OpenAI
from .models import ChatProfile, ChatClient, ChatRoom, ChatMessage
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
User = get_user_model()

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

        # Broadcast
        broadcast_message(profile, client_obj, message_text, 'outgoing',room.id)
        return res_data

    except Exception as e:
        print(f"❌ Error sending message: {e}")
        room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)
        ChatMessage.objects.create(room=room, type="outgoing", text=message_text)
        return {"error": str(e)}


def broadcast_message(profile, client_obj, message_text, message_type, room_id=None):
    """
    Webhook থেকে WebSocket এ message broadcast করে
    
    Args:
        profile: ChatProfile object
        client_obj: ChatClient object
        message_text: Message content
        message_type: 'incoming' or 'outgoing'
        room_id: Optional room ID
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"chat_{profile.platform}_{profile.profile_id}"

        from datetime import datetime
        
        # Group এ message পাঠাই
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'chat_message',  # Consumer এর method name
                'platform': profile.platform,
                'client_id': client_obj.client_id,
                'message': message_text,
                'message_type': message_type,
                'timestamp': datetime.now().isoformat(),
                'room_id': room_id
            }
        )
        print(f"✅ Broadcast Success: {group_name}")
        
    except Exception as e:
        print(f"❌ Broadcast Error: {e}")

@csrf_exempt
def unified_webhook(request, platform):
    """Generic webhook for WhatsApp, Facebook, Instagram"""
    if request.method == "GET":
        # Verification
        verify_token = platform
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if token == verify_token:
            return HttpResponse(challenge)
        return HttpResponse("Invalid verification token", status=403)

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))

            # ---- WhatsApp ----
            if platform == "whatsapp":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})
                changes = entry[0].get("changes", [])
                if not changes:
                    return JsonResponse({"status": "no_changes"})
                value = changes[0].get("value", {})
                profile_id = value.get("metadata", {}).get("phone_number_id")
                profile = ChatProfile.objects.filter(platform="whatsapp", profile_id=profile_id, bot_active=True).first()
                if not profile:
                    return JsonResponse({"status": "no_profile"})

                messages = value.get("messages", [])
                if not messages:
                    return JsonResponse({"status": "no_messages"})
                msg = messages[0]
                client_id = msg.get("from")
                text = msg.get("text", {}).get("body", "")

            # ---- Facebook ----
            elif platform == "facebook":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})
                entry0 = entry[0]
                profile_id = entry0.get("id")
                profile = ChatProfile.objects.filter(platform="facebook", profile_id=profile_id, bot_active=True).first()
                if not profile:
                    return JsonResponse({"status": "no_profile"})
                messaging = entry0.get("messaging", [])
                if not messaging:
                    return JsonResponse({"status": "no_messaging"})
                msg_event = messaging[0]
                client_id = msg_event.get("sender", {}).get("id")
                text = msg_event.get("message", {}).get("text", "")

            # ---- Instagram ----
            elif platform == "instagram":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})
                entry0 = entry[0]
                profile_id = entry0.get("id")
                profile = ChatProfile.objects.filter(platform="instagram", profile_id=profile_id, bot_active=True).first()
                if not profile:
                    return JsonResponse({"status": "no_profile"})
                changes = entry0.get("changes", [])
                if not changes:
                    return JsonResponse({"status": "no_changes"})
                change = changes[0].get("value", {})
                client_id = change.get("from", {}).get("id")
                text = change.get("message") or change.get("text", "")

            else:
                return JsonResponse({"error": "Unknown platform"})

            # --- Unified Chat handling ---
            if not client_id or not text:
                return JsonResponse({"status": "no_client_or_text"})

            client_obj, _ = ChatClient.objects.get_or_create(platform=platform, client_id=client_id)
            room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)
            
            # Incoming message save করো
            ChatMessage.objects.create(room=room, type="incoming", text=text)

            # 🔥 WebSocket এ broadcast করো (Real-time update!)
            broadcast_message(profile, client_obj, text, "incoming",room.id)

            # AI reply generate করো
            reply_text = generate_ai_response(text, platform)
            
            # Reply পাঠাও
            if profile.bot_active and room.bot_active:
                send_message(profile, client_obj, reply_text)
            

        except Exception as e:
            print(f"❌ Webhook Error ({platform}):", e)

        return JsonResponse({"status": "received"})