from rest_framework import serializers
from .models import *
from Socials.models import *
from django.core.exceptions import ObjectDoesNotExist

class StripeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StripeCredential
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

        return StripeCredential.objects.create(company=company, **validated_data)

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

class PlanValueSerializers(serializers.ModelSerializer):
    class Meta:
        model = PlanValue
        fields = ['value'] 

class PlanSerializers(serializers.ModelSerializer):
    values = PlanValueSerializers(source='plan_value', many=True)

    class Meta:
        model = Plan
        fields = ['name', 'duration', 'values']
