from rest_framework.response import Response
from rest_framework import status,permissions,generics
from rest_framework.views import APIView 
from rest_framework.viewsets import ModelViewSet 
from rest_framework.permissions import IsAuthenticated,AllowAny
from .models import *
from Finance.models import *
from django.conf import settings
from .serializers import *
from django.apps import apps
from rest_framework.exceptions import PermissionDenied
import requests
from django.utils import timezone
import pytz
from datetime import timedelta, datetime
from django.db.models import Sum,Count
from Accounts.permissions import *
from .helper import *
import urllib.parse
from django.shortcuts import render

def get_google_access_token(google_account):
    """Get a fresh access token using the refresh token"""
    if not google_account.refresh_token:
        print("❌ No refresh token available")
        return None
        
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": google_account.refresh_token,
        "grant_type": "refresh_token",
    }
    
    try:
        response = requests.post(google_account.token_uri, data=data)
        result = response.json()
        
        if response.status_code == 200:
            access_token = result.get("access_token")
            print(f"✅ Got new access token: {access_token[:20]}...")
            return access_token
        else:
            print(f"❌ Token refresh failed: {result}")
            return None
    except Exception as e:
        print(f"❌ Exception refreshing token: {e}")
        return None

class ClientBookingView(APIView):
    def post(self, request, company_id):
        company = Company.objects.filter(id=company_id).first()
        
        if not company:
            return Response(
                {"error": "Company not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        data = request.data.copy()
        number = data.get('number')
        
        # Get timezone from params (e.g., "Asia/Dhaka" or "+06:00")
        timezone_str = request.query_params.get('timezone') or request.data.get('timezone') or 'UTC'
        
        # Fix common timezone typos
        if timezone_str == "Dhaka/Asia":
            timezone_str = "Asia/Dhaka"
            
        try:
            # Try to parse as timezone name first (e.g., "Asia/Dhaka")
            user_tz = pytz.timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            user_tz = pytz.UTC
        
        # Calculate UTC times for Google Calendar
        calendar_start_utc = None
        calendar_end_utc = None
        
        if 'start_time' in data:
            start_time_local = data['start_time']
            
            if isinstance(start_time_local, str):
                # Parse the datetime string
                try:
                    start_dt = datetime.strptime(start_time_local, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Try alternate format if needed, or let serializer handle validation later
                    start_dt = datetime.strptime(start_time_local, "%Y-%m-%dT%H:%M:%S")
            else:
                start_dt = start_time_local
            
            # Localize to user timezone and convert to UTC for Calendar
            start_aware = user_tz.localize(start_dt)
            calendar_start_utc = start_aware.astimezone(pytz.UTC)
            
            # Note: We do NOT update data['start_time'] so DB saves the raw input (as UTC/Naive)
        
        if 'end_time' in data:
            end_time_local = data['end_time']
            
            if isinstance(end_time_local, str):
                try:
                    end_dt = datetime.strptime(end_time_local, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    end_dt = datetime.strptime(end_time_local, "%Y-%m-%dT%H:%M:%S")
            else:
                end_dt = end_time_local
            
            end_aware = user_tz.localize(end_dt)
            calendar_end_utc = end_aware.astimezone(pytz.UTC)
        
        # Create booking
        serializer = BookingSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save(company=company)
        
        # Create Google Calendar event
        google_account = GoogleCalendar.objects.filter(company=company).first()
        calendar_error = None
        
        if google_account:
            try:
                access_token = get_google_access_token(google_account)
                if not access_token:
                    calendar_error = "Unable to get access token from refresh token"
                    print(f"❌ Google Calendar Error: {calendar_error}")
                else:
                    # Use the calculated UTC times for Google Calendar
                    # We send timeZone="UTC" because we already converted to UTC
                    
                    start_val = calendar_start_utc if calendar_start_utc else booking.start_time
                    end_val = calendar_end_utc if calendar_end_utc else (booking.end_time or booking.start_time)
                    
                    # Prepare event data
                    event_data = {
                        "summary": booking.title,
                        "description": booking.notes or "",
                        "start": {
                            "dateTime": start_val.isoformat(),
                            "timeZone": "UTC"
                        },
                        "end": {
                            "dateTime": end_val.isoformat(),
                            "timeZone": "UTC"
                        },
                        "location": booking.location or "",
                        "attendees": [{"email": booking.client}] if booking.client else [],
                    }
                    
                    print(f"📅 Creating Google Calendar event...")
                    print(f"   Timezone: UTC (Converted from {timezone_str})")
                    print(f"   Start: {start_val.isoformat()}")
                    
                    headers = {"Authorization": f"Bearer {access_token}"}
                    response = requests.post(
                        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                        headers=headers,
                        json=event_data
                    )
                    
                    print(f"   Response Status: {response.status_code}")
                    
                    if response.status_code in [200, 201]:
                        event = response.json()
                        booking.google_event_id = event.get("id")
                        booking.event_link = event.get("htmlLink")
                        booking.save()
                        print(f"✅ Google Calendar event created: {booking.event_link}")
                    else:
                        calendar_error = response.json()
                        print(f"❌ Google Calendar API Error: {calendar_error}")
                        
            except Exception as e:
                calendar_error = str(e)
                print(f"❌ Exception creating Google Calendar event: {e}")
        else:
            print("ℹ️ No Google Account found for this company")
        
        # Send confirmation SMS
        if number:
            # Use the raw booking time (which matches input) for SMS
            # No timezone conversion needed as requested
            
            text_message = (
                f"Booking Confirmed ✓\n"
                f"Title: {booking.title}\n"
                f"Time: {booking.start_time.strftime('%d %b %Y, %I:%M %p')}\n"
                f"Location: {booking.location or 'N/A'}\n"
                f"Event Link: {booking.event_link or 'N/A'}\n"
                f"\n⏰ Reminder: 1 hour before"
            )
            
            send_via_webhook_style(number, text_message)
        
        return Response(
            BookingSerializer(booking).data, 
            status=status.HTTP_201_CREATED
        )

class DashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated,IsEmployeeAndCanViewDashboard]

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
            payment_date__lt=end_utc,
        )

        total_amount = sum(payment.amount for payment in payments_qs.filter(status="success"))

        payment_list = []
        for payment in payments_qs:
            payment_list.append({
                "transaction_id": payment.transaction_id,
                "amount": float(payment.amount),
                "type": payment.type,
                "reason": payment.reason,
                "status" : payment.status,
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
        company = Company.objects.filter(user=user).first()
        calendar = GoogleCalendar.objects.filter(company=company).exists()
        platforms = ['whatsapp', 'facebook', 'instagram']
        status = {}

        for platform in platforms:
            exists = ChatProfile.objects.filter(user=user, platform=platform).exists()
            status[platform] = exists
        
        status['calendar'] = calendar

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
            "open_chat": open_chat_count,
            "today_payments": today_payments,
            "today_meetings": today_meetings,
            "channel_status": chat_status
        })
    
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
        serializer = ActivityLogSerializer(activities[:10], many=True)
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
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [permissions.IsAuthenticated] 

    def get_queryset(self):
        return KnowledgeBase.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class KnowledgeBaseRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = KnowledgeBase.objects.all()
    serializer_class = KnowledgeBaseSerializer
    permission_classes = [permissions.IsAuthenticated]  # optional
    lookup_field = 'id'

class AnalyticsView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated,IsEmployeeAndCanAccessAnalyticsReports]

    def get(self, request):
        try:
            company = Company.objects.get(user=request.user)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company profile not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        data = {
            "message_count": self.get_message(request, company),
            "booking_count": self.get_booking_count(request, company),
            "total_revenue": self.get_total_revenue(request, company),
            "new_customers": self.get_new_customers(company, request),
            "unanswered_messages": self.get_unanswered_messages(company, request),
            "channel_messages": self.channel_data(company, request),
        }

        return Response(data)

    def get_message(self, request, company):
        # ChatRoom এর মাধ্যমে messages filter করুন
        rooms = ChatRoom.objects.filter(profile__user=company.user)
        qs = ChatMessage.objects.filter(room__in=rooms)

        time_filter = request.GET.get("time", "all")
        channel = request.GET.get("channel", "all")
        msg_type = request.GET.get("type", "all")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")
        tz = request.GET.get("timezone", "UTC")

        qs = self.filter_by_time(qs, time_filter, start_date, end_date, tz)
        
        # Messages এর জন্য channel filter
        if channel != "all":
            qs = qs.filter(room__profile__platform=channel)
            
        qs = self.filter_by_type(qs, msg_type)

        # Get total count
        total_count = qs.count()
        
        # Get count per platform
        platforms = qs.values("room__profile__platform").annotate(count=Count("id"))
        
        # Initialize result with 0 for all platforms
        result = {
            "whatsapp": {"count": 0, "percentage": 0.0},
            "facebook": {"count": 0, "percentage": 0.0},
            "instagram": {"count": 0, "percentage": 0.0}
        }
        
        # Update with actual counts and calculate percentages
        for p in platforms:
            platform = p["room__profile__platform"]
            count = p["count"]
            percentage = round((count / total_count * 100), 2) if total_count > 0 else 0.0
            result[platform] = {
                "count": count,
                "percentage": percentage
            }
        res = {
            "whatsapp": result["whatsapp"]["percentage"],
            "facebook": result["facebook"]["percentage"],
            "instagram": result["instagram"]["percentage"]
        }
        
        return {
            "total": total_count,
            "platforms": res
        }

    def get_booking_count(self, request, company):
        qs = Booking.objects.filter(company=company)

        time_filter = request.GET.get("time", "all")
        tz = request.GET.get("timezone", "UTC")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        qs = self.filter_by_time_generic(qs, time_filter, "start_time", start_date, end_date, tz)

        return qs.count()

    def get_total_revenue(self, request, company):
        qs = Payment.objects.filter(company=company)

        time_filter = request.GET.get("time", "all")
        tz = request.GET.get("timezone", "UTC")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        qs = self.filter_by_time_generic(qs, time_filter, "created_at", start_date, end_date, tz)

        total = qs.aggregate(total=Sum("amount"))["total"]
        return float(total) if total else 0.0

    def get_new_customers(self, company, request):
        user = company.user
        rooms = ChatRoom.objects.filter(profile__user=user)

        time_filter = request.GET.get("time", "all")
        channel = request.GET.get("channel", "all")
        tz = request.GET.get("timezone", "UTC")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        rooms = self.filter_by_time_generic(
            rooms, time_filter, "created_at", start_date, end_date, tz
        )

        # Rooms এর জন্য channel filter
        if channel != "all":
            rooms = rooms.filter(profile__platform=channel)

        return rooms.values("client").distinct().count()

    def get_unanswered_messages(self, company, request):
        user = company.user
        rooms = ChatRoom.objects.filter(profile__user=user)

        time_filter = request.GET.get("time", "all")
        channel = request.GET.get("channel", "all")
        tz = request.GET.get("timezone", "UTC")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")

        # Rooms এর জন্য channel filter
        if channel != "all":
            rooms = rooms.filter(profile__platform=channel)

        count = 0

        for room in rooms:
            last_msg = ChatMessage.objects.filter(room=room).order_by("-timestamp").first()
            if not last_msg:
                continue

            qs = ChatMessage.objects.filter(id=last_msg.id)
            qs = self.filter_by_time(qs, time_filter, start_date, end_date, tz)

            if not qs.exists():
                continue

            if last_msg.type == "incoming":
                count += 1

        return count

    def channel_data(self, company, request):
        user = company.user
        
        time_filter = request.GET.get("time", "all")
        start_date = request.GET.get("start_date")
        end_date = request.GET.get("end_date")
        tz = request.GET.get("timezone") or request.GET.get("tz") or "UTC"

        chat_profiles = ChatProfile.objects.filter(user=user)
        rooms = ChatRoom.objects.filter(profile__in=chat_profiles)
        
        qs = ChatMessage.objects.filter(
            room__in=rooms,
            type="incoming"
        )

        qs = self.filter_by_time(qs, time_filter, start_date, end_date, tz)

        platforms = qs.values("room__profile__platform").annotate(count=Count("id"))

        # সব platform এর জন্য 0 দিয়ে initialize করুন
        result = {
            "whatsapp": 0,
            "facebook": 0,
            "instagram": 0
        }
        
        # যে platform এ message আছে সেগুলো update করুন
        for p in platforms:
            platform = p["room__profile__platform"]
            result[platform] = p["count"]

        return result
    
    @staticmethod
    def filter_by_time(queryset, time_filter, start_date=None, end_date=None, tz="UTC"):
        user_tz = pytz.timezone(tz)
        now = timezone.now().astimezone(user_tz)

        if time_filter == "today":
            return queryset.filter(timestamp__date=now.date())

        if time_filter == "this_week":
            week_start = now - timedelta(days=now.weekday())
            return queryset.filter(timestamp__date__gte=week_start.date())

        if time_filter == "this_month":
            return queryset.filter(
                timestamp__year=now.year,
                timestamp__month=now.month
            )

        if time_filter == "this_year":
            return queryset.filter(timestamp__year=now.year)

        if time_filter == "custom" and start_date and end_date:
            return queryset.filter(timestamp__date__range=[start_date, end_date])

        return queryset

    @staticmethod
    def filter_by_time_generic(queryset, time_filter, date_field, start_date=None, end_date=None, tz="UTC"):
        user_tz = pytz.timezone(tz)
        now = timezone.now().astimezone(user_tz)

        if time_filter == "today":
            return queryset.filter(**{f"{date_field}__date": now.date()})

        if time_filter == "this_week":
            week_start = now - timedelta(days=now.weekday())
            return queryset.filter(**{f"{date_field}__date__gte": week_start.date()})

        if time_filter == "this_month":
            return queryset.filter(
                **{
                    f"{date_field}__year": now.year,
                    f"{date_field}__month": now.month
                }
            )

        if time_filter == "this_year":
            return queryset.filter(**{f"{date_field}__year": now.year})

        if time_filter == "custom" and start_date and end_date:
            return queryset.filter(**{f"{date_field}__date__range": [start_date, end_date]})

        return queryset

    @staticmethod
    def filter_by_type(queryset, msg_type):
        if msg_type == "all":
            return queryset

        if msg_type == "human":
            return queryset.filter(type="outgoing", send_by_bot=False)

        if msg_type == "ai":
            return queryset.filter(type="outgoing", send_by_bot=True)

        return queryset
    
class FinanceDataView(APIView):
    permission_classes = [IsAuthenticated,IsEmployeeAndCanAccessFinancialData]
    
    def get(self, request):
        try:
            company = Company.objects.get(user=request.user)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company profile not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        data = {
            "success_payment": Payment.success_payment_change_percentage(company),
            "failed_payment" : Payment.get_failed_payment_counts(company),
            "pending_payment": Payment.pending_payment_stats(company),
            "average_order" : Payment.average_order_value_change(company)
        }

        return Response(data)
    
class SupportTicketViewSet(ModelViewSet):
    serializer_class = SupportTicketSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = SupportTicket.objects.all()
    def get_queryset(self):
        user = self.request.user
        
        if user.is_staff:
            return SupportTicket.objects.all()
        return SupportTicket.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_staff and instance.user != request.user:
            return Response(
                {"error": "You don't have permission to edit this ticket."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)
    
class ConnectGoogleCalendarView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        company = Company.objects.filter(user=request.user).first()
        method = request.data.get("from", "web")
        if not company:
            return Response(
                {"error": "Company not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        google_account, _ = GoogleCalendar.objects.get_or_create(company=company)

        serializer = GoogleCalendarSerializer(
            google_account,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(company=company)

        redirect_uri = "https://ape-in-eft.ngrok-free.app/api/google/calendar/callback/"

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "scope": "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/userinfo.email",
            "state":f"{request.user.id}" ,
            "from":method

        }

        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            + urllib.parse.urlencode(params)
        )

        return Response({"auth_url": auth_url}, status=status.HTTP_200_OK)

class GoogleOAuthCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.query_params.get("code")
        state = request.query_params.get("state")  # Get user ID from state
        method = request.query_params.get("from")
        if not code:
            return Response(
                {"error": "Missing authorization code"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not state:
            return Response(
                {"error": "Missing state parameter"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get user from state parameter
        try:
            user_id = int(state)
            user = User.objects.get(id=user_id)
        except (ValueError, User.DoesNotExist):
            return Response(
                {"error": "Invalid user"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        company = Company.objects.filter(user=user).first()
        if not company:
            return Response(
                {"error": "Company not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        google_calendar = GoogleCalendar.objects.filter(company=company).first()
        if not google_calendar:
            return Response(
                {"error": "Google calendar not initialized"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Your redirect URL (must match the one used in SaveGoogleAccountView)
        redirect_uri = "https://ape-in-eft.ngrok-free.app/api/google/calendar/callback/"

        token_url = "https://oauth2.googleapis.com/token"

        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,           
            "grant_type": "authorization_code"
        }

        response = requests.post(token_url, data=data)

        if response.status_code != 200:
            return Response(
                {"error": "Token exchange failed", "details": response.json()},
                status=status.HTTP_400_BAD_REQUEST
            )

        token_data = response.json()

        # Save tokens
        google_calendar.access_token = token_data.get("access_token")
        google_calendar.refresh_token = token_data.get("refresh_token", google_calendar.refresh_token)
        google_calendar.scopes = ["https://www.googleapis.com/auth/calendar"]
        google_calendar.save()

        # return Response(
        #     {"message": "Google Calendar connected successfully!"}
        # )
        if method == "app":
            return render(request, 'redirect.html')
        return Response(
            {"message": "Google Calendar connected successfully!"}
        )

class ActiveSessionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = UserSession.objects.filter(user=request.user)
        data = [{
            "device": s.device,
            "browser": s.browser,
            "location": s.location,
            "ip": s.ip_address,
            "last_active": s.last_active,
            "session_id": s.id,
        } for s in list(reversed(sessions))[:5]]

        return Response(data)

class LogoutSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        try:
            session = UserSession.objects.get(id=session_id, user=request.user)
            session.is_active = False
            session.save()
            return Response({"message": "Logout successful"})
        except UserSession.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

class LogoutAllSessionsView(APIView):
    permission_classes = [IsAuthenticated] 

    def post(self, request):
        try:
            sessions = UserSession.objects.filter(user=request.user, is_active=True)
            sessions.update(is_active=False)
            return Response({"message": "Logout successful"})
        except UserSession.DoesNotExist:
            return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

class MonthlyBookingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            company = Company.objects.get(user=request.user)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company profile not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        tz_name = request.GET.get('timezone') or 'UTC'
        try:
            company_tz = pytz.timezone(tz_name)
        except pytz.exceptions.UnknownTimeZoneError:
            company_tz = pytz.UTC

        now_utc = timezone.now()
        now_local = now_utc.astimezone(company_tz)
        try:
            month = int(request.GET.get('month', now_local.month))
            year = int(request.GET.get('year', now_local.year))
            day_param = request.GET.get('day')
            day = int(day_param) if day_param else None
        except (ValueError, TypeError):
            return Response(
                {"error": "Invalid date parameters"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if month < 1 or month > 12:
            return Response(
                {"error": "Month must be between 1 and 12"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if day:
            try:
                # Calculate start and end of the day in local timezone
                start_local = company_tz.localize(
                    datetime(year, month, day, 0, 0, 0)
                )
                # End of day is start of next day
                end_local = start_local + timedelta(days=1)
            except ValueError:
                return Response(
                    {"error": "Invalid day for given month and year"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Calculate start and end of the month in local timezone
            start_local = company_tz.localize(
                datetime(year, month, 1, 0, 0, 0)
            )
            
            # Calculate end of month (start of next month)
            if month == 12:
                end_local = company_tz.localize(
                    datetime(year + 1, 1, 1, 0, 0, 0)
                )
            else:
                end_local = company_tz.localize(
                    datetime(year, month + 1, 1, 0, 0, 0)
                )

        # Convert to UTC for database query
        start_utc = start_local.astimezone(pytz.UTC)
        end_utc = end_local.astimezone(pytz.UTC)

        # Query bookings for the month
        bookings_qs = Booking.objects.filter(
            company=company,
            start_time__gte=start_utc,
            start_time__lt=end_utc
        ).order_by('start_time')

        # Prepare booking list with details
        bookings_list = []
        for booking in bookings_qs:
            # Convert times to local timezone for display
            start_local = booking.start_time.astimezone(company_tz)
            end_local = booking.end_time.astimezone(company_tz) if booking.end_time else None

            booking_data = {
                "id": booking.id,
                "title": booking.title,
                "client": booking.client,
                "start_time": start_local.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end_local.strftime("%Y-%m-%d %H:%M:%S") if end_local else None,
                "location": booking.location,
                "price": booking.price,
                "notes": booking.notes,
                "event_link": booking.event_link,
                "google_event_id": booking.google_event_id,
                "reminder_hours_before": booking.reminder_hours_before,
                "created_at": booking.created_at.astimezone(company_tz).strftime("%Y-%m-%d %H:%M:%S")
            }
            bookings_list.append(booking_data)

        return Response({
            "day": day,
            "month": month,
            "year": year,
            "timezone": tz_name,
            "total_bookings": bookings_qs.count(),
            "bookings": bookings_list
        }, status=status.HTTP_200_OK)

class AITrainingFileBulkUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)
        
        files = request.FILES.getlist('files')
        if not files:
            return Response({"error": "No files provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        created_files = []
        for file in files:
            ai_file = AITrainingFile.objects.create(company=company, file=file)
            created_files.append(ai_file)
            
        serializer = AITrainingFileSerializer(created_files, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def get(self, request):
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response({"error": "Company not found"}, status=status.HTTP_404_NOT_FOUND)
            
        files = AITrainingFile.objects.filter(company=company)
        serializer = AITrainingFileSerializer(files, many=True)
        return Response(serializer.data)
