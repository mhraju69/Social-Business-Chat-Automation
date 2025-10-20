from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import requests
from .models import FacebookProfile, Incoming, Outgoing  # use same Incoming/Outgoing models if you like
from django.conf import settings
from openai import OpenAI
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import requests
from .models import FacebookProfile, Incoming, Outgoing
from openai import OpenAI
from django.contrib.auth import get_user_model

User = get_user_model()

# =========================
# 🔹 OpenAI Client
# =========================
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key= settings.AI_TOKEN,
)

def generate_ai_response(user_message):
    try:
        completion = client.chat.completions.create(
            model="google/gemini-2.5-flash-lite-preview-09-2025",
            messages=[
                {"role": "system", "content": "You are a friendly Facebook Page assistant."},
                {"role": "user", "content": user_message},
            ],
        )
        return completion.choices[0].message.content or "Sorry, I couldn't generate a response."
    except Exception as e:
        print("⚠️ AI Error:", e)
        return "Sorry, something went wrong while generating a reply."


# =========================
# 🔹 Send Message via Graph API
# =========================
def send_facebook_message(profile, recipient_id, message_text):
    url = f"https://graph.facebook.com/v19.0/me/messages"
    headers = {"Content-Type": "application/json"}
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    params = {"access_token": profile.page_access_token}

    try:
        response = requests.post(url, headers=headers, params=params, json=data)
        response.raise_for_status()
        res_data = response.json()

        Outgoing.objects.create(
            sender=profile,
            to_user_id=recipient_id,
            text=message_text,
            message_id=res_data.get("message_id"),
        )
        print(f"✅ Sent message to {recipient_id}")
        return res_data

    except Exception as e:
        print(f"❌ Error sending Facebook message: {e}")
        Outgoing.objects.create(
            sender=profile,
            to_user_id=recipient_id,
            text=message_text
        )
        return {"error": str(e)}


# =========================
# 🔹 Facebook Webhook
# =========================
@csrf_exempt
def facebook_webhook(request):
    if request.method == "GET":
        # ✅ Verification
        verify_token = "facebook"
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if mode == "subscribe" and token == verify_token:
            print("✅ Facebook Webhook verified!")
            return HttpResponse(challenge)
        else:
            return HttpResponse("Verification failed", status=403)

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))

            for entry in data.get("entry", []):
                page_id = entry.get("id")
                profile = FacebookProfile.objects.filter(page_id=page_id, bot_active=True).first()

                # If no page profile exists → auto-create with default user
                if not profile:
                    default_user, _ = User.objects.get_or_create(username="auto_created")
                    profile = FacebookProfile.objects.create(
                        user=default_user,
                        page_id=page_id,
                        page_access_token="TEMP_MISSING_TOKEN",
                        bot_active=False,
                    )
                    print(f"⚠️ Auto-created inactive profile for Page ID: {page_id}")

                for messaging_event in entry.get("messaging", []):
                    sender_id = messaging_event.get("sender", {}).get("id")
                    recipient_id = messaging_event.get("recipient", {}).get("id")

                    # Skip echo messages to prevent reply loops
                    message = messaging_event.get("message")
                    if not message or message.get("is_echo"):
                        continue

                    text = message.get("text", "")
                    print(f"\n📩 From: {sender_id}")
                    print(f"💬 Message: {text}")

                    # Save incoming message
                    Incoming.objects.create(
                        receiver=profile,
                        from_user_id=sender_id,
                        text=text
                    )

                    # Generate AI reply
                    reply_text = generate_ai_response(text)
                    print(f"🤖 Reply: {reply_text}\n")

                    # Send reply
                    send_facebook_message(profile, sender_id, reply_text)

        except Exception as e:
            print("❌ Error in Facebook webhook:", e)

        return JsonResponse({"status": "received"})
