from django.urls import path,include
from .views import *
from rest_framework.routers import DefaultRouter
from Accounts.views import *
from Others.views import *


router = DefaultRouter()
router.register(r'users', UserViewSet)
urlpatterns = [
    path('', include(router.urls)),  
    path('get-otp/', GetOtp.as_view()),
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path("google/callback/", SocialAuthCallbackView.as_view()),
    path('company/', CompanyDetailUpdateView.as_view(), name='company-detail-update'),
    path('company/service/', ServiceListCreateView.as_view(), name='service-list-create'),
    path('company/service/<int:pk>/', ServiceRetrieveUpdateDestroyView.as_view(), name='service-detail'),
    path('company/employee/', AddEmployeeView.as_view(), name='add-employee'),
    path('company/employee/check-permissions/<int:employee_id>/', GetPermissionsView.as_view(), name='employee-list'),
    path('company/employee/update-permissions/<int:employee_id>/', UpdatePermissionsView.as_view(), name='employee-list'),
    path('google/login/',SocialAuthCallbackView.as_view()),
    path('reset-password/',ResetPassword.as_view()),
    path('logout-session/<int:session_id>/', LogoutSessionView.as_view()),
    path('logout-all-sessions/', LogoutAllSessionsView.as_view()),
    path('sessions/', ActiveSessionsView.as_view()),
    path('me/', UserDataView.as_view()),
]