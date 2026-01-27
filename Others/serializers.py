# serializers.py
import datetime
from rest_framework import serializers
from .models import *
from Socials.models import *
from django.core.exceptions import ObjectDoesNotExist

class BookingSerializer(serializers.ModelSerializer):
    start_time_local = serializers.SerializerMethodField()
    end_time_local = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ['company', 'google_event_id', 'event_link', 'created_at']

    def get_start_time_local(self, obj):
        if not obj.start_time:
            return None
        from Others.helper import utc_to_local
        timezone_str = obj.company.timezone if obj.company and obj.company.timezone else 'UTC'
        return utc_to_local(obj.start_time, timezone_str).strftime('%Y-%m-%d %I:%M %p')

    def get_end_time_local(self, obj):
        if not obj.end_time:
            return None
        from Others.helper import utc_to_local
        timezone_str = obj.company.timezone if obj.company and obj.company.timezone else 'UTC'
        return utc_to_local(obj.end_time, timezone_str).strftime('%Y-%m-%d %I:%M %p')
  
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
        read_only_fields = ['user']

class GoogleCalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoogleCalendar
        fields = '__all__'
        read_only_fields = ['company']


class SupportTicketSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    ticket_id = serializers.CharField(read_only=True)
    time_since_created = serializers.SerializerMethodField()
    class Meta:
        model = SupportTicket
        fields = '__all__'
        read_only_fields = ('user', 'ticket_id', 'subject', 'status', 'created_at', 'updated_at', 'time_since_created')
    
    def get_time_since_created(self, obj):
        delta = datetime.datetime.now(datetime.timezone.utc) - obj.created_at
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        if days > 0:
            return f"{days} days ago"
        elif hours > 0:
            return f"{hours} hours ago"
        elif minutes > 0:
            return f"{minutes} minutes ago"
        else:
            return "Just now"

class AITrainingFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = AITrainingFile
        fields = '__all__'
        read_only_fields = ['company', 'uploaded_at']