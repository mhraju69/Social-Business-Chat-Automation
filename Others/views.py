from rest_framework.response import Response
from rest_framework import status,permissions,generics
from rest_framework.views import APIView 
from rest_framework.viewsets import ModelViewSet 
from rest_framework.permissions import IsAuthenticated
from .models import *
from Finance.models import *
from django.conf import settings
from .serializers import *
from django.apps import apps
from rest_framework.exceptions import PermissionDenied
import requests
from django.utils import timezone
import pytz
from datetime import timedelta
from django.db.models import Sum,Count
from Accounts.permissions import *
from .helper import *
import urllib.parse

def get_google_access_token(google_account):
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
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
            return Response(
                {"error": "Company not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        data = request.data.copy()
        number = data.get('number')
        tz_offset = company.user.timezone or "+6"
        
        # Convert local time to UTC
        if 'start_time' in data:
            start_time_local = data['start_time']  # "2025-11-21 06:06:00"
            
            # Parse as naive datetime
            if isinstance(start_time_local, str):
                start_dt = datetime.strptime(start_time_local, "%Y-%m-%d %H:%M:%S")
            else:
                start_dt = start_time_local
            
            # Get user timezone
            offset_hours = float(tz_offset)
            offset_minutes = int(offset_hours * 60)
            user_tz = pytz.FixedOffset(offset_minutes)
            
            # Localize to user timezone
            start_aware = user_tz.localize(start_dt)
            
            # Convert to UTC
            start_utc = start_aware.astimezone(pytz.UTC)
            
            print(f"📥 Input (local): {start_time_local}")
            print(f"🌍 Timezone: {tz_offset}")
            print(f"🌐 Saved (UTC): {start_utc}")
            
            data['start_time'] = start_utc
        
        if 'end_time' in data:
            end_time_local = data['end_time']
            
            if isinstance(end_time_local, str):
                end_dt = datetime.strptime(end_time_local, "%Y-%m-%d %H:%M:%S")
            else:
                end_dt = end_time_local
            
            offset_hours = float(tz_offset)
            offset_minutes = int(offset_hours * 60)
            user_tz = pytz.FixedOffset(offset_minutes)
            end_aware = user_tz.localize(end_dt)
            end_utc = end_aware.astimezone(pytz.UTC)
            
            data['end_time'] = end_utc
        
        # Create booking
        serializer = BookingSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save(company=company)
        
        # Create Google Calendar event
        google_account = GoogleAccount.objects.filter(company=company).first()
        if google_account:
            access_token = get_google_access_token(google_account)
            if not access_token:
                return Response(
                    {"error": "Unable to get access token"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Prepare event data with proper timezone
            event_data = {
                "summary": booking.title,
                "description": booking.notes or "",
                "start": {
                    "dateTime": booking.start_time.isoformat(),
                    "timeZone": "UTC"  # Since we're storing in UTC
                },
                "end": {
                    "dateTime": (booking.end_time or booking.start_time).isoformat(),
                    "timeZone": "UTC"
                },
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
        
        # Send confirmation SMS
        if number:
            # Convert UTC time back to local for display
            user_tz = parse_timezone_offset(tz_offset)
            start_local = booking.start_time.astimezone(user_tz)
            
            text_message = (
                f"Booking Confirmed ✓\n"
                f"Title: {booking.title}\n"
                f"Time: {start_local.strftime('%d %b %Y, %I:%M %p')}\n"
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

        return qs.count()

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
    
class SaveGoogleAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response(
                {"error": "Company not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        google_account, _ = GoogleAccount.objects.get_or_create(company=company)

        serializer = GoogleAccountSerializer(
            google_account,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(company=company)

        redirect_uri = request.build_absolute_uri("/api/google/oauth/callback/")

        params = {
            "client_id": google_account.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
            "scope": "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/userinfo.email"
        }

        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            + urllib.parse.urlencode(params)
        )

        return Response({"auth_url": auth_url}, status=status.HTTP_200_OK)

class GoogleOAuthCallbackView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = request.query_params.get("code")
        if not code:
            return Response(
                {"error": "Missing authorization code"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        company = Company.objects.filter(user=request.user).first()
        if not company:
            return Response(
                {"error": "Company not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        google_account = GoogleAccount.objects.filter(company=company).first()
        if not google_account:
            return Response(
                {"error": "Google account not initialized"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Your redirect URL (must match the one used in SaveGoogleAccountView)
        redirect_uri = request.build_absolute_uri("/api/google/oauth/callback/")

        token_url = "https://oauth2.googleapis.com/token"

        data = {
            "code": code,
            "client_id": google_account.client_id,
            "client_secret": google_account.client_secret,
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
        google_account.access_token = token_data.get("access_token")
        google_account.refresh_token = token_data.get("refresh_token", google_account.refresh_token)
        google_account.scopes = ["https://www.googleapis.com/auth/calendar"]
        google_account.save()

        return Response(
            {"message": "Google Calendar connected successfully!"}
        )
