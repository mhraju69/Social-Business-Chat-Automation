from django.utils import timezone
from celery import shared_task
from django.core.mail import send_mail
from .models import Booking
import time    
from Socials.models import ChatRoom, ChatMessage
from Socials.helper import generate_ai_response, send_message

@shared_task
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

@shared_task
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
    reply_text = generate_ai_response(full_text, room.profile.platform)
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