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
            name = "Unknown"
            if platform == "whatsapp":
                entry = data.get("entry", [])
                if not entry:
                    return JsonResponse({"status": "no_entry"})
                changes = entry[0].get("changes", [])
                if not changes:
                    return JsonResponse({"status": "no_changes"})

                value = changes[0].get("value", {})
                profile_id = value.get("metadata", {}).get("phone_number_id")
                # {'object': 'whatsapp_business_account', 'entry': [{'id': '2409871142748879', 'changes': [{'value': {'messaging_product': 'whatsapp', 'metadata': {'display_phone_number': '15551379120', 'phone_number_id': '860175507179810'}, 'contacts': [{'profile': {'name': 'Hasan Mehedi'}, 'wa_id': '8801401541283'}], 'messages': [{'from': '8801401541283', 'id': 'wamid.HBgNODgwMTQwMTU0MTI4MxUCABIYFjNFQjBBMUU4QUYyRDdCNDY4QzhGOTAA', 'timestamp': '1765929323', 'text': {'body': 'hy'}, 'type': 'text'}]}, 'field': 'messages'}]}]}
                contract = value.get("contacts", [])
                name = contract[0].get("profile", {}).get("name")
              
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
                print(f"📘 [Facebook] Webhook received")
                entry = data.get("entry", [])
                if not entry:
                    print(f"❌ [Facebook] No entry in webhook data")
                    return JsonResponse({"status": "no_entry"})

                entry0 = entry[0]
                profile_id = entry0.get("id")
                print(f"📘 [Facebook] Profile ID: {profile_id}")

                profile = ChatProfile.objects.filter(
                    platform="facebook",
                    profile_id=profile_id,
                    bot_active=True
                ).first()
                if not profile:
                    print(f"❌ [Facebook] No active profile found for {profile_id}")
                    return JsonResponse({"status": "no_profile"})
                
                print(f"✅ [Facebook] Profile found: {profile.name or profile.profile_id}, bot_active={profile.bot_active}")

                messaging = entry0.get("messaging", [])
                if not messaging:
                    print(f"❌ [Facebook] No messaging array in webhook")
                    return JsonResponse({"status": "no_messaging"})

                msg_event = messaging[0]
                client_id = msg_event.get("sender", {}).get("id")
                text = msg_event.get("message", {}).get("text", "")
                print(f"📘 [Facebook] Message from {client_id}: {text}")

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
                client_id=client_id,
                defaults={
                    "name": name
                }
            )
            room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)

            # CRITICAL FIX: Check for stuck state BEFORE updating the timestamp
            # If is_waiting_reply is True but it's been a long time since the last message,
            # it means the previous task failed or died. We must reset it.
            if room.is_waiting_reply and room.last_incoming_time:
                time_waiting = (timezone.now() - room.last_incoming_time).total_seconds()
                if time_waiting > 30:  # If waiting for more than 30 seconds, it's definitely stuck
                    print(f"⚠️ [{platform}] Room {room.id} stuck waiting for {time_waiting}s, forcing reset of is_waiting_reply")
                    room.is_waiting_reply = False
                    room.save(update_fields=["is_waiting_reply"])

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

            # (Stuck check removed from here as it was ineffective)

            # If already waiting, the existing task will see the new last_incoming_time
            # and reschedule itself. We just need to ensure a task is scheduled.
            if profile.bot_active and room.bot_active:
                if not room.is_waiting_reply:
                    print(f"🤖 [{platform}] Bot reply activated for room {room.id}")
                    room.is_waiting_reply = True
                    room.save(update_fields=["is_waiting_reply"])
                    wait_and_reply.delay(room.id, delay=5)
                    print(f"⏰ [{platform}] wait_and_reply task scheduled for room {room.id}")
                else:
                    print(f"⏳ [{platform}] Already waiting for reply on room {room.id}, existing task will reschedule itself")
                
                # Debug logging for Facebook
                if platform == "facebook":
                    print(f"🔍 [Facebook Debug] Room {room.id} state:")
                    print(f"    - is_waiting_reply: {room.is_waiting_reply}")
                    print(f"    - bot_active: {room.bot_active}")
                    print(f"    - profile.bot_active: {profile.bot_active}")
                    print(f"    - last_incoming_time: {room.last_incoming_time}")
            else:
                print(f"⏭️ [{platform}] Bot reply disabled - profile.bot_active={profile.bot_active}, room.bot_active={room.bot_active}")
            

        except Exception as e:
            print(f"❌ Webhook Error ({platform}):", e)

        return JsonResponse({"status": "received"})
