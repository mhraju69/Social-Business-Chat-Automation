import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework import generics
from Accounts.models import User, Company
from Finance import models
from Socials.models import ChatProfile, ChatMessage
from Finance.models import Payment
from Others.models import SupportTicket
from django.db.models import Sum, Q
from Others.serializers import SupportTicketSerializer
from Accounts.serializers import CompanySerializer, UserSerializer
from rest_framework.filters import OrderingFilter, SearchFilter
from Accounts.permissions import IsAdmin
from drf_spectacular.utils import extend_schema_view, extend_schema, inline_serializer
from rest_framework import serializers
from .serializers import AdminTeamMemberSerializer, ChannelOverviewSerializer, SimpleUserSerializer, AdminCompanySerializer
from rest_framework.pagination import PageNumberPagination
from datetime import timedelta
from .utils import get_today
class DashboardView(generics.GenericAPIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Get admin dashboard statistics",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "totalUsers": {"type": "integer"},
                    "activeIntegrations": {"type": "integer"},
                    "newCompanies": {"type": "integer"},
                    "addIncome": {"type": "number"},
                    "netProfit": {"type": "number"},
                    "costs": {"type": "number"},
                    "openTickets": {
                        "type": "array",
                        "items": {
                            "type": "object"
                        },
                    },
                    "chartData": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "month": {"type": "string"},
                                "users": {"type": "integer"},
                                "revenue": {"type": "number"},
                                "cost": {"type": "number"},
                            },
                        },
                    },
                },
            }
        }   
    )
    def get(self, request, *args, **kwargs):
        total_user = User.objects.count()
        active_integrations = ChatProfile.objects.filter(bot_active=True).count()
        new_companies = Company.objects.filter(created_at__gte=datetime.date.today()).count()
        earnings_today = Payment.objects.filter(created_at__date=datetime.date.today()).aggregate(total_earnings=models.Sum('amount'))['total_earnings'] or 0
        net_profit_this_month = Payment.objects.filter(
            created_at__year=datetime.date.today().year,
            created_at__month=datetime.date.today().month
        ).aggregate(total_earnings=models.Sum('amount'))['total_earnings'] or 0

        tickets = SupportTicket.objects.filter(
            Q(status='open') | Q(status='in_progress')
        )[:5]

        # Show chart data for last 6 months
        chart_data = []
        today = datetime.date.today()
        for i in range(5, -1, -1):
            month_date = today - datetime.timedelta(days=i*30)
            month_name = month_date.strftime('%B')
            month = month_date.month
            year = month_date.year
            month_users = User.objects.filter(date_joined__month=month, date_joined__year=year).count()
            month_revenue = Payment.objects.filter(created_at__month=month, created_at__year=year).aggregate(total_revenue=Sum('amount'))['total_revenue'] or 0
            month_cost = 0  # Placeholder for cost calculation
            chart_data.append({
                'month': month_name,
                'users': month_users,
                'revenue': month_revenue,
                'cost': month_cost
            })
        
        response_data = {
            "totalUsers": total_user,
            "activeIntegrations": active_integrations,
            "newCompanies": new_companies,
            "addIncome": earnings_today,
            "netProfit": net_profit_this_month,
            "costs": 0,
            "openTickets": SupportTicketSerializer(tickets, many=True).data,
            "chartData": chart_data

        }
        return Response(response_data)

class UserListPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

@extend_schema_view(
    get=extend_schema(
        tags=["Admin Dashboard"],
        summary="Get list of users with search and ordering",
    )
)
class UserListView(generics.ListAPIView):
    queryset = User.objects.filter(role__in=['user', 'employee'], company__name__isnull=False).prefetch_related('company')
    serializer_class = SimpleUserSerializer
    permission_classes = [IsAdmin]
    pagination_class = UserListPagination

    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'email', 'phone']
    ordering_fields = ['date_joined', 'name', 'email']

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            if is_active.lower() == 'true':
                queryset = queryset.filter(is_active=True)
            elif is_active.lower() == 'false':
                queryset = queryset.filter(is_active=False)
        return queryset


class EnableChannelsView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Enable channels for all users",
        request=inline_serializer(
            name="EnableChannelsRequest",
            fields={
                "channel_name": serializers.CharField()
            }
        ),
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        }
    )
    def post(self, request, *args, **kwargs):
        channel_name = request.data.get("channel_name")

        if channel_name:
            if channel_name not in dict(ChatProfile.PLATFORM_CHOICES).keys():
                return Response({"error": f"Invalid channel name: {channel_name}. Options are: {', '.join(dict(ChatProfile.PLATFORM_CHOICES).keys())}"}, status=400)
            profiles = ChatProfile.objects.filter(platform=channel_name)

            profiles.update(bot_active=True)
            return Response({"status": f"All {channel_name} channels enabled for all users."})

        return Response({"error": "Channel name not provided."}, status=400)

class DisableChannelsView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Disable channels for all users",
        request=inline_serializer(
            name="DisableChannelsRequest",
            fields={
                "channel_name": serializers.CharField()
            }
        ),
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
            404: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        }
    )
    def post(self, request, *args, **kwargs):
        channel_name = request.data.get("channel_name")

        if channel_name:
            profiles = ChatProfile.objects.filter(platform=channel_name)
            if not profiles.exists():
                return Response({"error": f"No channels found for {channel_name}."}, status=404)
            
            profiles.update(bot_active=False)
            return Response({"status": f"All {channel_name} channels disabled for all users."})

        return Response({"error": "Channel name not provided."}, status=400)
    
class ApproveChannelsView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Approve a chat profile",
        request=inline_serializer(
            name="ApproveChannelsRequest",
            fields={
                "chat_profile_id": serializers.IntegerField()
            }
        ),
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
            404: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        }
    )
    def post(self, request, *args, **kwargs):
        chat_profile_id = request.data.get("chat_profile_id")

        if chat_profile_id:
            try:
                profile = ChatProfile.objects.get(id=chat_profile_id)
                profile.is_approved = True
                profile.save()
                return Response({"status": f"Chat profile {chat_profile_id} approved."})
            
            except ChatProfile.DoesNotExist:
                return Response({"error": f"Chat profile with id {chat_profile_id} does not exist."}, status=404)

        return Response({"error": "Chat profile id not provided."}, status=400)
    
class RejectChannelsView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Reject a chat profile",
        request=inline_serializer(
            name="RejectChannelsRequest",
            fields={
                "chat_profile_id": serializers.IntegerField()
            }
        ),
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                },
            },
            400: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
            404: {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        }
    )
    def post(self, request, *args, **kwargs):
        chat_profile_id = request.data.get("chat_profile_id")

        if chat_profile_id:
            try:
                profile = ChatProfile.objects.get(id=chat_profile_id)
                profile.delete()
                return Response({"status": f"Chat profile {chat_profile_id} rejected."})
            
            except ChatProfile.DoesNotExist:
                return Response({"error": f"Chat profile with id {chat_profile_id} does not exist."}, status=404)

        return Response({"error": "Chat profile id not provided."}, status=400)
    
class UserChannelsView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Get all chat profiles for a specific user",
        responses=inline_serializer(
            name="UserChannelsResponse",
            fields={
                "user_id": serializers.IntegerField(),
                "channels": serializers.ListField(
                    child=serializers.DictField()
                )
            }
        ),
    )
    def get(self, request, user_id, *args, **kwargs):
        try:
            user = User.objects.get(id=user_id)
            profiles = ChatProfile.objects.filter(user=user)
            data = []
            for profile in profiles:
                data.append({
                    "id": profile.id,
                    "platform": profile.platform,
                    "profile_id": profile.profile_id,
                    "bot_active": profile.bot_active,
                    "is_approved": profile.is_approved,
                    "created_at": profile.created_at,
                })
            return Response({"user_id": user_id, "channels": data})
        
        except User.DoesNotExist:
            return Response({"error": f"User with id {user_id} does not exist."}, status=404)

class CompanyListPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

@extend_schema_view(
    get=extend_schema(
        tags=["Admin Dashboard"],
        summary="Get list of companies with search and ordering",
    )
)
class CompanyListView(generics.ListAPIView):
    queryset = Company.objects.all()
    serializer_class = AdminCompanySerializer
    permission_classes = [IsAdmin]
    pagination_class = CompanyListPagination

    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['created_at', 'name']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            if is_active.lower() == 'true':
                queryset = queryset.filter(user__is_active=True)
            elif is_active.lower() == 'false':
                queryset = queryset.filter(user__is_active=False)
        queryset = queryset.exclude(name='').order_by('name')
        return queryset

class PerformanceAnalyticsAPIView(generics.GenericAPIView):
    permission_classes = [IsAdmin]
    

    @extend_schema(
        tags=["Admin Dashboard"],
        summary="Get performance analytics data",
        responses=inline_serializer(
            name="PerformanceAnalyticsResponse",
            fields={
                "total_message_sent": serializers.DictField(),
                "total_message_received": serializers.DictField(),
                "monthly_revenue": serializers.DictField(),
                "total_revenue": serializers.FloatField(),
                "time_scope": serializers.CharField(),
            }
        ),
    )
    def get(self, request, *args, **kwargs):

        time_scope = request.query_params.get('time_scope', 'last_month') # today / last_month / last_year

        today_start, today_end = get_today()

        if time_scope == 'today':
            data_date_start_date = today_start
        elif time_scope == 'last_month':
            data_date_start_date = today_start - timedelta(days=30)
        elif time_scope == 'last_year':
            data_date_start_date = today_start - timedelta(days=365)
        else:
            return Response({"error": "Invalid time_scope parameter. Use 'today', 'last_month', or 'last_year'."}, status=400)

        total_message_sent = ChatMessage.objects.filter(type='outgoing', created_at__gte=data_date_start_date).count()
        total_message_received = ChatMessage.objects.filter(type='incoming', created_at__gte=data_date_start_date).count()
        monthly_revenue = Payment.objects.filter(created_at__gte=data_date_start_date).aggregate(total=Sum('amount'))['total'] or 0
        total_revenue = Payment.objects.aggregate(total=Sum('amount'))['total'] or 0

        if time_scope == 'today':
            previous_date = today_start - timedelta(days=1)
        elif time_scope == 'last_month':
            previous_date = today_start - timedelta(days=60)
        elif time_scope == 'last_year':
            previous_date = today_start - timedelta(days=730)

        # previous month data
        message_sent_prev = ChatMessage.objects.filter(type='outgoing', created_at__gte=previous_date, created_at__lt=data_date_start_date).count()
        message_received_prev = ChatMessage.objects.filter(type='incoming', created_at__gte=previous_date, created_at__lt=data_date_start_date).count()
        monthly_revenue_prev = Payment.objects.filter(created_at__gte=previous_date, created_at__lt=data_date_start_date).aggregate(total=Sum('amount'))['total'] or 0

        # difference percentage calculation
        message_sent_diff = ((total_message_sent - message_sent_prev) / message_sent_prev * 100) if message_sent_prev > 0 else 0
        message_received_diff = ((total_message_received - message_received_prev) / message_received_prev * 100) if message_received_prev > 0 else 0
        monthly_revenue_diff = ((monthly_revenue - monthly_revenue_prev) / monthly_revenue_prev * 100) if monthly_revenue_prev > 0 else 0


        data = {
            "total_message_sent": {
                "current": total_message_sent,
                "previous": message_sent_diff
            },
            "total_message_received": {
                "current": total_message_received,
                "previous": message_received_diff
            },
            "monthly_revenue": {
                "current": monthly_revenue,
                "previous": monthly_revenue_diff
            },
            "total_revenue": total_revenue,
            "time_scope": time_scope,
        }
        return Response(data)

@extend_schema_view(
    get=extend_schema(
        tags=["Admin Dashboard"],
        summary="Get list of admin and employee team members with search and ordering",
    )
)
class AdminTeamMemberListView(generics.ListAPIView):
    queryset = User.objects.filter(role__in=['admin'])
    serializer_class = AdminTeamMemberSerializer
    permission_classes = [IsAdmin]
    pagination_class = UserListPagination

    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'email', 'phone']
    ordering_fields = ['date_joined', 'name', 'email']

class CompanyOverviewPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100
@extend_schema_view(
    get=extend_schema(
        tags=["Admin Dashboard"],
        summary="Get channel overview for companies with search and ordering",
    )
)
class CompanyOverviewListView(generics.GenericAPIView):
    permission_classes = [IsAdmin]

    def get(self, request, *args, **kwargs):
        total_channels= ChatProfile.objects.count(),
        online_channels = ChatProfile.objects.filter(bot_active=True).count(),
        offline_channels = ChatProfile.objects.filter(bot_active=False).count(),
        warning_channels = 0,  # Placeholder for warning channel calculation
        companies = Company.objects.all()
        serializer = ChannelOverviewSerializer(companies, many=True, context={'request': request})
        data = {
            "total_channels": total_channels,
            "online_channels": online_channels,
            "offline_channels": offline_channels,
            "warning_channels": warning_channels,
            "companies": serializer.data
        }
        return Response(data)
