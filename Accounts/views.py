# views.py
from rest_framework import viewsets, permissions, status , generics
from rest_framework.response import Response
from .utils import *
from .models import User
from .serializers import *
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
from .permissions import VALID_ROLES
from django.core.files.base import ContentFile
from django.contrib.auth.hashers import make_password
from django.utils.text import slugify
import random
import string

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.AllowAny] 

    def get_queryset(self):
        queryset = super().get_queryset()
        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)
        return queryset

class GetOtp(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        task = request.data.get('task', '')
        if not email:
            return Response(
                {"error": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        res = send_otp(email, task)

        if res['success']:
            return Response({"success": True, "message": res['message']}, status=status.HTTP_200_OK)
        else:
            return Response({"error": res['message']}, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)        
        if serializer.is_valid():
            
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class VerifyOTP(APIView):
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        email = request.data.get('email')
        otp_code = request.data.get('otp')

        if not email or not otp_code:
            return Response(
                {"error": "Email and OTP code are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = verify_otp(email, otp_code)    

        if result['success']:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            return Response({
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }, status=status.HTTP_200_OK)
        else:
            # 403 for lock, 400 for invalid/expired
            status_code = status.HTTP_403_FORBIDDEN if "Too many attempts" in result['message'] else status.HTTP_400_BAD_REQUEST
            return Response({"success": False, "error": result['message']}, status=status_code)

class SocialAuthCallbackView(APIView):
    def post(self, request):
        access_token = request.data.get('access_token')
        
        if not access_token:
            return Response({'error': 'No access token provided'}, status=400)
        print(access_token)
        try:
            # Verify token
            token_info_response = requests.get(
                f'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={access_token}'
            )

            if token_info_response.status_code != 200:
                return Response({'error': 'Invalid access token'}, status=400)

            token_info = token_info_response.json()

            if 'error' in token_info:
                return Response({'error': token_info['error']}, status=400)

            # Get basic user info
            user_info_response = requests.get(
                'https://www.googleapis.com/oauth2/v2/userinfo',
                headers={'Authorization': f'Bearer {access_token}'}
            )

            user_data = user_info_response.json()
            profile_image_url = user_data.get("picture")
            email = user_data.get("email")
            name = user_data.get("name")

            #  Get DOB + Phone Number using People API
            date_of_birth = None
            phone_number = None

            people_api_url = "https://people.googleapis.com/v1/people/me?personFields=birthdays,phoneNumbers"
            people_response = requests.get(
                people_api_url,
                headers={'Authorization': f'Bearer {access_token}'}
            )

            
            try:
                people_json = people_response.json()
            except Exception as json_err:
                people_json = {}

            if people_response.status_code == 200 and isinstance(people_json, dict):

                # Birthday extraction
                birthdays = people_json.get("birthdays", [])
                if birthdays:
                    date_info = None
                    for b in birthdays:
                        d = b.get("date", {})
                        if "year" in d:
                            date_info = d
                            break
                    if not date_info:
                        date_info = birthdays[0].get("date", {})
                    year = date_info.get("year")
                    month = date_info.get("month")
                    day = date_info.get("day")
                    if year and month and day:
                        date_of_birth = f"{year}-{month:02d}-{day:02d}"
                    elif month and day:
                        date_of_birth = f"1900-{month:02d}-{day:02d}"

                # Phone number extraction
                phone_numbers = people_json.get("phoneNumbers", [])
                if phone_numbers:
                    primary_phone = next((p for p in phone_numbers if p.get("metadata", {}).get("primary")), phone_numbers[0])
                    phone_number = primary_phone.get("value")

            # Create or get user
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'name': name,
                    'is_active': True,
                    'password': make_password(None)
                }
            )

            # Save profile image if new user
            if created and profile_image_url:
                img_response = requests.get(profile_image_url)
                if img_response.status_code == 200:
                    file_name = f"{slugify(name)}-profile.jpg"
                    user.image.save(file_name, ContentFile(img_response.content), save=True)

            # Save DOB or Phone if fetched successfully
            if date_of_birth or phone_number:
                if not user.date_of_birth:  # only set if not already present
                    user.date_of_birth = date_of_birth
                    user.save(update_fields=["date_of_birth"])
                elif not user.phone:
                    user.phone = phone_number
                    user.save(update_fields=["phone"])

            # Check suspend flag
            if getattr(user, 'suspend', False):
                return Response(
                    {"error": "User account is disabled. Please contact support"},
                    status=403
                )

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            serializer = UserSerializer(user)

            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': serializer.data,
            })

        except Exception as e:
            return Response({'error': str(e)}, status=500)

class CompanyDetailUpdateView(generics.RetrieveUpdateAPIView):
    serializer_class = CompanySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """
        Return a single company instance for the logged-in user.
        If the user has multiple companies, take the first one.
        """
        # Use .first() to get a single instance from RelatedManager
        company = self.request.user.company
        if not company:
            # Optional: raise 404 if user has no company
            from rest_framework.exceptions import NotFound
            raise NotFound("No company found for this user.")
        return company
    
class ServiceListCreateView(generics.ListCreateAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Service.objects.filter(company=self.request.user.company)

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

class ServiceRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Only allow access to services belonging to the user’s company
        return Service.objects.filter(company=self.request.user.company)

class CompanyInfoCreateView(generics.ListCreateAPIView):
    serializer_class = CompanyInfoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)
    def get_queryset(self):
        return CompanyInfo.objects.filter(company=self.request.user.company.first())

class CompanyInfoRetrieveUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CompanyInfoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Get or raise error if company has no info yet
        company = self.request.user.company.first()
        try:
            return CompanyInfo.objects.get(company=company)
        except CompanyInfo.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("No company info found for this company.")
    
class AddEmployeeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        email = request.data.get('email')
        roles = request.data.get('roles', [])  
        
        if not email:
            return Response({'error': 'Email is required.'}, status=400)
        
        # Validate roles
        if not isinstance(roles, list):
            return Response({'error': 'Roles must be a list.'}, status=400)
        
        invalid_roles = [role for role in roles if role not in VALID_ROLES]
        if invalid_roles:
            return Response({
                'error': f'Invalid roles: {", ".join(invalid_roles)}. Valid roles are: {", ".join(VALID_ROLES)}'
            }, status=400)
        
        if not roles:
            return Response({'error': 'At least one role is required.'}, status=400)
        
        owner = request.user.email
        try:
            company = Company.objects.get(owner__email=owner)
        except Company.DoesNotExist:
            return Response({'error': 'Company not found.'}, status=404)
        
        if User.objects.filter(email=email).exists():
            return Response({'error': 'User with this email already exists.'}, status=400)
        
        # Create user
        password = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
        user = User.objects.create_user(
            email=email, 
            password=password,
            is_active=True,
            role='employee'
        )
        
        # Create employee with roles
        employee = Employee.objects.create(user=user, company=company, roles=roles)
        
        # Send invitation (assuming this function exists)
        send_employee_invitation(email, password, company.name,roles)
        
        return Response({
            'success': f'Employee added with email {email}',
            'password': password,  # Consider removing this in production
            'roles': roles,
            'permissions': employee.get_all_permissions(),
            'permissions_details': employee.get_permissions_with_details()
        }, status=201)
    
class GetPermissionsView(APIView):
    """Get permissions for the authenticated user"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        employee = Employee.objects.filter(user=user).first()

        if not employee:
            return Response({"detail": "Employee record not found."}, status=404)

        # roles is a JSONField (list of strings)
        user_roles = getattr(employee, 'roles', [])
        if not isinstance(user_roles, list):
            user_roles = [user_roles]

        if not user_roles:
            return Response({"detail": "User has no assigned roles."}, status=404)

        combined_permissions = {}

        # Merge permissions for all roles
        for role in user_roles:
            role_perms = PERMISSIONS_MATRIX.get(role, {})
            for perm, has_access in role_perms.items():
                # If any role grants access, mark it as True
                if perm not in combined_permissions:
                    combined_permissions[perm] = has_access
                else:
                    combined_permissions[perm] = combined_permissions[perm] or has_access

        # Map internal names to readable ones
        formatted_permissions = {
            PERMISSION_NAMES.get(perm, perm): access
            for perm, access in combined_permissions.items()
        }

        return Response({
            "user": getattr(user, 'email', str(user)),
            "roles": user_roles,
            "permissions": formatted_permissions
        })