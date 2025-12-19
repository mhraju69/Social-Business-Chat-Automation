from django.utils import timezone
from .models import *
from .consumers import broadcast_message
import requests
from Ai.ai_service import get_ai_response
from django.core.cache import cache
from django_redis import get_redis_connection
from datetime import datetime


def send_message(profile: ChatProfile, client_obj: ChatClient, message_text):
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

def check_token_count(company_id, count):
    redis = get_redis_connection("default")
    cache_key = f"company_token_{company_id}"

    token_count = redis.get(cache_key)
    
    if token_count is None:
        plan = Subscriptions.objects.filter(company__id=company_id).first()

        if not plan or not plan.is_active or plan.end < datetime.now():
            return False

        token_count = plan.token_count
        redis.set(cache_key, token_count)

    with redis.pipeline() as pipe:
        while True:
            try:
                pipe.watch(cache_key)
                current_tokens = int(pipe.get(cache_key))

                if current_tokens < count:
                    pipe.unwatch()
                    return False

                new_token_count = current_tokens - count

                pipe.multi()
                pipe.set(cache_key, new_token_count)
                pipe.execute()
                break
            except Exception:
                continue

    Subscriptions.objects.filter(company__id=company_id).update(
        token_count=new_token_count
    )

    return True
