# serializers.py
from .models import *
from Others.models import *
from .utils import *
import requests,re
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    company = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'password', 'image', 'phone', 'role', 'dob', 'is_active', 'block', 'date_joined', 'company']
        read_only_fields = ['is_active', 'is_staff', 'is_superuser', 'date_joined','id','role', 'company']

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        send_otp(user.email, task="Account Registration")
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
    
    def get_company(self, obj):
        # Check if user is company owner
        company = Company.objects.filter(user=obj).first()
        if company:
            return CompanySerializer(company).data
            
        # Check if user is an employee
        employee = Employee.objects.filter(email=obj.email).first()
        if employee:
            return CompanySerializer(employee.company).data
            
        return None
    
    def get_status(self, obj):
        if obj.block:
            return "Blocked"
        elif not obj.is_active:
            return "Inactive"
        else:
            return "Active"

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")
        request = self.context.get('request')

        if not email or not password:
            raise serializers.ValidationError("Both email and password are required.")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid email or password.")
        if user.block:
            raise serializers.ValidationError("Your account has been temporarily blocked. Please contact support for more information.")
        if not user.check_password(password):
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("Account is not active. Please verify your email to activate your account.")
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        
        session = generate_session(request, user, access)

        employee = Employee.objects.filter(email__iexact=user.email).first()
        return {
            "user": UserSerializer(user).data,
            "role": employee.roles if employee else None,
            "session_id": session.id,
            "refresh": str(refresh),
            "access": str(access),  # Use the same access token, not a new one!
        }
    
class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        exclude = ["refresh_token","user","created_at","updated_at","stripe_customer_id","stripe_payment_method_id","stripe_connect_id"]

class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id','name', 'description', 'price', 'duration', 'start_time','end_time']
        read_only_fields = ['company']

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id','email','roles']

class UserSessionSerializer(serializers.ModelSerializer):
    is_current = serializers.BooleanField(read_only=True, default=False)
    
    class Meta:
        model = UserSession
        fields = ['id', 'device', 'browser', 'ip_address', 'location', 'last_active', 'is_active', 'is_current']