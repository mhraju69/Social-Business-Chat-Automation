from django.urls import path,include
from Accounts.views import *
from Others.views import *
from rest_framework.routers import DefaultRouter
router = DefaultRouter()
router.register(r'tickets', SupportTicketViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('get-otp/', GetOtp.as_view()),
    path('login/', LoginView.as_view(), name='login'),
    path('verify-otp/',VerifyOTP.as_view(), name="verify_otp"),
    path('dashboard/', DashboardView.as_view()),    
    path('booking/', ClientBookingView.as_view()),  
    path("google/calendar/connect/", ConnectGoogleCalendarView.as_view()),
    path("google/calendar/callback/", GoogleOAuthCallbackView.as_view()),
    path('analytics/', AnalyticsView.as_view(), name='analytics'),
    path('log/', UserActivityLogView.as_view(), name='user-activity-log'),
    path('opening-hours/', OpeningHoursCreateView.as_view(), name='opening-hours-create'),
    path('opening-hours/<int:id>/', OpeningHoursUpdateDeleteView.as_view(), name='opening-hours-update-delete'),
    path('alerts/', UserAlertsView.as_view(), name='user-alerts'),
    path('alerts/<int:alert_id>/read/', MarkAlertReadView.as_view(), name='mark-alert-read'),
    path('knowledge-base/', KnowledgeBaseListCreateView.as_view(), name='knowledgebase-list-create'),
    path('knowledge-base/<int:id>/', KnowledgeBaseRetrieveUpdateDestroyView.as_view(), name='knowledgebase-detail'),
    path('finance-data/', FinanceDataView.as_view(), name='knowledgebase-list-create'),
    path('bookings/monthly/', MonthlyBookingsView.as_view(), name='monthly-bookings'),
    path('bookings/days/', BookingDaysView.as_view(), name='booking-days'),
    path('ai-training-files/', AITrainingFileBulkUploadView.as_view(), name='ai-training-files'),
    path('validate-token/', ValidateTokenView.as_view(), name='validate-token'),
    path('knowledge-category/', KnowledgeCategoryView.as_view()),
    path('sync-knowledge/', SyncKnowledgeView.as_view()),
    path('payment-success/', PaymentSuccessView.as_view(), name='payment-success'),
]