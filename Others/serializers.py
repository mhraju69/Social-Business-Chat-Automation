# serializers.py
from rest_framework import serializers
from .models import Booking

class BookingSerializer(serializers.ModelSerializer):
    end_time = serializers.DateTimeField(required=False)
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ['google_event_id', 'user']

