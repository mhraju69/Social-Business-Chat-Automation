from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('enable-channels/', views.EnableChannelsView.as_view(), name='enable-channels'),
    path('disable-channels/', views.DisableChannelsView.as_view(), name='disable-channels'),
    path('user-channels/<int:user_id>/', views.UserChannelsView.as_view(), name='user-channels'),
    path('approve-channel/', views.ApproveChannelsView.as_view(), name='approve-channels'),
    path('reject-channel/', views.RejectChannelsView.as_view(), name='reject-channel'),

    path('companies/', views.CompanyListView.as_view(), name='company-list'),
    path('team-members/', views.AdminTeamMemberListView.as_view(), name='admin-team-member-list'),
    path('create-admin/', views.CreateAdminTeamMemberView.as_view(), name='create-admin'),
    path('company-overview/', views.CompanyOverviewListView.as_view(), name='company-overview'),

    path('performance-analytics/', views.PerformanceAnalyticsAPIView.as_view(), name='performance-analytics'),
    path('subscription-plan/', views.SubscriptionPlanListView.as_view(), name='subscription-plan-list'),
    path('subscription-plan/<int:id>/', views.SubscriptionPlanUpdateView.as_view(), name='subscription-plan-detail'),
    path('create-custom-plan/', views.CreateCustomPlanView.as_view(), name='create-custom-plan'),
    path('user-plan-requests/', views.UserPlanRequestListView.as_view(), name='user-plan-requests'),
    path('request-custom-plan/', views.RequestCustomPlanView.as_view(), name='request-custom-plan'),
    path('approve-user-plan/', views.ApproveUserPlanRequestView.as_view(), name='approve-user-plan'),
]