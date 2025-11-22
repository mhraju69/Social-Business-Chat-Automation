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
        fields = '__all__'

class PlanValueSerializers(serializers.ModelSerializer):
    class Meta:
        model = PlanValue
        fields = ['value'] 

class PlanSerializers(serializers.ModelSerializer):
    values = PlanValueSerializers(source='plan_value', many=True)

    class Meta:
        model = Plan
        fields = ['name', 'duration', 'values']
        
class SubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.get_name_display', read_only=True)
    plan_duration = serializers.CharField(source='plan.get_duration_display', read_only=True)
    plan_price = serializers.DecimalField(source='plan.price', max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = Subscriptions
        fields = ['id', 'company', 'plan', 'plan_name', 'plan_duration', 'plan_price', 'start', 'end', 'active']
        read_only_fields = ['company', 'start', 'end', 'active']

    def update(self, instance, validated_data):
        # Allow only 'plan' to be updated for existing subscriptions
        if 'plan' in validated_data:
            instance.plan = validated_data.get('plan', instance.plan)
            instance.save()
        return instance