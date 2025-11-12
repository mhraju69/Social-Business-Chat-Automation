from django.urls import reverse
from google_auth_oauthlib.flow import Flow
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status,permissions,generics
from rest_framework.views import APIView 
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import csrf_exempt
from .models import *
from Finance.models import *
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from .serializers import *
from django.apps import apps
from rest_framework.exceptions import PermissionDenied

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

class BookingAPIView(APIView):
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

class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    # --- Chat related function ---
    def get_open_chats_count(self, user, minutes=10):
        user_profiles = ChatProfile.objects.filter(user=user)
        rooms = ChatRoom.objects.filter(profile__in=user_profiles)

        now = timezone.now()
        threshold_time = now - timedelta(minutes=minutes)

        open_chat_count = 0
        for room in rooms:
            last_message = room.messages.order_by('-timestamp').first()
            if last_message and last_message.timestamp >= threshold_time:
                open_chat_count += 1

        return open_chat_count

    # --- Payment related function ---
    def get_today_payments(self, company, timezone_name=None):
        tz_name = timezone_name or getattr(company, 'timezone', 'UTC')
        company_tz = pytz.timezone(tz_name)

        now_utc = timezone.now()
        now_local = now_utc.astimezone(company_tz)

        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        start_utc = start_of_day.astimezone(pytz.UTC)
        end_utc = end_of_day.astimezone(pytz.UTC)

        payments_qs = Payment.objects.filter(
            company=company,
            payment_date__gte=start_utc,
            payment_date__lt=end_utc
        )

        total_amount = sum(payment.amount for payment in payments_qs)

        payment_list = []
        for payment in payments_qs:
            payment_list.append({
                "transaction_id": payment.transaction_id,
                "amount": float(payment.amount),
                "type": payment.type,
                "reason": payment.reason,
                "payment_date": payment.payment_date.astimezone(company_tz).strftime("%Y-%m-%d %H:%M:%S")
            })

        return {
            "total": float(total_amount),
            "list": payment_list
        }

    # --- Booking related function ---
    def get_today_meetings(self, company, timezone_name=None):
        tz_name = timezone_name or getattr(company, 'timezone', 'UTC')
        company_tz = pytz.timezone(tz_name)

        now_utc = timezone.now()
        now_local = now_utc.astimezone(company_tz)

        # আজকের শুরু এবং শেষ সময়
        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        start_utc = start_of_day.astimezone(pytz.UTC)
        end_utc = end_of_day.astimezone(pytz.UTC)

        # আজকের meetings
        today_qs = Booking.objects.filter(
            company=company,
            start_time__gte=start_utc,
            start_time__lt=end_utc
        )

        today_meetings_list = []
        for booking in today_qs:
            today_meetings_list.append({
                "title": booking.title,
                "client": booking.client,
                "start_time": booking.start_time.astimezone(company_tz).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": booking.end_time.astimezone(company_tz).strftime("%Y-%m-%d %H:%M:%S") if booking.end_time else None,
                "location": booking.location,
                "price": booking.price,
                "notes": booking.notes,
                "event_link": booking.event_link
            })

        # Remaining meetings (আগামীকাল বা পরে)
        tomorrow_start = end_of_day
        tomorrow_start_utc = tomorrow_start.astimezone(pytz.UTC)

        remaining_count = Booking.objects.filter(
            company=company,
            start_time__gte=tomorrow_start_utc
        ).count()

        return {
            "count": today_qs.count(),
            "list": today_meetings_list,
            "remaining": remaining_count
        }

    def get_chat_channel_status(self, user):

        platforms = ['whatsapp', 'facebook', 'instagram']
        status = {}

        for platform in platforms:
            exists = ChatProfile.objects.filter(user=user, platform=platform).exists()
            status[platform] = exists

        return status
    
    # --- Dashboard API endpoint ---
    def get(self, request, *args, **kwargs):
        timezone_name = request.query_params.get('timezone', None)
        company = getattr(request.user, 'company', None)

        open_chat_count = self.get_open_chats_count(request.user, minutes=10)
        today_payments = self.get_today_payments(company, timezone_name) if company else {"total_amount": 0, "payments": []}
        today_meetings = self.get_today_meetings(company, timezone_name) if company else {"today_count": 0, "today_meetings": [], "remaining_count": 0}
        chat_status = self.get_chat_channel_status(request.user)

        return Response({
            "open_cha": open_chat_count,
            "today_payments": today_payments,
            "today_meetings": today_meetings,
             "channel_status": chat_status
        })
    
class AnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        print("\n" + "="*80)
        print("📊 [DEBUG] Analytics API called")
        print(f"👤 [DEBUG] User: {request.user}")
        print(f"🌐 [DEBUG] Query params: {request.query_params}")
        print("="*80 + "\n")
        
        # Get timezone from query params
        timezone_param = request.query_params.get('timezone', 'UTC')
        
        serializer = AnalyticsSerializer(
            instance={},
            context={
                'request': request,
                'timezone': timezone_param
            }
        )
        
        response_data = serializer.data
        print("\n" + "="*80)
        print("📤 [DEBUG] Analytics Response:")
        print(response_data)
        print("="*80 + "\n")
        
        return Response(response_data)

class UserActivityLogView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        activities = []
        
        # Models to track
        tracked_models = [
            {'model': 'Service', 'app': 'Accounts'},
            {'model': 'User', 'app': 'Accounts'},
            {'model': 'CompanyInfo', 'app': 'Accounts'},
            {'model': 'Company', 'app': 'Accounts'},
        ]
        
        for tracked in tracked_models:
            model = apps.get_model(tracked['app'], tracked['model'])
            
            # Get history for this user's records only
            history_model = model.history.model
            user_history = history_model.objects.filter(
                history_user=user
            ).order_by('-history_date')[:50]
            
            for record in user_history:
                activity = {
                    'id': record.history_id,
                    'activity_type': self.get_activity_type(record),
                    'title': self.get_activity_title(record),
                    'description': self.get_activity_description(record),
                    'icon': self.get_activity_icon(record),
                    'timestamp': record.history_date,
                    'model_name': tracked['model'],
                    'changes': self.get_field_changes(record)  # NEW: Detailed changes
                }
                activities.append(activity)
        
        # Sort by timestamp (newest first)
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Return last 20 activities
        serializer = ActivityLogSerializer(activities[:20], many=True)
        return Response(serializer.data)
    
    def get_activity_type(self, record):
        type_map = {
            '+': 'created',
            '~': 'updated',
            '-': 'deleted'
        }
        return type_map.get(record.history_type, 'unknown')
    
    def get_activity_title(self, record):
        model_name = record._meta.model.__name__.replace('Historical', '')
        
        if record.history_type == '+':
            return f"New {model_name} data added"
        elif record.history_type == '~':
            return f"{model_name} data updated"
        elif record.history_type == '-':
            return f"{model_name} data removed"
    
    def get_field_changes(self, record):
        """Get detailed field-by-field changes"""
        if record.history_type != '~':  # Only for updates
            return []
        
        changes = []
        prev = record.prev_record
        
        if not prev:
            return []
        
        # Fields to ignore
        ignored_fields = [
            'id', 'history_id', 'history_date', 'history_change_reason',
            'history_type', 'history_user', 'history_user_id','updated_at', 'created_at'
        ]
        
        # Get all fields
        for field in record._meta.fields:
            field_name = field.name
            
            if field_name in ignored_fields:
                continue
            
            try:
                old_value = getattr(prev, field_name, None)
                new_value = getattr(record, field_name, None)
                
                # Check if value changed
                if old_value != new_value:
                    changes.append({
                        'field': self.format_field_name(field_name),
                        'field_name': field_name,
                        'old_value': self.format_value(old_value),
                        'new_value': self.format_value(new_value),
                    })
            except Exception as e:
                continue
        
        return changes
    
    def format_field_name(self, field_name):
        """Convert field_name to readable format"""
        # Convert snake_case to Title Case
        return field_name.replace('_', ' ').title()
    
    def format_value(self, value):
        """Format value for display"""
        if value is None:
            return 'None'
        elif isinstance(value, bool):
            return 'Yes' if value else 'No'
        elif hasattr(value, 'strftime'):  # DateTime/Date/Time
            return value.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return str(value)
    
    def get_activity_description(self, record):
        """Generate human-readable description"""
        model_name = record._meta.model.__name__.replace('Historical', '')
        
        if record.history_type == '+':
            # For creation
            if hasattr(record, 'name'):
                return f"'{record.name}' was created"
            elif hasattr(record, 'question'):
                return f"Question: '{record.question[:50]}...'"
            return f"New {model_name} created"
            
        elif record.history_type == '~':
            # For updates - show what changed
            changes = self.get_field_changes(record)
            
            if changes:
                # Create a summary of changes
                if len(changes) == 1:
                    change = changes[0]
                    return f"{change['field']} changed from '{change['old_value']}' to '{change['new_value']}'"
                else:
                    field_names = [c['field'] for c in changes[:3]]
                    if len(changes) > 3:
                        return f"Updated {', '.join(field_names)} and {len(changes) - 3} more field(s)"
                    return f"Updated {', '.join(field_names)}"
            
            return f"{model_name} was updated"
            
        elif record.history_type == '-':
            # For deletion
            if hasattr(record, 'name'):
                return f"'{record.name}' was deleted"
            return f"{model_name} was removed"
    
    def get_activity_icon(self, record):
        icon_map = {
            '+': 'info',
            '~': 'edit',
            '-': 'trash'
        }
        return icon_map.get(record.history_type, 'info')

class OpeningHoursCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def post(self, request):
        company = Company.objects.filter(user = request.user).first()
        company_id = company.id
        days = request.data.get('days')  # e.g. ["mon", "wed", "fri"]
        start = request.data.get('start')
        end = request.data.get('end')

        if not all([company_id, days, start, end]):
            return Response({"error": "company, days, start, end are required"}, status=status.HTTP_400_BAD_REQUEST)

        objects = []
        for day in days:
            objects.append(OpeningHours(company_id=company_id, day=day, start=start, end=end))

        OpeningHours.objects.bulk_create(objects)  # create all at once

        serializer = OpeningHoursSerializer(objects, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def get(self, request):
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response({"detail": "You do not have an associated company."}, status=status.HTTP_403_FORBIDDEN)

        obj = OpeningHours.objects.filter(company=company)
        serializer = OpeningHoursSerializer(obj, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class OpeningHoursUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    queryset = OpeningHours.objects.all()
    serializer_class = OpeningHoursSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_object(self):
        obj = super().get_object()

        company = Company.objects.filter(user=self.request.user).first()

        if not company:
            raise PermissionDenied("You do not have an associated company.")

        if obj.company != company:
            raise PermissionDenied("You do not have permission to modify this record.")

        return obj
    
class UserAlertsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user  # SimpleJWT automatically sets request.user
        alerts = Alert.objects.filter(user=user)
        serializer = AlertSerializer(alerts, many=True)
        return Response(serializer.data)
    
class MarkAlertReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, alert_id):
        try:
            alert = Alert.objects.get(id=alert_id, user=request.user)
            alert.is_read = True
            alert.save()
            return Response({"detail": "Alert marked as read"})
        except Alert.DoesNotExist:
            return Response({"detail": "Alert not found"}, status=status.HTTP_404_NOT_FOUND)
