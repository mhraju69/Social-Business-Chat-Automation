import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework import generics
from Accounts.models import User, Company
from Finance import models
from Socials.models import ChatProfile
from Finance.models import Payment
from Others.models import SupportTicket
from django.db.models import Sum, Q
from Others.serializers import SupportTicketSerializer
from Accounts.serializers import UserSerializer
from rest_framework.filters import OrderingFilter, SearchFilter

class DashboardView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

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
        )

        # Show chart data by month (month, users, revenue, cost)

        chart_data = []
        for month in range(1, 13):
            month_name = datetime.date(1900, month, 1).strftime('%B')
            month_users = User.objects.filter(date_joined__month=month).count()
            month_revenue = Payment.objects.filter(created_at__month=month).aggregate(total_revenue=Sum('amount'))['total_revenue'] or 0
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
    
class UserListView(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAdminUser]

    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'email', 'phone']
    ordering_fields = ['date_joined', 'name', 'email']


class EnableChannelsView(APIView):
    permission_classes = [permissions.IsAdminUser]

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
    permission_classes = [permissions.IsAdminUser]

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
    permission_classes = [permissions.IsAdminUser]

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
    permission_classes = [permissions.IsAdminUser]

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