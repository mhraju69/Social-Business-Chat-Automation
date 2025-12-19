from rest_framework import serializers
from Accounts.models import User, Company
from admin_dashboard import models
import json


class SimpleUserSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    class Meta:
        model = User
        fields = ['id', 'name', 'role', 'email', 'company_name', 'is_active']

class  AdminCompanySerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    billing_contact = serializers.CharField(source='user.name', read_only=True)
    billing_email = serializers.EmailField(source='user.email', read_only=True)
    joining_date = serializers.DateTimeField(source='user.date_joined', read_only=True)
    total_paid = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)

    class Meta:
        model = Company
        fields = ['id', 'name', 'email', 'billing_contact', 'billing_email', 'joining_date', 'invoice', 'total_paid', 'is_active']

    def get_total_paid(self, obj):
        # return obj.invoices.filter(status='paid').aggregate(total=models.Sum('amount'))['total'] or 0
        return None
    
    def get_invoice(self, obj):
        # TODO change it later to get actual invoice data
        return (
            {
                'name': 'Sample Invoice',
                'url': 'https://example.com/invoice/0',
            }
        )