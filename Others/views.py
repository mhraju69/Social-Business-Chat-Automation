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
from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from .serializers import *
from django.apps import apps
from rest_framework.exceptions import PermissionDenied
import requests

def get_google_access_token(google_account):
    data = {
        "client_id": google_account.client_id or settings.GOOGLE_CLIENT_ID,
        "client_secret": google_account.client_secret or settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": google_account.refresh_token,
        "grant_type": "refresh_token",
    }
    response = requests.post(google_account.token_uri, data=data)
    result = response.json()
    return result.get("access_token")

class ClientBookingView(APIView):
    def post(self, request, company_id):
        company = Company.objects.filter(id=company_id).first()
        if not company:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)

        if not hasattr(company, 'google_account'):
            return Response({"error": "Company has not connected Google Calendar"}, status=400)

        serializer = BookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        booking = serializer.save(company=company)

        # create event in Google Calendar
        google_account = company.google_account
        access_token = get_google_access_token(google_account)
        if not access_token:
            return Response({"error": "Unable to get access token"}, status=400)

        event_data = {
            "summary": booking.title,
            "description": booking.notes or "",
            "start": {"dateTime": booking.start_time.isoformat(), "timeZone": company.timezone},
            "end": {"dateTime": booking.end_time.isoformat() if booking.end_time else booking.start_time.isoformat(), 
                    "timeZone": company.timezone},
            "location": booking.location or "",
            "attendees": [{"email": booking.client}] if booking.client else [],
        }

        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=headers,
            json=event_data
        )

        if response.status_code in [200, 201]:
            event = response.json()
            booking.google_event_id = event.get("id")
            booking.event_link = event.get("htmlLink")
            booking.save()
        else:
            return Response({"error": "Failed to create Google Calendar event", "details": response.json()},
                            status=response.status_code)

        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)
    
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

class KnowledgeBaseListCreateView(generics.ListCreateAPIView):
    queryset = KnowledgeBase.objects.all()
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [permissions.IsAuthenticated]  # optional, remove if public

class KnowledgeBaseRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = KnowledgeBase.objects.all()
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [permissions.IsAuthenticated]  # optional
    lookup_field = 'id'

class GoogleConnectView(generics.CreateAPIView):
    serializer_class = GoogleAccountSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response({'error': 'Company not found'}, status=status.HTTP_404_NOT_FOUND)

        # Check if already connected
        google_account, created = GoogleAccount.objects.get_or_create(company=company)
        serializer = self.get_serializer(google_account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(company=company)

        msg = "Google account connected successfully" if created else "Google account updated successfully"
        return Response({"message": msg, "data": serializer.data}, status=status.HTTP_200_OK)