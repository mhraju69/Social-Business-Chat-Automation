# views.py
from rest_framework import viewsets, permissions ,views, status 
from rest_framework.response import Response
from .utils import send_otp
from .models import User
from .serializers import UserSerializer

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

class GetOtp(views.APIView):
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
  