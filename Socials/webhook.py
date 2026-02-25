from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import json, requests
from Others.task import wait_and_reply
from .models import ChatProfile, ChatClient, ChatRoom, ChatMessage
from .consumers import broadcast_message, send_alert
from .helper import check_token_count
User = get_user_model()

@csrf_exempt
def unified_webhook(request, platform):
    """Generic webhook for WhatsApp, Facebook, Instagram"""
    
    # 🕵️ EXTREME DEBUG: Log every single request hitting this endpoint
    print(f"--- 📥 New Webhook Request: {platform} ---")
    print(f"Path: {request.path}")
    print(f"Method: {request.method}")

    if request.method == "GET":
        # ১. যদি এটি Instagram OAuth এর কলব্যাক হয় (এতে 'code' থাকবে)
        code = request.GET.get("code")
        if platform == "instagram" and code:
            from .views import instagram_callback
            return instagram_callback(request)

        # ২. স্ট্যান্ডার্ড Webhook ভেরিফিকেশন
        verify_token = platform
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        print(f"Verification Check - Token: {token}, Challenge: {challenge}")
        
        if token == verify_token:
            return HttpResponse(challenge)
        return HttpResponse("Invalid verification token", status=403)

    elif request.method == "POST":
        raw_body = ""
        try:
            raw_body = request.body.decode("utf-8")
            print(f"📦 Raw Body Length: {len(raw_body)}")
            # print(f"� Raw Body: {raw_body}") # Optional: Uncomment if needed
            
            data = json.loads(raw_body)
            print(f"�🚀 [{platform}] Webhook JSON: {json.dumps(data)}")

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

                # Token count check
                if not check_token_count(profile.user.company.id, 1):
                    return JsonResponse({"status": "error", "message": "Token limit reached."}, status=400)

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

                # Token count check
                if not check_token_count(profile.user.company.id, 1):
                    print(f"❌ [Facebook] Token count check failed for Company {profile.user.company.id}")
                    return JsonResponse({"status": "error", "message": "Token limit reached."}, status=400)

                # Fetch user name from Facebook Graph API
                try:
                    user_url = f"https://graph.facebook.com/{client_id}?fields=first_name,last_name,name&access_token={profile.access_token}"
                    user_res = requests.get(user_url)
                    if user_res.status_code == 200:
                        user_data = user_res.json()
                        name = user_data.get("name") or f"{user_data.get('first_name','')} {user_data.get('last_name','')}"
                        print(f"✅ [Facebook] Fetched user name: {name}")
                except Exception as e:
                    print(f"❌ [Facebook] Error fetching user profile: {e}")

            elif platform == "instagram":
                entry = data.get("entry", [])
                if not entry:
                    print(f"⚠️ [Instagram] Error: 'entry' is missing in webhook data")
                    return JsonResponse({"status": "no_entry"})

                entry0 = entry[0]
                profile_id = str(entry0.get("id"))
                print(f"📥 [Instagram] Raw Header - Entry ID: {profile_id}")
                
                # Identify the profile — check ALL profiles (bot_active or not)
                profile = ChatProfile.objects.filter(
                    platform="instagram",
                    profile_id=profile_id,
                ).first()
                
                if profile:
                    if not profile.bot_active:
                        print(f"⚠️ [Instagram] Profile found but bot_active=False: {profile.name}. Skipping.")
                        return JsonResponse({"status": "bot_inactive"})
                    print(f"✅ [Instagram] Profile Match: {profile.name}")
                if not profile:
                    print(f"🔍 [Instagram] Entry ID {profile_id} not in DB. Running auto-resolution...")
                    
                    potential_profiles = ChatProfile.objects.filter(platform="instagram", bot_active=True)
                    resolved = False
                    
                    for potential in potential_profiles:
                        print(f"🕵️ Checking: {potential.name} (DB ID: {potential.profile_id})")
                        try:
                            # Only request id and username — ig_id field is NOT supported on all accounts
                            res = requests.get(
                                "https://graph.instagram.com/me",
                                params={"fields": "id,username", "access_token": potential.access_token},
                                timeout=5
                            ).json()
                            
                            if "error" in res:
                                err_code = res["error"].get("code", 0)
                                if err_code == 190:  # Invalid/Expired token
                                    print(f"  ❌ Invalid token for {potential.name}: {res['error'].get('message')}")
                                    continue  # This token is broken, skip it
                                # Other errors (e.g. field not found) — still try to continue with partial data
                            
                            fetched_ig_id = str(res.get("id", ""))
                            fetched_uname = res.get("username", "")
                            
                            print(f"  👉 {potential.name}: user_id={fetched_ig_id}, username={fetched_uname}")
                            
                            # Before updating, check if any other profile already owns this ID
                            already_exists = ChatProfile.objects.filter(
                                platform="instagram", profile_id=profile_id
                            ).exclude(pk=potential.pk).exists()
                            
                            if already_exists:
                                print(f"  ⚠️ ID {profile_id} already belongs to another profile. Skipping update for {potential.name}.")
                                # The real owner is already in DB — it just wasn't found (maybe bot_active=False)
                                real_owner = ChatProfile.objects.filter(platform="instagram", profile_id=profile_id).first()
                                if real_owner:
                                    profile = real_owner
                                    resolved = True
                                    print(f"✅ [Instagram] Found real owner: {real_owner.name} (bot_active={real_owner.bot_active})")
                                break
                            
                            # Match if returned ID equals the incoming profile_id
                            if profile_id == fetched_ig_id:
                                old_id = potential.profile_id
                                potential.profile_id = profile_id
                                potential.save(update_fields=["profile_id"])
                                profile = potential
                                resolved = True
                                print(f"✨ [Instagram] Auto-resolved by ID! {potential.name}: {old_id} -> {profile_id}")
                                break
                            
                            # Fallback: Match by username == profile name stored in DB
                            if fetched_uname and fetched_uname == potential.name:
                                print(f"💡 [Instagram] Username match ({fetched_uname})! Updating ID...")
                                old_id = potential.profile_id
                                potential.profile_id = profile_id
                                potential.save(update_fields=["profile_id"])
                                profile = potential
                                resolved = True
                                print(f"✨ [Instagram] Auto-resolved by username! {potential.name}: {old_id} -> {profile_id}")
                                break

                        except Exception as ex:
                            print(f"  ⚠️ Error checking {potential.name}: {ex}")
                    
                    if not resolved:
                        print(f"❌ [Instagram] Could not resolve {profile_id}. Account may not be subscribed to webhooks. Please re-connect this account.")
                        return JsonResponse({"status": "no_profile"})

                # 1. Parse message data
                messaging = entry0.get("messaging", [])
                if messaging:
                    msg_event = messaging[0]
                    message_obj = msg_event.get("message", {})
                    client_id = str(msg_event.get("sender", {}).get("id"))
                    text = message_obj.get("text", "")
                    
                    if message_obj.get("is_echo"):
                        print(f"空️ [Instagram] Skipping Echo from {client_id}")
                        return JsonResponse({"status": "echo_skip"})
                else:
                    changes = entry0.get("changes", [])
                    if not changes:
                        print(f"⚠️ [Instagram] No messaging or changes in webhook")
                        return JsonResponse({"status": "no_changes_or_messaging"})
                    change = changes[0].get("value", {})
                    client_id = str(change.get("from", {}).get("id"))
                    text = change.get("message") or change.get("text", "")

                # 2. Final safety check (Bot talking to Bot)
                if client_id == profile_id or ChatProfile.objects.filter(platform=platform, profile_id=client_id).exists():
                    print(f"空️ [Instagram] Skipping internal message ({client_id})")
                    return JsonResponse({"status": "internal_bot_message_skip"})

                if not check_token_count(profile.user.company.id, 1):
                    return JsonResponse({"status": "token_limit"})

                try:
                    user_url = f"https://graph.instagram.com/{client_id}?fields=username&access_token={profile.access_token}"
                    user_res = requests.get(user_url)
                    if user_res.status_code == 200:
                        name = user_res.json().get("username", "Instagram User")
                except Exception as e:
                    print(f"⚠️ Error fetching IG username: {e}")

            else:
                return JsonResponse({"error": "Unknown platform"})


            #---------------------------------------------
            # VALIDATION
            #---------------------------------------------
            if not client_id or not text:
                print(f"⚠️ Validation Failed: client_id={client_id}, text_len={len(text) if text else 0}")
                return JsonResponse({"status": "no_client_or_text"})

            if client_id == profile_id:
                return JsonResponse({"status": "self_message_skip"})


            #---------------------------------------------
            # UNIFIED CHAT HANDLING
            #---------------------------------------------
            client_obj, _ = ChatClient.objects.get_or_create(
                platform=platform,
                client_id=client_id,
                defaults={"name": name}
            )
            
            if name != "Unknown" and client_obj.name != name:
                client_obj.name = name
                client_obj.save(update_fields=["name"])

            room, _ = ChatRoom.objects.get_or_create(profile=profile, client=client_obj)

            if room.is_waiting_reply and room.last_incoming_time:
                time_waiting = (timezone.now() - room.last_incoming_time).total_seconds()
                if time_waiting > 30:
                    room.is_waiting_reply = False
                    room.save(update_fields=["is_waiting_reply"])

            ChatMessage.objects.create(room=room, type="incoming", text=text)
            broadcast_message(profile, client_obj, text, "incoming", room.id)

            room.last_incoming_time = timezone.now()
            room.save(update_fields=["last_incoming_time"])

            if profile.bot_active and room.bot_active:
                if not room.is_waiting_reply:
                    room.is_waiting_reply = True
                    room.save(update_fields=["is_waiting_reply"])
                    wait_and_reply.delay(room.id, delay=0)
            
        except Exception as e:
            import traceback
            print(f"� CRITICAL WEBHOOK ERROR ({platform}):")
            print(traceback.format_exc())
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

        return JsonResponse({"status": "received"})
