# from django.http import HttpResponse, JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# import json
# import requests
# from .models import *
# from django.conf import settings
# from openai import OpenAI
# from django.contrib.auth import get_user_model
# from Chat.consumers import broadcast_message

# User = get_user_model()

# # Initialize OpenAI client
# client = OpenAI(
#     base_url="https://openrouter.ai/api/v1",
#     api_key=settings.AI_TOKEN,
# )


# def generate_ai_response(user_message):
#     """Generate AI response using OpenRouter (Gemini)."""
#     try:
#         completion = client.chat.completions.create(
#             model="google/gemini-2.5-flash-lite-preview-09-2025",
#             messages=[
#                 {"role": "system", "content": "You are a friendly Facebook Page assistant."},
#                 {"role": "user", "content": user_message},
#             ],
#         )
#         return completion.choices[0].message.content or "Sorry, I couldn't generate a response."
#     except Exception as e:
#         print("⚠️ AI Error:", e)
#         return "Sorry, something went wrong while generating a reply."


# def send_facebook_message(profile, recipient_id, message_text):
#     """Send outgoing message via Facebook Page."""
#     url = "https://graph.facebook.com/v19.0/me/messages"
#     headers = {"Content-Type": "application/json"}
#     data = {
#         "recipient": {"id": recipient_id},
#         "message": {"text": message_text}
#     }
#     params = {"access_token": profile.page_access_token}

#     try:
#         response = requests.post(url, headers=headers, params=params, json=data)
#         response.raise_for_status()
#         res_data = response.json()

#         client_obj, _ = FacebookClient.objects.get_or_create(user_id=recipient_id)
#         Outgoing.objects.create(
#             sender=profile,
#             client=client_obj,
#             text=message_text,
#             message_id=res_data.get("message_id"),
#         )

#         # ✅ Broadcast sent message to WebSocket
#         broadcast_message(profile, client_obj, message_text, "facebook", "bot")

#         print(f"✅ Sent message to {recipient_id}")
#         return res_data

#     except Exception as e:
#         print(f"❌ Error sending Facebook message: {e}")
#         client_obj = FacebookClient.objects.filter(user_id=recipient_id).first()
#         Outgoing.objects.create(sender=profile, client=client_obj, text=message_text)
#         return {"error": str(e)}


# @csrf_exempt
# def facebook_webhook(request):
#     """Handle Facebook webhook events (messages + verification)."""
#     if request.method == "GET":
#         verify_token = "facebook"
#         mode = request.GET.get("hub.mode")
#         token = request.GET.get("hub.verify_token")
#         challenge = request.GET.get("hub.challenge")

#         if mode == "subscribe" and token == verify_token:
#             print("✅ Facebook Webhook verified!")
#             return HttpResponse(challenge)
#         return HttpResponse("Verification failed", status=403)

#     elif request.method == "POST":
#         try:
#             data = json.loads(request.body.decode("utf-8"))
#             for entry in data.get("entry", []):
#                 page_id = entry.get("id")

#                 # ✅ Get the page profile
#                 profile = FacebookProfile.objects.filter(page_id=page_id, bot_active=True).first()
#                 if not profile:
#                     default_user, _ = User.objects.get_or_create(username="auto_created")
#                     profile = FacebookProfile.objects.create(
#                         user=default_user,
#                         page_id=page_id,
#                         page_access_token="TEMP_MISSING_TOKEN",
#                         bot_active=False
#                     )
#                     print(f"⚠️ Auto-created inactive profile for Page ID: {page_id}")

#                 # ✅ Iterate over each messaging event
#                 for messaging_event in entry.get("messaging", []):
#                     sender_id = messaging_event.get("sender", {}).get("id")
#                     recipient_id = messaging_event.get("recipient", {}).get("id")

#                     message = messaging_event.get("message")
#                     if not message or message.get("is_echo"):
#                         continue  # skip echoes

#                     text = message.get("text", "")
#                     print(f"\n📩 From: {sender_id}")
#                     print(f"💬 Message: {text}")

#                     # ✅ Get or create client
#                     client_obj, created = FacebookClient.objects.get_or_create(user_id=sender_id)
#                     if created:
#                         print(f"🔹 New Facebook client created: {sender_id}")

#                     # ✅ Store incoming message
#                     Incoming.objects.create(receiver=profile, client=client_obj, text=text)

#                     # ✅ Broadcast incoming message (mark sender_type='client')
#                     broadcast_message(profile, client_obj, text, "facebook", "client")

#                     # ✅ Generate AI reply
#                     reply_text = generate_ai_response(text)
#                     print(f"🤖 Reply: {reply_text}")

#                     # ✅ Send reply
#                     send_facebook_message(profile, sender_id, reply_text)

#         except Exception as e:
#             print("❌ Error in Facebook webhook:", e)

#         return JsonResponse({"status": "received"})
