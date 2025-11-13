# serializers.py
from rest_framework import serializers
from .models import *
from Socials.models import *
from django.core.exceptions import ObjectDoesNotExist

class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ['company', 'google_event_id', 'event_link', 'created_at']
  
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

class GoogleAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoogleAccount
        fields = '__all__'
        read_only_fields = ['company']