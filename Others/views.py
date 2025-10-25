# views.py
from rest_framework import views, status, generics
from rest_framework.response import Response
from .models import Booking
from .serializers import BookingSerializer
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from django.utils.dateparse import parse_datetime
from datetime import timedelta

# ---------------------------
# Google Calendar Helper
# ---------------------------
def get_google_calendar_service(user, data=None):
    """
    Returns a tuple: (service, start_time, end_time)
    Raises ValueError if token missing or invalid, or if time invalid.
    """
    token = data.get("google_token")
    if not token:
        raise ValueError("No Google token found for this user.")
    
    creds = Credentials(token=token)
    service = build('calendar', 'v3', credentials=creds)

    start_time = parse_datetime(data.get("start_time"))
    if not start_time:
        raise ValueError("start_time is required and must be valid ISO format.")

    end_time = parse_datetime(data.get("end_time")) if data.get("end_time") else start_time + timedelta(hours=1)


    # Check DB overlap
    if Booking.objects.filter(
        user=user,
        start_time__lt=end_time,
        end_time__gt=start_time
    ).exists():
        raise ValueError("Booking conflict in database.")

    # Check Google Calendar free/busy
    busy_result = service.freebusy().query(body={
        "timeMin": start_time.isoformat(),
        "timeMax": end_time.isoformat(),
        "timeZone": "Asia/Dhaka",
        "items": [{"id": "primary"}]
    }).execute()

    if busy_result['calendars']['primary']['busy']:
        raise ValueError("Selected time slot is busy in Google Calendar.")

    return service, start_time, end_time

# ---------------------------
# Booking Management View
# ---------------------------
class BookingView(generics.ListCreateAPIView, generics.UpdateAPIView, generics.DestroyAPIView):
    serializer_class = BookingSerializer
    queryset = Booking.objects.all()
    lookup_field = 'id'

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        user = request.user
        data = request.data

        try:
            service, start_time, end_time = get_google_calendar_service(user, data)

            # Create Google event
            event = {
                'summary': data.get('title'),
                'description': data.get('description', ''),
                'start': {'dateTime': start_time.isoformat()},
                'end': {'dateTime': end_time.isoformat()},
            }
            created_event = service.events().insert(calendarId='primary', body=event).execute()
            google_event_id = created_event.get('id')

            # Save booking in DB
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            booking = serializer.save(
                user=user,
                google_event_id=google_event_id,
                event_link=created_event.get('htmlLink')
            )

            return Response(
                BookingSerializer(booking).data
            , status=status.HTTP_201_CREATED)

        except ValueError as ve:
            return Response({"error": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except HttpError as he:
            return Response({"error": f"Google Calendar API error: {he}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": f"Unexpected error: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    # ----------------------
    # PATCH / Reschedule
    # ----------------------
    def patch(self, request, *args, **kwargs):
        booking = self.get_object()
        user = request.user
        data = request.data
        try:

            service, start_time, end_time = get_google_calendar_service(user, data)

            # Update Google Calendar event
            event = service.events().get(calendarId='primary', eventId=booking.google_event_id).execute()
            event['start']['dateTime'] = start_time.isoformat()
            event['end']['dateTime'] = end_time.isoformat()
            updated_event = service.events().update(calendarId='primary', eventId=booking.google_event_id, body=event).execute()

            # Update DB
            serializer = self.get_serializer(booking, data={'start_time': start_time, 'end_time': end_time}, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return Response({
                "message": "Booking rescheduled successfully.",
                "google_event_link": updated_event.get('htmlLink'),
                "booking": serializer.data
            })

        except ValueError as ve:
            return Response({"error": str(ve)}, status=400)
        except HttpError as he:
            return Response({"error": str(he)}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    # ----------------------
    # DELETE / Cancel
    # ----------------------
    def delete(self, request, *args, **kwargs):
        booking = self.get_object()
        user = request.user
        if user != booking.user:
            return Response({"error": "You do not have permission to cancel this booking."}, status=403)
        try:  
            token = request.data.get("google_token")
            if not token:
                raise ValueError("No Google token found for this user.")
            
            creds = Credentials(token=token)
            service = build('calendar', 'v3', credentials=creds)
            if booking.google_event_id:
                service.events().delete(calendarId='primary', eventId=booking.google_event_id).execute()

            booking.delete()
            return Response({"message": "Booking cancelled successfully."})

        except ValueError as ve:
            return Response({"error": str(ve)}, status=400)
        except HttpError as he:
            return Response({"error": str(he)}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=400)
