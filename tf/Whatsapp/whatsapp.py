from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import requests
from .models import *
from django.conf import settings
from openai import OpenAI
from Chat.consumers import broadcast_message

# Initialize OpenAI client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.AI_TOKEN,
)


def generate_ai_response(user_message):
    """Generate AI response using OpenRouter (Gemini model)."""
    try:
        completion = client.chat.completions.create(
            model="google/gemini-2.5-flash-lite-preview-09-2025",
            messages=[
                {"role": "system", "content": "You are a helpful WhatsApp assistant."},
                {"role": "user", "content": user_message},
            ],
        )
        return completion.choices[0].message.content or "Sorry, I couldn't generate a response."
    except Exception as e:
        print("⚠️ Error generating AI response:", e)
        return "Sorry, something went wrong while generating a reply."


def send_whatsapp_message(profile: WhatsAppProfile, to, message):
    """Send outgoing message via WhatsApp Business API."""
    url = f"https://graph.facebook.com/v17.0/{profile.number_id}/messages"
    headers = {
        "Authorization": f"Bearer {profile.access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        res_data = response.json()

        # ✅ Link outgoing message to client
        client_obj, _ = WhatsAppClient.objects.get_or_create(number=to)
        Outgoing.objects.create(
            sender=profile,
            client=client_obj,
            text=message,
            message_id=res_data.get("messages", [{}])[0].get("id"),
        )

        # ✅ Broadcast message to WebSocket (only once)
        broadcast_message(profile, client_obj, message, "whatsapp", "bot")

        print("✅ WhatsApp message sent successfully!")
        return res_data

    except Exception as e:
        print("❌ Error sending WhatsApp message:", e)
        client_obj = WhatsAppClient.objects.filter(number=to).first()
        Outgoing.objects.create(sender=profile, client=client_obj, text=message)
        return {"error": str(e)}


@csrf_exempt
def whatsapp_webhook(request):
    """Main webhook endpoint for incoming WhatsApp messages."""
    if request.method == "GET":
        # ✅ Verification (Meta challenge)
        verify_token = "whatsapp"
        hub_verify_token = request.GET.get("hub.verify_token")
        hub_challenge = request.GET.get("hub.challenge")
        if hub_verify_token == verify_token:
            return HttpResponse(hub_challenge)
        return HttpResponse("Invalid verification token", status=403)

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            entry = data.get("entry", [])[0].get("changes", [])[0].get("value", {})
            phone_number_id = entry["metadata"]["phone_number_id"]

            # ✅ Get active profile
            profile = WhatsAppProfile.objects.filter(number_id=phone_number_id, bot_active=True).first()
            if not profile:
                print(f"❌ No active WhatsAppProfile found for number_id {phone_number_id}")
                return JsonResponse({"status": "no_profile"})

            # ✅ Process incoming messages
            if "messages" in entry:
                msg = entry["messages"][0]
                from_number = msg["from"]
                msg_body = msg.get("text", {}).get("body", "")

                # ✅ Get or create client
                client_obj, created = WhatsAppClient.objects.get_or_create(number=from_number)
                if created:
                    print(f"🔹 New client created: {from_number}")

                print(f"\n📩 Incoming number: {from_number}")
                print(f"💬 Message: {msg_body}")

                # ✅ Store incoming message
                Incoming.objects.create(receiver=profile, client=client_obj, text=msg_body)

                # ✅ Broadcast message (mark as client sender)
                broadcast_message(profile, client_obj, msg_body, "whatsapp", "client")

                # ✅ Generate AI reply
                ai_reply = generate_ai_response(msg_body)
                print(f"🤖 Reply: {ai_reply}")

                # ✅ Send reply
                send_whatsapp_message(profile, from_number, ai_reply)

        except Exception as e:
            print("❌ Error processing webhook:", e)

        return JsonResponse({"status": "received"})
