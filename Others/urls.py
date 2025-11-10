from django.urls import path
from Accounts.views import *
from Others.views import *


urlpatterns = [
    path('get-otp/', GetOtp.as_view()),
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path('booking/', BookingAPIView.as_view()),  # POST to create
    path('booking/<int:booking_id>/', BookingAPIView.as_view()),  
    path("google/booking/", SocialAuthCallbackView.as_view()),
    path("boking/today/<int:company_id>", SocialAuthCallbackView.as_view()),
    path('stripe/', StripeListCreateView.as_view(), name='stripe-list-create'),
    path('stripe/update/', StripeUpdateView.as_view(), name='stripe-list-create'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
    path('log/', UserActivityLogView.as_view(), name='user-activity-log'),
    path('opening-hours/', OpeningHoursCreateView.as_view(), name='opening-hours-create'),
    path('opening-hours/<int:id>/', OpeningHoursUpdateDeleteView.as_view(), name='opening-hours-update-delete'),
    path('alerts/', UserAlertsView.as_view(), name='user-alerts'),
    path('alerts/<int:alert_id>/read/', MarkAlertReadView.as_view(), name='mark-alert-read'),

]