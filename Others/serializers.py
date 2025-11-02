# serializers.py
from rest_framework import serializers
from .models import *
from django.core.exceptions import ObjectDoesNotExist

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

from rest_framework import serializers
from Others.models import Booking, Company

class DashboardSerializer(serializers.Serializer):
    meetings_today_count = serializers.SerializerMethodField()
    meetings_today_list = serializers.SerializerMethodField()
    upcoming_meetings_count = serializers.SerializerMethodField()

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

