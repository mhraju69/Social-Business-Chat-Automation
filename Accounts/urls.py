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
    path('company/info/', CompanyInfoCreateView.as_view(), name='companyinfo-create'),
    path('company/info/<int:pk>/', CompanyInfoRetrieveUpdateView.as_view(), name='companyinfo-retrieve-update'),
    path('company/employee/', AddEmployeeView.as_view(), name='add-employee'),
    path('company/employee/check-permissions/', GetPermissionsView.as_view(), name='employee-list'),
    path('company/employee/update-permissions/', UpdatePermissionsView.as_view(), name='employee-list'),

]