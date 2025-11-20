# views.py
from rest_framework import viewsets, permissions, status , generics, decorators
from rest_framework.response import Response
from .utils import *
from .models import User
from .serializers import *
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests
from .permissions import *
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
    
    @decorators.action(detail=False, methods=['patch'], url_path='me')
    def update_me(self, request):
        user = request.user
        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

class ResetPassword(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        email = request.data.get('email')
        new_password = request.data.get('new_password')

        if not email or not new_password :
            return Response(
                {"error": "Email and new password are required."},
                status=400
            )
        
        elif request.user.email != email :
            return Response(
                {"error": "You can only reset your own password."},
                status=403)
        
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            return Response({"success": True, "message": "Password reset successfully"}, status=200)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
        
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
    
class AddEmployeeView(APIView):
    permission_classes = [permissions.IsAuthenticated,IsOwner,IsEmployeeAndCanManageUsers]

    def get(self, request):
        owner = request.user.email
        try:
            company = Company.objects.get(owner__email=owner)
        except Company.DoesNotExist:
            return Response({'error': 'Company not found.'}, status=404)
        
        employees = Employee.objects.filter(company=company)
        employee_data = []
        for emp in employees:
            employee_data.append({
                'email': emp.user.email,
                'roles': emp.roles,
                'permissions': emp.get_all_permissions(),
                'permissions_details': emp.get_permissions_with_details()
            })
        
        return Response({'employees': employee_data}, status=200)
    
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
    permission_classes = [permissions.IsAuthenticated,IsOwner]

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

class UpdatePermissionsView(APIView):
    """Update roles (permissions) for an employee - Admin only"""
    permission_classes = [permissions.IsAuthenticated,IsOwner]

    def post(self, request):
        # Extract target employee email and new roles
        email = request.data.get("email")
        new_roles = request.data.get("roles")

        if not email or not new_roles:
            return Response(
                {"detail": "Both 'email' and 'roles' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not isinstance(new_roles, list):
            return Response(
                {"detail": "'roles' must be a list of role names."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the requesting user (from token)
        current_user = request.user

        # Find the target employee
        target_employee = Employee.objects.filter(user__email=email).first()
        if not target_employee:
            return Response(
                {"detail": f"No employee found with email {email}."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update roles (assuming roles is a JSONField)
        target_employee.roles = new_roles
        target_employee.save()

        return Response(
            {
                "detail": f"Roles updated successfully for {email}.",
                "roles": target_employee.roles
            },
            status=status.HTTP_200_OK
        )

class SocialAuthCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
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

            people_api_url = "https://people.googleapis.com/v1/people/me?personFields=birthdays,phoneNumbers"
            people_response = requests.get(
                people_api_url,
                headers={'Authorization': f'Bearer {access_token}'}
            )

            
            try:
                people_json = people_response.json()
            except Exception as json_err:
                people_json = {}

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

            # Check suspend flag
            if getattr(user, 'block', False):
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