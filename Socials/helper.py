from django.utils import timezone
from .models import *
from .consumers import broadcast_message
import requests
from Ai.ai_service import get_ai_response
from django.core.cache import cache
from django_redis import get_redis_connection
from Others.models import Alert
from Accounts.models import Company
from Finance.models import Subscriptions, DailyUsage
from .models import ChatProfile, ChatRoom, ChatMessage, ChatClient

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
            url = f"https://graph.instagram.com/v22.0/me/messages"
            params = {"access_token": profile.access_token}
            payload = {
                "recipient": {"id": client_obj.client_id},
                "message": {"text": message_text}
            }
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
    """
    Simplified token count check. Direct database operation without Redis cache.
    """
    try:
        # 1. Fetch active subscription
        subscription = Subscriptions.objects.filter(
            company__id=company_id, 
            active=True,
            end__gt=timezone.now()
        ).first()

        if not subscription:
            print(f"❌ [Debug] No active or unexpired subscription found for Company {company_id}")
            # Check if any subscription exists at all for debugging
            any_sub = Subscriptions.objects.filter(company__id=company_id).last()
            if any_sub:
                print(f"   - Last Sub ID: {any_sub.id}, Active: {any_sub.active}, End: {any_sub.end}, Now: {timezone.now()}")
            return False

        # 2. Check if tokens are exhausted
        if subscription.token_count < count:
            # Logic: Deactivate Chat Profiles + Send Alert
            try:
                company = Company.objects.get(id=company_id)
                
                # Deactivate Chat Profiles
                ChatProfile.objects.filter(user=company.user).update(bot_active=False)
                
                # Send Real-time Alert
                from .consumers import send_alert
                send_alert(
                    company, 
                    "Token Limit Reached", 
                    "Your AI tokens have been exhausted. Chat profiles are now inactive.", 
                    type="error"
                )
                print(f"⚠️ Tokens exhausted for Company {company_id}. Profiles deactivated.")
            except Exception as e:
                print(f"Error handling token exhaustion: {e}")
            
            return False

        # 3. Deduct tokens and save
        subscription.token_count -= count
        subscription.save(update_fields=['token_count'])
        
        return True

    except Exception as e:
        print(f"❌ Error in check_token_count: {e}")
        return False

def check_msg_limit(company_id):
    """
    Check if the company has reached its daily AI response limit.
    If limit reached, deactivate chat profiles and send alert.
    """
    try:
        # 1. Fetch active subscription and plan
        subscription = Subscriptions.objects.filter(
            company__id=company_id, 
            active=True,
            end__gt=timezone.now()
        ).select_related('plan').first()

        if not subscription or not subscription.plan:
            print(f"⚠️ No active subscription or plan found for Company {company_id}")
            return False

        plan = subscription.plan
        msg_limit = plan.msg_limit

        # 2. Get or create daily usage record
        today = timezone.now().date()
        usage, created = DailyUsage.objects.get_or_create(
            company_id=company_id,
            date=today,
            defaults={'msg_count': 0}
        )

        # 3. Check if limit is already reached
        if usage.msg_count >= msg_limit:
            # Action: Deactivate & Alert (if not already done, but we'll do it safely)
            deactivate_and_alert_limit(company_id, "Daily Message Limit Reached")
            return False

        # 4. Increment count
        usage.msg_count += 1
        usage.save(update_fields=['msg_count'])

        # 5. Check if THIS message hits the limit
        if usage.msg_count >= msg_limit:
            deactivate_and_alert_limit(company_id, "Daily Message Limit Reached")

        return True

    except Exception as e:
        print(f"❌ Error in check_msg_limit: {e}")
        return False

def deactivate_and_alert_limit(company_id, reason):
    """
    Deactivates bot for all chat profiles and sends a real-time alert.
    """
    try:
        company = Company.objects.get(id=company_id)
        
        # Deactivate Chat Profiles
        updated_count = ChatProfile.objects.filter(user=company.user).update(bot_active=False)
        
        if updated_count > 0:
            # Send alert only if we actually deactivated something or as a reminder
            from .consumers import send_alert
            send_alert(
                company, 
                reason, 
                f"Your AI response limit ({reason}) has been reached. Chat profiles are now inactive.", 
                type="error"
            )
            print(f"⚠️ Limit reached for Company {company_id}. Profiles deactivated: {updated_count}")
    except Exception as e:
        print(f"Error in deactivate_and_alert_limit: {e}")
