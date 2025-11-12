# serializers.py
from rest_framework import serializers
from .models import *
from Socials.models import *
from django.core.exceptions import ObjectDoesNotExist

# class BookingSerializer(serializers.ModelSerializer):
#     end_time = serializers.DateTimeField(required=False)
#     class Meta:
#         model = Booking
#         fields = '__all__'
#         read_only_fields = ['google_event_id', 'user']

# class DashboardSerializer(serializers.Serializer):
#     active_profiles = serializers.SerializerMethodField()
#     active_chats_count = serializers.SerializerMethodField()
#     today_messages_count = serializers.SerializerMethodField()
#     recent_messages = serializers.SerializerMethodField()
#     platform_breakdown = serializers.SerializerMethodField()

#     def get_active_profiles(self, obj):
#         """Return list of connected profiles for this user"""
#         user = self.context['request'].user
#         profiles = ChatProfile.objects.filter(user=user, bot_active=True)
#         return [
#             {
#                 "id": p.id,
#                 "platform": p.platform,
#                 "profile_id": p.profile_id,
#                 "created_at": p.created_at,
#             }
#             for p in profiles
#         ]

#     def get_active_chats_count(self, obj):
#         """Number of active chat rooms for this user"""
#         user = self.context['request'].user
#         rooms = ChatRoom.objects.filter(profile__user=user)
#         return rooms.count()

#     def get_today_messages_count(self, obj):
#         """Count of messages received today across all platforms"""
#         user = self.context['request'].user
#         today = timezone.now().date()
#         return ChatMessage.objects.filter(
#             room__profile__user=user,
#             type='incoming',
#             timestamp__date=today
#         ).count()

#     def get_recent_messages(self, obj):
#         """Last 10 messages (incoming or outgoing)"""
#         user = self.context['request'].user
#         messages = ChatMessage.objects.filter(
#             room__profile__user=user
#         ).order_by('-timestamp')[:10]

#         return [
#             {
#                 "platform": m.room.profile.platform,
#                 "client_id": m.room.client.client_id,
#                 "type": m.type,
#                 "text": m.text,
#                 "send_by_bot": m.send_by_bot,
#                 "timestamp": m.timestamp,
#             }
#             for m in messages
#         ]

#     def get_platform_breakdown(self, obj):
#         """Breakdown of messages count by platform"""
#         user = self.context['request'].user
#         data = {}
#         for platform, _ in ChatProfile.PLATFORM_CHOICES:
#             count = ChatMessage.objects.filter(
#                 room__profile__user=user,
#                 room__profile__platform=platform
#             ).count()
#             data[platform] = count
#         return data

# class AnalyticsSerializer(serializers.Serializer):
#     received_msg = serializers.SerializerMethodField()
#     sent_msg = serializers.SerializerMethodField()
    
#     # Breakdown by platform
#     whatsapp_received = serializers.SerializerMethodField()
#     whatsapp_sent = serializers.SerializerMethodField()
#     facebook_received = serializers.SerializerMethodField()
#     facebook_sent = serializers.SerializerMethodField()
#     instagram_received = serializers.SerializerMethodField()
#     instagram_sent = serializers.SerializerMethodField()
    
#     # Weekly breakdown (Saturday to Friday)
#     weekly_breakdown = serializers.SerializerMethodField()

#     def _get_user_profiles(self):
#         """Get all profiles associated with the user"""
#         user = self.context['request'].user        
#         profiles = {
#             'whatsapp': [],
#             'facebook': [],
#             'instagram': []
#         }
        
#         # Get WhatsApp profiles
#         try:
#             from Whatsapp.models import WhatsAppProfile
#             wa_profiles = WhatsAppProfile.objects.filter(user=user)
#             profiles['whatsapp'] = list(wa_profiles)
#         except Exception as e:
#             print(f"⚠️ [DEBUG] WhatsApp profile error: {e}")
        
#         # Get Facebook profiles
#         try:
#             from Facebook.models import FacebookProfile
#             fb_profiles = FacebookProfile.objects.filter(user=user)
#             profiles['facebook'] = list(fb_profiles)
#         except Exception as e:
#             print(f"⚠️ [DEBUG] Facebook profile error: {e}")
        
#         # Get Instagram profiles
#         try:
#             from Instagram.models import InstagramProfile
#             ig_profiles = InstagramProfile.objects.filter(user=user)
#             profiles['instagram'] = list(ig_profiles)
#         except Exception as e:
#             print(f"⚠️ [DEBUG] Instagram profile error: {e}")
        
#         return profiles

#     def get_whatsapp_received(self, obj):
#         profiles = self._get_user_profiles()
        
#         if not profiles['whatsapp']:
#             return 0
        
#         profile_ids = [p.id for p in profiles['whatsapp']]
        
#         count = WAIncoming.objects.filter(receiver_id__in=profile_ids).count()
        
#         return count

#     def get_whatsapp_sent(self, obj):
#         profiles = self._get_user_profiles()
        
#         if not profiles['whatsapp']:
#             return 0
        
#         profile_ids = [p.id for p in profiles['whatsapp']]
        
#         count = WAOutgoing.objects.filter(sender_id__in=profile_ids).count()
        
#         return count

#     def get_facebook_received(self, obj):
#         profiles = self._get_user_profiles()
        
#         if not profiles['facebook']:
#             return 0
        
#         profile_ids = [p.id for p in profiles['facebook']]
        
#         count = FBIncoming.objects.filter(receiver_id__in=profile_ids).count()
        
#         return count

#     def get_facebook_sent(self, obj):
#         profiles = self._get_user_profiles()
        
#         if not profiles['facebook']:
#             return 0
        
#         profile_ids = [p.id for p in profiles['facebook']]
        
#         count = FBOutgoing.objects.filter(sender_id__in=profile_ids).count()
        
#         return count

#     def get_instagram_received(self, obj):
#         profiles = self._get_user_profiles()
        
#         if not profiles['instagram']:
#             return 0
        
#         profile_ids = [p.id for p in profiles['instagram']]
        
#         count = IGIncoming.objects.filter(receiver_id__in=profile_ids).count()
        
#         return count

#     def get_instagram_sent(self, obj):
#         profiles = self._get_user_profiles()
        
#         if not profiles['instagram']:
#             return 0
        
#         profile_ids = [p.id for p in profiles['instagram']]
        
#         count = IGOutgoing.objects.filter(sender_id__in=profile_ids).count()
        
#         return count

#     def get_received_msg(self, obj):
        
#         wa_count = self.get_whatsapp_received(obj)
#         fb_count = self.get_facebook_received(obj)
#         ig_count = self.get_instagram_received(obj)
        
#         total = wa_count + fb_count + ig_count

#         return total

#     def get_sent_msg(self, obj):
        
#         wa_count = self.get_whatsapp_sent(obj)
#         fb_count = self.get_facebook_sent(obj)
#         ig_count = self.get_instagram_sent(obj)
        
#         total = wa_count + fb_count + ig_count
        
#         return total

#     def get_weekly_breakdown(self, obj):
#         """Get daily message breakdown for the current week (Saturday to Friday)"""
        
#         # Get timezone from context
#         tz_name = self.context.get('timezone', 'UTC')
#         tz = pytz.timezone(tz_name)
        
#         # Get current time in specified timezone
#         now = timezone.now().astimezone(tz)
        
#         # Find the most recent Saturday (start of week)
#         # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
#         days_since_saturday = (now.weekday() + 2) % 7
#         week_start = (now - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        
#         # Get all profiles
#         profiles = self._get_user_profiles()
        
#         # Prepare profile IDs
#         wa_profile_ids = [p.id for p in profiles['whatsapp']]
#         fb_profile_ids = [p.id for p in profiles['facebook']]
#         ig_profile_ids = [p.id for p in profiles['instagram']]
        
#         # Day names in order (Saturday to Friday)
#         day_names = ['Saturday', 'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        
#         weekly_data = []
        
#         for day_index in range(7):
#             day_start = week_start + timedelta(days=day_index)
#             day_end = day_start + timedelta(days=1)
            
#             # Convert to UTC for database queries
#             day_start_utc = day_start.astimezone(pytz.UTC)
#             day_end_utc = day_end.astimezone(pytz.UTC)
            
#             day_name = day_names[day_index]
            
#             # Count messages for this day across all platforms
#             total_received = 0
#             total_sent = 0
            
#             # WhatsApp
#             if wa_profile_ids:
#                 wa_received = WAIncoming.objects.filter(
#                     receiver_id__in=wa_profile_ids,
#                     timestamp__gte=day_start_utc,
#                     timestamp__lt=day_end_utc
#                 ).count()
#                 wa_sent = WAOutgoing.objects.filter(
#                     sender_id__in=wa_profile_ids,
#                     timestamp__gte=day_start_utc,
#                     timestamp__lt=day_end_utc
#                 ).count()
#                 total_received += wa_received
#                 total_sent += wa_sent
            
#             # Facebook
#             if fb_profile_ids:
#                 fb_received = FBIncoming.objects.filter(
#                     receiver_id__in=fb_profile_ids,
#                     timestamp__gte=day_start_utc,
#                     timestamp__lt=day_end_utc
#                 ).count()
#                 fb_sent = FBOutgoing.objects.filter(
#                     sender_id__in=fb_profile_ids,
#                     timestamp__gte=day_start_utc,
#                     timestamp__lt=day_end_utc
#                 ).count()
#                 total_received += fb_received
#                 total_sent += fb_sent

#             # Instagram
#             if ig_profile_ids:
#                 ig_received = IGIncoming.objects.filter(
#                     receiver_id__in=ig_profile_ids,
#                     timestamp__gte=day_start_utc,
#                     timestamp__lt=day_end_utc
#                 ).count()
#                 ig_sent = IGOutgoing.objects.filter(
#                     sender_id__in=ig_profile_ids,
#                     timestamp__gte=day_start_utc,
#                     timestamp__lt=day_end_utc
#                 ).count()
#                 total_received += ig_received
#                 total_sent += ig_sent

#             day_data = {
#                 'day': day_name,
#                 'date': day_start.date().isoformat(),
#                 'received': total_received,
#                 'sent': total_sent
#             }
#             weekly_data.append(day_data)
        
#         return weekly_data
    
class FieldChangeSerializer(serializers.Serializer):
    field = serializers.CharField()
    field_name = serializers.CharField()
    old_value = serializers.CharField()
    new_value = serializers.CharField()

class ActivityLogSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    activity_type = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField()
    timestamp = serializers.DateTimeField()
    model_name = serializers.CharField()
    # changes = FieldChangeSerializer(many=True)

class OpeningHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpeningHours
        fields = ['id','company', 'day', 'start', 'end']

class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = ["id", "title", "subtitle", "time", "type", "is_read"]

class KnowledgeBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeBase
        fields = '__all__'

