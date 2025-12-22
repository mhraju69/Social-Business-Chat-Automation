from django.utils import timezone
from celery import shared_task
from django.core.mail import send_mail
from .models import Booking
import time    
from Socials.models import ChatRoom, ChatMessage
from Socials.helper import *

def get_msg_history(room_id):
    """
    Get last 20 messages for a chat room in OpenAI chat format.
    
    Args:
        room_id: The ChatRoom ID to filter messages
        
    Returns:
        List of dicts in format: [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        Messages are ordered from oldest to newest (chronological order for context)
    """
    # Get last 20 messages for this room, ordered by timestamp (most recent first)
    messages = ChatMessage.objects.filter(
        room_id=room_id
    ).order_by('-timestamp')[:20]
    
    # Convert to list and reverse to get chronological order (oldest first)
    messages_list = list(messages)
    messages_list.reverse()
    
    # Format messages in OpenAI chat format
    formatted_messages = []
    for msg in messages_list:
        # Map message type to role
        # 'incoming' = user message, 'outgoing' = assistant message
        role = "user" if msg.type == "incoming" else "assistant"
        
        formatted_messages.append({
            "role": role,
            "content": msg.text
        })
    
    return formatted_messages
    

@shared_task(ignore_result=True)
def send_booking_reminder(booking_id):
    """Send booking reminder via email/SMS"""
    try:
        booking = Booking.objects.get(id=booking_id)
        
        print(f"📧 Sending reminder for booking #{booking.id}")
        print(f"   Title: {booking.title}")
        print(f"   Client: {booking.client}")
        print(f"   Start: {booking.start_time}")
        
        # Get user timezone
        tz_offset = booking.company.user.timezone or "+6"
        offset_hours = float(tz_offset)
        offset_minutes = int(offset_hours * 60)
        
        import pytz
        user_tz = pytz.FixedOffset(offset_minutes)
        start_local = booking.start_time.astimezone(user_tz)
        
        # Prepare message
        message = (
            f"⏰ Reminder: Your appointment is in 1 hour!\\n\\n"
            f"Title: {booking.title}\\n"
            f"Time: {start_local.strftime('%d %b %Y, %I:%M %p')}\\n"
            f"Location: {booking.location or 'N/A'}\\n"
            f"Event Link: {booking.event_link or 'N/A'}"
        )
        
        # Send SMS if number exists
        if hasattr(booking, 'number') and booking.number:
            from .helper import send_via_webhook_style
            send_via_webhook_style(booking.number, message)
            print(f"✅ SMS sent to {booking.number}")
        
        # Send email
        if booking.client:
            send_mail(
                subject=f"Reminder: {booking.title}",
                message=message,
                from_email='noreply@yourdomain.com',
                recipient_list=[booking.client],
                fail_silently=False,
            )
            print(f"✅ Email sent to {booking.client}")
        
        return f"Reminder sent for booking #{booking_id}"
        
    except Exception as e:
        print(f"❌ Error sending reminder: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

@shared_task(ignore_result=True)
def wait_and_reply(room_id, delay):
    """
    Waits for 'delay' seconds to batch incoming messages for a room,
    then sends AI-generated reply for all unprocessed incoming messages
    that arrived after the last outgoing message.
    
    FIXED: Now reschedules itself if new messages arrive during delay period.
    """
    import time
    print(f"⏰ wait_and_reply task started for room {room_id}, waiting {delay}s...")
    time.sleep(delay)  # Wait for additional messages

    try:
        room = ChatRoom.objects.get(id=room_id)
        print(f"✅ Room found: {room.profile.platform} - {room.client.client_id}")
    except ChatRoom.DoesNotExist:
        print(f"❌ Room {room_id} does not exist")
        return f"Room {room_id} does not exist"

    now = timezone.now()

    # If new message arrived within delay → reschedule task (FIXED)
    if room.last_incoming_time and (now - room.last_incoming_time).total_seconds() < delay:
        print(f"⏭️ [{room.profile.platform}] New incoming detected → rescheduling task for room {room_id}")
        # Don't reset is_waiting_reply, just schedule a new task
        wait_and_reply.delay(room_id, delay=delay)
        return f"New incoming detected → rescheduled for room {room_id}"

    # Fetch all unprocessed incoming messages after last outgoing
    if room.last_outgoing_time:
        incoming_msgs = ChatMessage.objects.filter(
            room=room,
            type="incoming",
            processed=False,
            created_at__gt=room.last_outgoing_time
        )
    else:
        incoming_msgs = ChatMessage.objects.filter(
            room=room,
            type="incoming",
            processed=False
        )

    if not incoming_msgs.exists():
        room.is_waiting_reply = False
        room.save(update_fields=["is_waiting_reply"])
        print(f"⏭️ No unprocessed incoming messages → nothing to reply for room {room_id}")
        return "No unprocessed incoming messages → nothing to reply"

    # Combine all incoming texts
    full_text = "\\n".join(msg.text for msg in incoming_msgs)
    print(f"📝 [{room.profile.platform}] Combined message text ({len(incoming_msgs)} messages): {full_text[:100]}...")

    # Generate AI reply
    print(f"🤖 [{room.profile.platform}] Generating AI response...")
    
    # Get company from room -> profile -> user -> company
    company = room.profile.user.company
    
    reply_data = get_ai_response(
        company_id=company.id, 
        query=full_text, 
        history=get_msg_history(room_id=room.id)
    )
    reply_text = reply_data['content']
    print(f"✅ [{room.profile.platform}] AI response generated: {reply_text[:100]}...")

    # Send reply via existing send_message function
    print(f"📤 [{room.profile.platform}] Sending reply to {room.client.client_id}...")
    result = send_message(room.profile, room.client, reply_text)
    print(f"✅ [{room.profile.platform}] Reply sent, result: {result}")

    # Mark messages as processed
    incoming_msgs.update(processed=True)

    # Update room timestamps & reset waiting flag
    room.last_outgoing_time = timezone.now()
    room.last_incoming_time = None
    room.is_waiting_reply = False
    room.save(update_fields=["last_outgoing_time", "last_incoming_time", "is_waiting_reply"])

    print(f"🎉 [{room.profile.platform}] Reply sent successfully for room {room.id}")
    return f"Reply sent for room {room.id}"

@shared_task
def cleanup_system():
    """
    Periodic task to clean up:
    1. Useless Redis token cache for inactive companies.
    2. Extra UserSession data (keep only last 20 per user).
    3. Extra ChatMessage data (keep only last 20 per room).
    4. Extra Alert data (keep only last 20 per user).
    5. Reset stuck ChatRooms.
    """
    from django_redis import get_redis_connection
    from Finance.models import Subscriptions
    from Others.models import UserSession, Alert
    from Socials.models import ChatRoom, ChatMessage
    from django.db.models import Count
    from django.utils import timezone
    
    # 1. Cleanup Token Cache
    try:
        redis = get_redis_connection("default")
        for key in redis.scan_iter("company_token_*"):
            try:
                # Key is usually company_token_<id>
                # Using decode() as redis keys can be bytes
                key_str = key.decode() if isinstance(key, bytes) else key
                company_id = key_str.split("_")[-1]
                # Check if company has an active plan
                plan = Subscriptions.objects.filter(company_id=company_id, is_active=True, end__gt=timezone.now()).exists()
                if not plan:
                    redis.delete(key)
                    print(f"🗑️ Deleted useless token cache for company {company_id}")
            except Exception as e:
                print(f"Error checking token key {key}: {e}")
    except Exception as e:
        print(f"Redis connection error during cleanup: {e}")

    # 2. Cleanup User Sessions (Keep 20 per user)
    users_with_many_sessions = UserSession.objects.values('user').annotate(counts=Count('id')).filter(counts__gt=20)
    for entry in users_with_many_sessions:
        user_id = entry['user']
        sessions_to_keep = UserSession.objects.filter(user_id=user_id).order_by('-last_active')[:20].values_list('id', flat=True)
        deleted_count = UserSession.objects.filter(user_id=user_id).exclude(id__in=list(sessions_to_keep)).delete()[0]
        print(f"🗑️ Deleted {deleted_count} extra sessions for user {user_id}")

    # 3. Cleanup Chat Messages (Keep 20 per room)
    rooms_with_many_messages = ChatRoom.objects.annotate(counts=Count('messages')).filter(counts__gt=20)
    for room in rooms_with_many_messages:
        msgs_to_keep = ChatMessage.objects.filter(room=room).order_by('-timestamp')[:100].values_list('id', flat=True)
        deleted_count = ChatMessage.objects.filter(room=room).exclude(id__in=list(msgs_to_keep)).delete()[0]
        print(f"🗑️ Deleted {deleted_count} extra messages for room {room.id}")

    # 4. Cleanup Alerts (Keep 20 per user)
    users_with_many_alerts = Alert.objects.values('user').annotate(counts=Count('id')).filter(counts__gt=20)
    for entry in users_with_many_alerts:
        user_id = entry['user']
        alerts_to_keep = Alert.objects.filter(user_id=user_id).order_by('-time')[:20].values_list('id', flat=True)
        deleted_count = Alert.objects.filter(user_id=user_id).exclude(id__in=list(alerts_to_keep)).delete()[0]
        print(f"🗑️ Deleted {deleted_count} extra alerts for user {user_id}")

    # 5. Cleanup Bookings (Keep 20 per company)
    from Others.models import Booking
    from Accounts.models import Company
    companies_with_many_bookings = Booking.objects.values('company').annotate(counts=Count('id')).filter(counts__gt=20)
    for entry in companies_with_many_bookings:
        company_id = entry['company']
        if company_id:
            bookings_to_keep = Booking.objects.filter(company_id=company_id).order_by('-start_time')[:300].values_list('id', flat=True)
            deleted_count = Booking.objects.filter(company_id=company_id).exclude(id__in=list(bookings_to_keep)).delete()[0]
            print(f"🗑️ Deleted {deleted_count} extra bookings for company {company_id}")

    # 6. Reset stuck ChatRooms (stuck for > 30 mins)
    stuck_rooms = ChatRoom.objects.filter(
        is_waiting_reply=True,
        last_incoming_time__lt=timezone.now() - timezone.timedelta(minutes=30)
    )
    stuck_count = stuck_rooms.count()
    stuck_rooms.update(is_waiting_reply=False)
    if stuck_count > 0:
        print(f"🔓 Reset {stuck_count} stuck chat rooms")

    return "System cleanup successful"
