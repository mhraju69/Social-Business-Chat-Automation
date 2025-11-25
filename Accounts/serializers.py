# serializers.py
from rest_framework import serializers
from .models import *
# from Others.models import Company
from .utils import send_otp
from rest_framework_simplejwt.tokens import RefreshToken

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)
    company = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'password', 'image', 'phone', 'role', 'dob', 'is_active', 'is_staff', 'is_superuser', 'block', 'date_joined', 'company', 'status']
        read_only_fields = ['is_active', 'is_staff', 'is_superuser', 'date_joined','id','role', 'company', 'status']

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
        company = Company.objects.filter(user=obj).first()
        if company:
            return CompanySerializer(company).data
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
            otp = user.user_otp.first()
            if otp and otp.is_expired():
                send_otp(user.email, 'Login')
            raise serializers.ValidationError("Account is not active. Please verify your email to activate your account.")
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        return {
            "user": UserSerializer(user).data,
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }  
    
class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = "__all__"
        
        read_only_fields = ['user']

class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id','name', 'description', 'price', 'start_time','end_time']
        read_only_fields = ['company']

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id','email','roles']