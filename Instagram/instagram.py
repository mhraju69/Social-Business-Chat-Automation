# from django.http import HttpResponse, JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# import json
# import requests
# from django.conf import settings
# from openai import OpenAI
# from django.contrib.auth import get_user_model
# from .models import *

# User = get_user_model()

# # =========================
# # 🔹 OpenAI Client
# # =========================
# client = OpenAI(
#     base_url="https://openrouter.ai/api/v1",
#     api_key=settings.AI_TOKEN,
# )

# def generate_ai_response(user_message):
#     """Generate AI response using OpenAI"""
#     try:
#         completion = client.chat.completions.create(
#             model="google/gemini-2.5-flash-lite-preview-09-2025",
#             messages=[
#                 {"role": "system", "content": "You are a friendly Instagram Page assistant."},
#                 {"role": "user", "content": user_message},
#             ],
#         )
#         return completion.choices[0].message.content or "Sorry, I couldn't generate a response."
#     except Exception as e:
#         print("⚠️ AI Error:", e)
#         return "Sorry, something went wrong while generating a reply."


# # =========================
# # 🔹 Send Instagram Message via Graph API
# # =========================
# def send_instagram_message(profile, recipient_id, message_text):
#     """
#     Sends a message via Instagram Graph API.
#     Uses the connected page's access token from InstagramProfile.
#     """
#     url = f"https://graph.facebook.com/v20.0/{profile.instagram_id}/messages"
#     headers = {"Content-Type": "application/json"}
#     data = {
#         "recipient": {"id": recipient_id},
#         "message": {"text": message_text},
#     }
#     params = {"access_token": profile.access_token}

#     try:
#         response = requests.post(url, headers=headers, params=params, json=data)
#         response.raise_for_status()
#         res_data = response.json()

#         Outgoing.objects.create(
#             sender=profile,
#             to_user_id=recipient_id,
#             text=message_text,
#             message_id=res_data.get("message_id"),
#         )
#         print(f"✅ Sent Instagram message to {recipient_id}")
#         return res_data

#     except Exception as e:
#         print(f"❌ Error sending Instagram message: {e}")
#         Outgoing.objects.create(
#             sender=profile,
#             to_user_id=recipient_id,
#             text=message_text
#         )
#         return {"error": str(e)}


# # =========================
# # 🔹 Instagram Webhook
# # =========================
# @csrf_exempt
# def instagram_webhook(request):
#     """
#     Handles Instagram webhook verification (GET)
#     and message events (POST)
#     """
#     if request.method == "GET":
#         # ✅ Verification (same as Facebook)
#         verify_token = "instagram"
#         mode = request.GET.get("hub.mode")
#         token = request.GET.get("hub.verify_token")
#         challenge = request.GET.get("hub.challenge")

#         if mode == "subscribe" and token == verify_token:
#             print("✅ Instagram Webhook verified!")
#             return HttpResponse(challenge)
#         else:
#             return HttpResponse("Verification failed", status=403)

#     elif request.method == "POST":
#         try:
#             data = json.loads(request.body.decode("utf-8"))
#             print("\n📩 Incoming Instagram Webhook:", json.dumps(data, indent=2))

#             for entry in data.get("entry", []):
#                 ig_business_id = entry.get("id")
#                 profile = InstagramProfile.objects.filter(instagram_id=ig_business_id, bot_active=True).first()

#                 # Auto-create profile if not found (optional fallback)
#                 if not profile:
#                     default_user, _ = User.objects.get_or_create(username="auto_created")
#                     profile = InstagramProfile.objects.create(
#                         user=default_user,
#                         instagram_id=ig_business_id,
#                         access_token="TEMP_MISSING_TOKEN",
#                         bot_active=False,
#                     )
#                     print(f"⚠️ Auto-created inactive Instagram profile for ID: {ig_business_id}")

#                 # Parse Instagram message events
#                 for change in entry.get("changes", []):
#                     value = change.get("value", {})
#                     if value.get("field") != "messages":
#                         continue

#                     message_data = value.get("messages", [value])[0]  # sometimes list, sometimes dict
#                     sender_id = message_data.get("from", {}).get("id")
#                     text = message_data.get("message") or message_data.get("text", "")

#                     if not sender_id or not text:
#                         continue

#                     print(f"💬 From IG User: {sender_id}")
#                     print(f"💭 Message: {text}")

#                     # Save incoming message
#                     Incoming.objects.create(
#                         receiver=profile,
#                         from_user_id=sender_id,
#                         text=text,
#                     )

#                     # Generate AI reply
#                     reply_text = generate_ai_response(text)
#                     print(f"🤖 Reply: {reply_text}")

#                     # Send reply
#                     send_instagram_message(profile, sender_id, reply_text)

#         except Exception as e:
#             print("❌ Error in Instagram webhook:", e)

#         return JsonResponse({"status": "received"})
