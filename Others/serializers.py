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

