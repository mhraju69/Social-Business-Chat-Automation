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
]