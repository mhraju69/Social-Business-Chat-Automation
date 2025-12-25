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
        # Try to parse User Agent and Client Info
        try:
            ua_string = request.META.get('HTTP_USER_AGENT', '')
            print(f"☘️☘️☘️☘️☘️☘️User Agent: {ua_string}")
            
            details = ua_string.split(",")
            device = f"{details[0].strip()} {details[1].strip()}"
            platform = details[2].strip()
            
        except :
            
            ua_string = request.META.get('HTTP_USER_AGENT', '')
            client_info_str = request.META.get('HTTP_X_CLIENT_INFO', '')
            
            device = "Unknown"
            platform = "Unknown"
            
            try:
                if client_info_str:
                    import json
                    client_data = json.loads(client_info_str)
                    p_platform = client_data.get('platform', '')
                    platform = p_platform if p_platform else "Unknown"
            except Exception as e:
                print(f"Error parsing HTTP_X_CLIENT_INFO: {e}")

            try:
                from user_agents import parse
                user_agent = parse(ua_string)
                
                d_family = user_agent.device.family
                if d_family == "Other":
                    d_family = "Desktop" # Or just Generic
                
                device = f"{d_family} / {user_agent.browser.family} {user_agent.browser.version_string}"
                platform = f"{user_agent.os.family} {user_agent.os.version_string}"
                
            except ImportError:
                pass
            except Exception as e:
                print(f"Error parsing User Agent with lib: {e}")
                try:
                    if "Windows" in ua_string:
                        platform = "Windows"
                        device = "Desktop"
                    elif "Android" in ua_string:
                        platform = "Android"
                        device = "Mobile"
                    elif "iPhone" in ua_string:
                        platform = "iOS"
                        device = "Mobile"
                except:
                    pass


        session = UserSession.objects.create(
            user=user,
            device=device,
            browser=platform,
            ip_address=get_client_ip(request),
            token=str(access['jti']),
            location=get_location(get_client_ip(request))
        )
        
        # Trigger AI Analysis Pre-warming
        try:
            # Check if user has a company attributed to them
            if hasattr(user, 'company'):
                from Ai.tasks import analyze_company_data_task
                # Run in background
                analyze_company_data_task.delay(user.company.id)
        except Exception as e:
            # logging.error(f"Failed to trigger analysis task: {e}")
            print(f"Failed to trigger analysis task: {e}")

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