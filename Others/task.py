from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from .models import Booking


@shared_task
def send_booking_reminder(booking_id):
    """Send booking reminder via email/SMS"""
    try:
        from .models import Booking
        
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
            f"⏰ Reminder: Your appointment is in 1 hour!\n\n"
            f"Title: {booking.title}\n"
            f"Time: {start_local.strftime('%d %b %Y, %I:%M %p')}\n"
            f"Location: {booking.location or 'N/A'}\n"
            f"Event Link: {booking.event_link or 'N/A'}"
        )
        
        # Send SMS if number exists
        if hasattr(booking, 'number') and booking.number:
            from .helper import send_via_webhook_style
            send_via_webhook_style(booking.number, message)
            print(f"✅ SMS sent to {booking.number}")
        
        # Send email
        if booking.client:
            from django.core.mail import send_mail
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