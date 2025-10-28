from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from datetime import timedelta
from django.db.models import Count
from django.db.models.functions import ExtractWeekDay
from django.utils.timezone import now
from Whatsapp.models import WhatsAppProfile, Incoming as WAIncoming, Outgoing as WAOutgoing
from Facebook.models import FacebookProfile, Incoming as FBIncoming, Outgoing as FBOutgoing
from Instagram.models import InstagramProfile, Incoming as IGIncoming, Outgoing as IGOutgoing

class MessageStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        weekday_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        start_date = now() - timedelta(days=7)

        results = {}

        # ================== WhatsApp ==================
        wa_stats = {day: 0 for day in weekday_names}
        wa_profiles = WhatsAppProfile.objects.filter(user=user)
        if wa_profiles.exists():
            # Get all clients that have messages linked to these profiles
            incoming_clients = WAIncoming.objects.filter(receiver__in=wa_profiles).values_list('client', flat=True)
            outgoing_clients = WAOutgoing.objects.filter(sender__in=wa_profiles).values_list('client', flat=True)
            client_ids = set(list(incoming_clients) + list(outgoing_clients))

            if client_ids:
                # Incoming
                data = (
                    WAIncoming.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    wa_stats[weekday_names[row['weekday'] - 1]] += row['count']

                # Outgoing
                data = (
                    WAOutgoing.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    wa_stats[weekday_names[row['weekday'] - 1]] += row['count']

        results['whatsapp'] = wa_stats

        # ================== Facebook ==================
        fb_stats = {day: 0 for day in weekday_names}
        fb_profiles = FacebookProfile.objects.filter(user=user)
        if fb_profiles.exists():
            # Get all clients linked to this user's FB profiles
            incoming_clients = FBIncoming.objects.filter(receiver__in=fb_profiles).values_list('client', flat=True)
            outgoing_clients = FBOutgoing.objects.filter(sender__in=fb_profiles).values_list('client', flat=True)
            client_ids = set(list(incoming_clients) + list(outgoing_clients))

            if client_ids:
                # Incoming
                data = (
                    FBIncoming.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    fb_stats[weekday_names[row['weekday'] - 1]] += row['count']

                # Outgoing
                data = (
                    FBOutgoing.objects.filter(timestamp__gte=start_date, client_id__in=client_ids)
                    .annotate(weekday=ExtractWeekDay('timestamp'))
                    .values('weekday')
                    .annotate(count=Count('id'))
                )
                for row in data:
                    fb_stats[weekday_names[row['weekday'] - 1]] += row['count']

        results['facebook'] = fb_stats

        # ================== Instagram ==================
        ig_stats = {day: 0 for day in weekday_names}
        ig_profiles = InstagramProfile.objects.filter(user=user)
        if ig_profiles.exists():
            # Incoming
            data = (
                IGIncoming.objects.filter(timestamp__gte=start_date, receiver__in=ig_profiles)
                .annotate(weekday=ExtractWeekDay('timestamp'))
                .values('weekday')
                .annotate(count=Count('id'))
            )
            for row in data:
                ig_stats[weekday_names[row['weekday'] - 1]] += row['count']

            # Outgoing
            data = (
                IGOutgoing.objects.filter(timestamp__gte=start_date, sender__in=ig_profiles)
                .annotate(weekday=ExtractWeekDay('timestamp'))
                .values('weekday')
                .annotate(count=Count('id'))
            )
            for row in data:
                ig_stats[weekday_names[row['weekday'] - 1]] += row['count']

        results['instagram'] = ig_stats

        return Response(results)
