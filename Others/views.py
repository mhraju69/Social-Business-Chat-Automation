from django.urls import reverse
from google_auth_oauthlib.flow import Flow
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status, views,permissions,generics
from django.views.decorators.csrf import csrf_exempt
from .models import *
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from django.utils.timezone import now
from Whatsapp.models import WhatsAppProfile, Incoming as WAIncoming, Outgoing as WAOutgoing
from Facebook.models import FacebookProfile, Incoming as FBIncoming, Outgoing as FBOutgoing
from Instagram.models import InstagramProfile, Incoming as IGIncoming, Outgoing as IGOutgoing
from django.db.models.functions import ExtractWeekDay
from django.db.models import Count
from .serializers import *

class MessageStatsAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        weekday_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        start_date = now() - timedelta(days=7)

        results = {}

        # ================== WhatsApp ==================
        wa_stats = {day: 0 for day in weekday_names}
        wa_profiles = WhatsAppProfile.objects.filter(user=user)
        if wa_profiles.exists():
            # Get all clients that have messages linked to these profiles
            incoming_clients = WAIncoming.objects.filter(receiver__in=wa_profiles).values_list('client', flat=True)
            outgoing_clients = WAOutgoing.objects.filter(sender__in=wa_profiles).values_list('client', flat=True)
            client_ids = set(list(incoming_clients) + list(outgoing_clients))

            if client_ids:
                # Incoming
                data = (
                    WAIncoming.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    wa_stats[weekday_names[row['weekday'] - 1]] += row['count']

                # Outgoing
                data = (
                    WAOutgoing.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    wa_stats[weekday_names[row['weekday'] - 1]] += row['count']

        results['whatsapp'] = wa_stats

        # ================== Facebook ==================
        fb_stats = {day: 0 for day in weekday_names}
        fb_profiles = FacebookProfile.objects.filter(user=user)
        if fb_profiles.exists():
            # Get all clients linked to this user's FB profiles
            incoming_clients = FBIncoming.objects.filter(receiver__in=fb_profiles).values_list('client', flat=True)
            outgoing_clients = FBOutgoing.objects.filter(sender__in=fb_profiles).values_list('client', flat=True)
            client_ids = set(list(incoming_clients) + list(outgoing_clients))

            if client_ids:
                # Incoming
                data = (
                    FBIncoming.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    fb_stats[weekday_names[row['weekday'] - 1]] += row['count']

                # Outgoing
                data = (
                    FBOutgoing.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    fb_stats[weekday_names[row['weekday'] - 1]] += row['count']

        results['facebook'] = fb_stats

        # ================== Instagram ==================
        ig_stats = {day: 0 for day in weekday_names}
        ig_profiles = InstagramProfile.objects.filter(user=user)
        if ig_profiles.exists():
            # Incoming
            data = (
                IGIncoming.objects.filter(timestamp__gte=start_date, receiver__in=ig_profiles)
                .annotate(weekday=ExtractWeekDay('timestamp'))
                .values('weekday')
                .annotate(count=Count('id'))
            )
            for row in data:
                ig_stats[weekday_names[row['weekday'] - 1]] += row['count']

            # Outgoing
            data = (
                IGOutgoing.objects.filter(timestamp__gte=start_date, sender__in=ig_profiles)
                .annotate(weekday=ExtractWeekDay('timestamp'))
                .values('weekday')
                .annotate(count=Count('id'))
            )
            for row in data:
                ig_stats[weekday_names[row['weekday'] - 1]] += row['count']

        results['instagram'] = ig_stats

        return Response(results)

@api_view(['POST'])
def connect_google(request):
    """
    Creates Google OAuth2 authorization URL dynamically based on current domain.
    """
    client_id = request.data.get('client_id')
    client_secret = request.data.get('client_secret')

    if not client_id or not client_secret:
        return Response(
            {"error": "Missing client_id or client_secret."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # ✅ Dynamically build redirect URI using URL name
        redirect_uri = request.build_absolute_uri(reverse('google_callback'))

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": [redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"]
        )

        flow.redirect_uri = redirect_uri

        auth_url, _ = flow.authorization_url(
            prompt='consent',
            access_type='offline',
            include_granted_scopes='true'
        )

        return Response({
            "auth_url": auth_url,
            "redirect_uri": redirect_uri  # optional, for debugging
        })

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@api_view(['POST'])
def google_callback(request):
    from django.urls import reverse
    from google_auth_oauthlib.flow import Flow
    import google.auth.transport.requests

    client_id = request.data.get("client_id")
    client_secret = request.data.get("client_secret")
    auth_response = request.data.get("auth_response")

    if not client_id or not client_secret or not auth_response:
        return Response(
            {"error": "Missing client_id, client_secret, or auth_response."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # ✅ Dynamically rebuild redirect URI
        redirect_uri = request.build_absolute_uri(reverse('google_callback'))

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": [redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"]
        )

        flow.redirect_uri = redirect_uri
        flow.fetch_token(authorization_response=auth_response)

        creds = flow.credentials
        user = request.user if request.user.is_authenticated else None

        GoogleAccount.objects.update_or_create(
            user=user,
            defaults={
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "scopes": " ".join(creds.scopes),
            }
        )

        return Response({"message": "Google account connected successfully"})

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BookingAPIView(views.APIView):
    """
    APIView to Create, Update, and Delete bookings.
    Checks DB and optionally Google Calendar for conflicts.
    """

    def _get_google_service(self, company_id):
        try:
            google_account = GoogleAccount.objects.get(user__company_id=company_id)
            creds = Credentials(
                token=google_account.access_token,
                refresh_token=google_account.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=google_account.client_id,
                client_secret=google_account.client_secret,
                scopes=["https://www.googleapis.com/auth/calendar"]
            )
            service = build("calendar", "v3", credentials=creds)
            return service
        except GoogleAccount.DoesNotExist:
            return None

    def _check_db_conflict(self, company_id, start_time, end_time, exclude_id=None):
        qs = Booking.objects.filter(
            company_id=company_id,
            start_time__lt=end_time,
            end_time__gt=start_time
        )
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        return qs.exists()

    def _check_google_conflict(self, service, start_time, end_time):
        if not service:
            return False
        try:
            body = {
                "timeMin": start_time.isoformat() + 'Z',
                "timeMax": end_time.isoformat() + 'Z',
                "timeZone": "UTC",
                "items": [{"id": "primary"}]
            }
            freebusy = service.freebusy().query(body=body).execute()
            busy_times = freebusy['calendars']['primary']['busy']
            return bool(busy_times)
        except Exception:
            # If Google API fails, we assume slot is free to avoid blocking
            return False

    # ---------------- CREATE ----------------
    def post(self, request):
        data = request.data
        company_id = data.get("company_id")
        title = data.get("title")
        description = data.get("description", "")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        if not all([company_id, title, start_time, end_time]):
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_time = timezone.datetime.fromisoformat(start_time)
            end_time = timezone.datetime.fromisoformat(end_time)
        except ValueError:
            return Response({"error": "Invalid datetime format"}, status=status.HTTP_400_BAD_REQUEST)

        # DB conflict
        if self._check_db_conflict(company_id, start_time, end_time):
            return Response({"error": "Time slot already booked in DB"}, status=status.HTTP_400_BAD_REQUEST)

        # Google Calendar conflict
        service = self._get_google_service(company_id)
        if self._check_google_conflict(service, start_time, end_time):
            return Response({"error": "Time slot not available in Google Calendar"}, status=status.HTTP_400_BAD_REQUEST)

        google_event_id = None
        event_link = None

        if service:
            # Create event in Google Calendar
            event_body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
            }
            event = service.events().insert(calendarId='primary', body=event_body).execute()
            google_event_id = event.get('id')
            event_link = event.get('htmlLink')

        booking = Booking.objects.create(
            company_id=company_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            google_event_id=google_event_id,
            event_link=event_link
        )

        return Response({"message": "Booking created", "booking_id": booking.id, "google_event_link": event_link}, status=status.HTTP_201_CREATED)

    # ---------------- UPDATE ----------------
    def put(self, request, booking_id):
        data = request.data
        try:
            booking = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            return Response({"error": "Booking not found"}, status=status.HTTP_404_NOT_FOUND)

        title = data.get("title", booking.title)
        description = data.get("description", booking.description)
        start_time = data.get("start_time", booking.start_time.isoformat())
        end_time = data.get("end_time", booking.end_time.isoformat())

        try:
            start_time = timezone.datetime.fromisoformat(start_time)
            end_time = timezone.datetime.fromisoformat(end_time)
        except ValueError:
            return Response({"error": "Invalid datetime format"}, status=status.HTTP_400_BAD_REQUEST)

        # DB conflict
        if self._check_db_conflict(booking.company_id, start_time, end_time, exclude_id=booking.id):
            return Response({"error": "Time slot already booked in DB"}, status=status.HTTP_400_BAD_REQUEST)

        # Google Calendar conflict
        service = self._get_google_service(booking.company_id)
        if self._check_google_conflict(service, start_time, end_time):
            return Response({"error": "Time slot not available in Google Calendar"}, status=status.HTTP_400_BAD_REQUEST)

        # Update Google Event if exists
        if service and booking.google_event_id:
            event_body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end_time.isoformat(), "timeZone": "UTC"},
            }
            service.events().update(calendarId='primary', eventId=booking.google_event_id, body=event_body).execute()

        # Update DB
        booking.title = title
        booking.description = description
        booking.start_time = start_time
        booking.end_time = end_time
        booking.save()

        return Response({"message": "Booking updated", "booking_id": booking.id}, status=status.HTTP_200_OK)

    # ---------------- DELETE ----------------
    def delete(self, request, booking_id):
        try:
            booking = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            return Response({"error": "Booking not found"}, status=status.HTTP_404_NOT_FOUND)

        service = self._get_google_service(booking.company_id)

        # Delete from Google Calendar if exists
        if service and booking.google_event_id:
            try:
                service.events().delete(calendarId='primary', eventId=booking.google_event_id).execute()
            except Exception:
                pass  # ignore Google errors

        # Delete from DB
        booking.delete()
        return Response({"message": "Booking deleted"}, status=status.HTTP_200_OK)

class StripeListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StripeSerializer

    def get_queryset(self):
        user = self.request.user
        company = getattr(user, 'company', None)
        if hasattr(company, 'first'):
            company = company.first()  # get actual Company instance
        return Stripe.objects.filter(company=company)

class StripeUpdateView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = StripeSerializer

    def get_object(self):
        user = self.request.user
        company_qs = getattr(user, 'company', None)

        if hasattr(company_qs, 'first'):
            company = company_qs.first()
        else:
            company = company_qs

        if not company:
            raise serializers.ValidationError("User has no associated company.")

        try:
            stripe_obj = company.stripe  # OneToOneField reverse
        except ObjectDoesNotExist:
            raise serializers.ValidationError("Stripe object does not exist for this company.")

        return stripe_obj
    
