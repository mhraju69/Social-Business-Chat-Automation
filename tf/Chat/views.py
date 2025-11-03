from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import WhatsAppProfile, Incoming

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_active_rooms(request):
    profile = WhatsAppProfile.objects.filter(user=request.user, bot_active=True).first()
    if not profile:
        return Response({"rooms": []})

    user_numbers = Incoming.objects.filter(receiver=profile).values_list('from_number', flat=True).distinct()

    rooms = []
    for number in user_numbers:
        rooms.append({
            "from_number": number,
            "room_name": f"{profile.number_id}_{number}"
        })

    return Response({"rooms": rooms})
