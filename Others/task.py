from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from .models import Booking


@shared_task
def send_booking_reminder(booking_id):
    try:
        booking = Booking.objects.get(id=booking_id)

        subject = "Reminder: Your Meeting Starts Soon"

        message = (
            f"Hello,\n\n"
            f"This is a reminder about your upcoming meeting:\n\n"
            f"Title: {booking.title}\n"
            f"Start Time: {booking.start_time}\n"
            f"Location: {booking.location or 'N/A'}\n"
            f"Join Link: {booking.event_link or 'N/A'}\n\n"
            f"Thank you."
        )

        send_mail(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            [booking.client],
            fail_silently=False,
        )

        return f"Reminder sent for booking ID: {booking_id}"

    except Booking.DoesNotExist:
        return f"Booking ID {booking_id} not found"
