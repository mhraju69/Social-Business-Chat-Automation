from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import json, requests
from Others.task import wait_and_reply
from .models import ChatProfile, ChatClient, ChatRoom, ChatMessage
from .consumers import broadcast_message
User = get_user_model()

@csrf_exempt
def unified_webhook(request, platform):
    """Generic webhook for WhatsApp, Facebook, Instagram"""

    if request.method == "GET":
        verify_token = platform
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if token == verify_token:
            return HttpResponse(challenge)
        return HttpResponse("Invalid verification token", status=403)

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))

            #---------------------------------------------
            # PLATFORM SPECIFIC DATA PARSING
            #---------------------------------------------
            
            if platform == "whatsapp":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})
                changes = entry[0].get("changes", [])
                if not changes:
                    return JsonResponse({"status": "no_changes"})

                value = changes[0].get("value", {})
                profile_id = value.get("metadata", {}).get("phone_number_id")

                profile = ChatProfile.objects.filter(
                    platform="whatsapp",
                    profile_id=profile_id,
                    bot_active=True
                ).first()
                if not profile:
                    return JsonResponse({"status": "no_profile"})

                messages = value.get("messages", [])
                if not messages:
                    return JsonResponse({"status": "no_messages"})

                msg = messages[0]
                client_id = msg.get("from")
                text = msg.get("text", {}).get("body", "")

            elif platform == "facebook":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})

                entry0 = entry[0]
                profile_id = entry0.get("id")

                profile = ChatProfile.objects.filter(
                    platform="facebook",
                    profile_id=profile_id,
                    bot_active=True
                ).first()
                if not profile:
                    return JsonResponse({"status": "no_profile"})

                messaging = entry0.get("messaging", [])
                if not messaging:
                    return JsonResponse({"status": "no_messaging"})

                msg_event = messaging[0]
                client_id = msg_event.get("sender", {}).get("id")
                text = msg_event.get("message", {}).get("text", "")

            elif platform == "instagram":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})

                entry0 = entry[0]
                profile_id = entry0.get("id")

                profile = ChatProfile.objects.filter(
                    platform="instagram",
                    profile_id=profile_id,
                    bot_active=True
                ).first()
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


            #---------------------------------------------
            # VALIDATION
            #---------------------------------------------
            if not client_id or not text:
                return JsonResponse({"status": "no_client_or_text"})

            # Self-message হলে skip
            if client_id == profile_id:
                return JsonResponse({"status": "self_message_skip"})


            #---------------------------------------------
            # UNIFIED CHAT HANDLING
            #---------------------------------------------
            client_obj, _ = ChatClient.objects.get_or_create(
                platform=platform,
                client_id=client_id
            )
            room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)

            # Save incoming message
            ChatMessage.objects.create(room=room, type="incoming", text=text)

            # Real-time push
            broadcast_message(profile, client_obj, text, "incoming", room.id)

            # Update last incoming time
            room.last_incoming_time = timezone.now()
            room.save(update_fields=["last_incoming_time"])

            #---------------------------------------------
            # BATCH REPLY SYSTEM ACTIVATION
            #---------------------------------------------

            if profile.bot_active and room.bot_active and not room.is_waiting_reply:
                room.is_waiting_reply = True
                room.save(update_fields=["is_waiting_reply"])
                wait_and_reply.delay(room.id, delay=5)
            

        except Exception as e:
            print(f"❌ Webhook Error ({platform}):", e)

        return JsonResponse({"status": "received"})
