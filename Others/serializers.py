# serializers.py
from rest_framework import serializers
from .models import *
from django.core.exceptions import ObjectDoesNotExist
from Whatsapp.models import Incoming as WAIncoming, Outgoing as WAOutgoing
from Facebook.models import  Incoming as FBIncoming, Outgoing as FBOutgoing
from Instagram.models import Incoming as IGIncoming, Outgoing as IGOutgoing

class BookingSerializer(serializers.ModelSerializer):
    end_time = serializers.DateTimeField(required=False)
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ['google_event_id', 'user']

class StripeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stripe
        fields = ['id', 'api_key', 'publishable_key', 'webhook_secret']

    def create(self, validated_data):
        user = self.context['request'].user

        # Get the first company associated with user
        company_qs = getattr(user, 'company', None)
        if company_qs is None:
            raise serializers.ValidationError("User has no associated company.")

        # If it's a manager, get the first company
        if hasattr(company_qs, 'first'):
            company = company_qs.first()
        else:
            company = company_qs  # already an instance

        if not company:
            raise serializers.ValidationError("User has no associated company.")

        # Check if Stripe already exists for this company
        try:
            _ = company.stripe  # OneToOneField reverse access
            raise serializers.ValidationError("Stripe configuration already exists for this company.")
        except ObjectDoesNotExist:
            pass

        return Stripe.objects.create(company=company, **validated_data)

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id',
            'reason',
            'amount',
            'transaction_id',
            'payment_date',
        ]

class DashboardSerializer(serializers.Serializer):
    meetings_today_count = serializers.SerializerMethodField()
    meetings_today_list = serializers.SerializerMethodField()
    upcoming_meetings_count = serializers.SerializerMethodField()
    payments_today_total = serializers.SerializerMethodField()
    payments_today_list = serializers.SerializerMethodField()

    def _get_company(self):
        """Get company associated with the user"""
        user = self.context['request'].user
        
        # Handle different user-company relationship patterns
        company_qs = getattr(user, 'company', None)
        
        if company_qs is None:
            return None
            
        # If it's a RelatedManager or QuerySet
        if hasattr(company_qs, 'first'):
            company = company_qs.first()
        else:
            # If it's a direct foreign key
            company = company_qs
            
        return company

    def _get_timezone(self, company):
        """Get timezone from query params or company settings"""
        # First check query parameters
        tz_param = self.context.get('timezone')
        if tz_param:
            return tz_param
        
        # Fall back to company timezone
        tz_name = getattr(company, 'timezone', 'UTC') if company else 'UTC'
        return tz_name

    def get_meetings_today_count(self, obj):
        company = self._get_company()
        if not company:
            return 0

        tz_name = self._get_timezone(company)
        qs = Booking.meetings_today(company=company, timezone_name=tz_name)
        count = qs.count()
        return count

    def get_meetings_today_list(self, obj):
        company = self._get_company()
        if not company:
            return []
        
        tz_name = self._get_timezone(company)
        qs = Booking.meetings_today(company=company, timezone_name=tz_name).order_by('start_time')
        count = qs.count()

        return BookingSerializer(qs, many=True).data

    def get_upcoming_meetings_count(self, obj):
        company = self._get_company()
        if not company:
            return 0

        tz_name = self._get_timezone(company)
        qs = Booking.new_meetings(company=company, timezone_name=tz_name)
        count = qs.count()
        return count
    
    def get_payments_today_list(self, obj):
        company = self._get_company()
        if not company:
            return []
        
        tz_name = self._get_timezone(company)
        qs = Payment.payments_today(company=company, timezone_name=tz_name).order_by('-payment_date')
        count = qs.count()
        
        if count > 0:
            for payment in qs:
                print(f"  💵 {payment.reason}: ${payment.amount} - TXN: {payment.transaction_id}")
        
        return PaymentSerializer(qs, many=True).data

    def get_payments_today_total(self, obj):
        company = self._get_company()
        if not company:
            return 0
        
        tz_name = self._get_timezone(company)
        qs = Payment.payments_today(company=company, timezone_name=tz_name)
        
        from django.db.models import Sum
        total = qs.aggregate(total=Sum('amount'))['total'] or 0
                
        return float(total)

class AnalyticsSerializer(serializers.Serializer):
    received_msg = serializers.SerializerMethodField()
    sent_msg = serializers.SerializerMethodField()
    
    # Breakdown by platform
    whatsapp_received = serializers.SerializerMethodField()
    whatsapp_sent = serializers.SerializerMethodField()
    facebook_received = serializers.SerializerMethodField()
    facebook_sent = serializers.SerializerMethodField()
    instagram_received = serializers.SerializerMethodField()
    instagram_sent = serializers.SerializerMethodField()
    
    # Weekly breakdown (Saturday to Friday)
    weekly_breakdown = serializers.SerializerMethodField()

    def _get_user_profiles(self):
        """Get all profiles associated with the user"""
        user = self.context['request'].user        
        profiles = {
            'whatsapp': [],
            'facebook': [],
            'instagram': []
        }
        
        # Get WhatsApp profiles
        try:
            from Whatsapp.models import WhatsAppProfile
            wa_profiles = WhatsAppProfile.objects.filter(user=user)
            profiles['whatsapp'] = list(wa_profiles)
        except Exception as e:
            print(f"⚠️ [DEBUG] WhatsApp profile error: {e}")
        
        # Get Facebook profiles
        try:
            from Facebook.models import FacebookProfile
            fb_profiles = FacebookProfile.objects.filter(user=user)
            profiles['facebook'] = list(fb_profiles)
        except Exception as e:
            print(f"⚠️ [DEBUG] Facebook profile error: {e}")
        
        # Get Instagram profiles
        try:
            from Instagram.models import InstagramProfile
            ig_profiles = InstagramProfile.objects.filter(user=user)
            profiles['instagram'] = list(ig_profiles)
        except Exception as e:
            print(f"⚠️ [DEBUG] Instagram profile error: {e}")
        
        return profiles

    def get_whatsapp_received(self, obj):
        profiles = self._get_user_profiles()
        
        if not profiles['whatsapp']:
            return 0
        
        profile_ids = [p.id for p in profiles['whatsapp']]
        
        count = WAIncoming.objects.filter(receiver_id__in=profile_ids).count()
        
        return count

    def get_whatsapp_sent(self, obj):
        profiles = self._get_user_profiles()
        
        if not profiles['whatsapp']:
            return 0
        
        profile_ids = [p.id for p in profiles['whatsapp']]
        
        count = WAOutgoing.objects.filter(sender_id__in=profile_ids).count()
        
        return count

    def get_facebook_received(self, obj):
        profiles = self._get_user_profiles()
        
        if not profiles['facebook']:
            return 0
        
        profile_ids = [p.id for p in profiles['facebook']]
        
        count = FBIncoming.objects.filter(receiver_id__in=profile_ids).count()
        
        return count

    def get_facebook_sent(self, obj):
        profiles = self._get_user_profiles()
        
        if not profiles['facebook']:
            return 0
        
        profile_ids = [p.id for p in profiles['facebook']]
        
        count = FBOutgoing.objects.filter(sender_id__in=profile_ids).count()
        
        return count

    def get_instagram_received(self, obj):
        profiles = self._get_user_profiles()
        
        if not profiles['instagram']:
            return 0
        
        profile_ids = [p.id for p in profiles['instagram']]
        
        count = IGIncoming.objects.filter(receiver_id__in=profile_ids).count()
        
        return count

    def get_instagram_sent(self, obj):
        profiles = self._get_user_profiles()
        
        if not profiles['instagram']:
            return 0
        
        profile_ids = [p.id for p in profiles['instagram']]
        
        count = IGOutgoing.objects.filter(sender_id__in=profile_ids).count()
        
        return count

    def get_received_msg(self, obj):
        
        wa_count = self.get_whatsapp_received(obj)
        fb_count = self.get_facebook_received(obj)
        ig_count = self.get_instagram_received(obj)
        
        total = wa_count + fb_count + ig_count

        return total

    def get_sent_msg(self, obj):
        
        wa_count = self.get_whatsapp_sent(obj)
        fb_count = self.get_facebook_sent(obj)
        ig_count = self.get_instagram_sent(obj)
        
        total = wa_count + fb_count + ig_count
        
        return total

    def get_weekly_breakdown(self, obj):
        """Get daily message breakdown for the current week (Saturday to Friday)"""
        
        # Get timezone from context
        tz_name = self.context.get('timezone', 'UTC')
        tz = pytz.timezone(tz_name)
        
        # Get current time in specified timezone
        now = timezone.now().astimezone(tz)
        
        # Find the most recent Saturday (start of week)
        # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        days_since_saturday = (now.weekday() + 2) % 7
        week_start = (now - timedelta(days=days_since_saturday)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        
        # Get all profiles
        profiles = self._get_user_profiles()
        
        # Prepare profile IDs
        wa_profile_ids = [p.id for p in profiles['whatsapp']]
        fb_profile_ids = [p.id for p in profiles['facebook']]
        ig_profile_ids = [p.id for p in profiles['instagram']]
        
        # Day names in order (Saturday to Friday)
        day_names = ['Saturday', 'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        
        weekly_data = []
        
        for day_index in range(7):
            day_start = week_start + timedelta(days=day_index)
            day_end = day_start + timedelta(days=1)
            
            # Convert to UTC for database queries
            day_start_utc = day_start.astimezone(pytz.UTC)
            day_end_utc = day_end.astimezone(pytz.UTC)
            
            day_name = day_names[day_index]
            
            # Count messages for this day across all platforms
            total_received = 0
            total_sent = 0
            
            # WhatsApp
            if wa_profile_ids:
                wa_received = WAIncoming.objects.filter(
                    receiver_id__in=wa_profile_ids,
                    timestamp__gte=day_start_utc,
                    timestamp__lt=day_end_utc
                ).count()
                wa_sent = WAOutgoing.objects.filter(
                    sender_id__in=wa_profile_ids,
                    timestamp__gte=day_start_utc,
                    timestamp__lt=day_end_utc
                ).count()
                total_received += wa_received
                total_sent += wa_sent
            
            # Facebook
            if fb_profile_ids:
                fb_received = FBIncoming.objects.filter(
                    receiver_id__in=fb_profile_ids,
                    timestamp__gte=day_start_utc,
                    timestamp__lt=day_end_utc
                ).count()
                fb_sent = FBOutgoing.objects.filter(
                    sender_id__in=fb_profile_ids,
                    timestamp__gte=day_start_utc,
                    timestamp__lt=day_end_utc
                ).count()
                total_received += fb_received
                total_sent += fb_sent

            # Instagram
            if ig_profile_ids:
                ig_received = IGIncoming.objects.filter(
                    receiver_id__in=ig_profile_ids,
                    timestamp__gte=day_start_utc,
                    timestamp__lt=day_end_utc
                ).count()
                ig_sent = IGOutgoing.objects.filter(
                    sender_id__in=ig_profile_ids,
                    timestamp__gte=day_start_utc,
                    timestamp__lt=day_end_utc
                ).count()
                total_received += ig_received
                total_sent += ig_sent

            day_data = {
                'day': day_name,
                'date': day_start.date().isoformat(),
                'received': total_received,
                'sent': total_sent
            }
            weekly_data.append(day_data)
        
        return weekly_data
    
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
