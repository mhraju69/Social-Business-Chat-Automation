from django.shortcuts import render,HttpResponse
import requests
from django.http import JsonResponse
from django.conf import settings
from .models import *
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from rest_framework.generics import *
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny,IsAuthenticated
User = get_user_model()
from rest_framework.decorators import api_view,permission_classes
from .serializers import *
from rest_framework.exceptions import NotFound
from django.db.models import Count
from django.db.models.functions import Lower
from Accounts.models import *
# Create your views here.

def Connect(request):
    return render(request,'connect.html')

class FacebookConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fb_app_id = settings.FB_APP_ID
        redirect_uri = "https://ape-in-eft.ngrok-free.app/facebook/callback/"
        
        # ✅ Added pages_messaging permission
        scope = "pages_show_list,pages_manage_metadata,pages_read_engagement,pages_messaging"
        # state = 1
        state = request.user.id

        fb_login_url = (
            f"https://www.facebook.com/v20.0/dialog/oauth"
            f"?client_id={fb_app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&state={state}"
            f"&from={request.data.get('from',"web")}"
        )

        return Response({"redirect_url": fb_login_url})


def subscribe_page_to_webhook(page_id, page_access_token):
    try:
        subscribe_url = f"https://graph.facebook.com/v20.0/{page_id}/subscribed_apps"
        params = {
            "subscribed_fields": "messages,messaging_postbacks,messaging_optins,message_echoes",
            "access_token": page_access_token
        }
        
        response = requests.post(subscribe_url, params=params)
        result = response.json()
        
        if result.get('success'):
            return True
        else:
            return False
            
    except Exception as e:
        return False


def check_page_subscription(page_id, page_access_token):
    """
    Page এর current subscription status check করে
    """
    try:
        check_url = f"https://graph.facebook.com/v20.0/{page_id}/subscribed_apps"
        params = {"access_token": page_access_token}
        
        response = requests.get(check_url, params=params)
        result = response.json()
        
        print(f"📊 Page {page_id} subscription status: {result}")
        return result
        
    except Exception as e:
        print(f"❌ Error checking subscription: {e}")
        return None


@api_view(['GET'])
@permission_classes([AllowAny])
def facebook_callback(request):
    code = request.GET.get("code")
    error = request.GET.get("error")
    state = request.GET.get("state")
    _from = request.GET.get("from")

    if error:
        return JsonResponse({"error": error})
    if not code:
        return JsonResponse({"error": "Missing code parameter"})

    token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": "https://ape-in-eft.ngrok-free.app/facebook/callback/",
        "client_secret": settings.FB_APP_SECRET,
        "code": code,
    }
    
    resp = requests.get(token_url, params=params)
    data = resp.json()
    
    if "access_token" not in data:
        return JsonResponse({"error": "Token exchange failed", "details": data})

    user_access_token = data["access_token"]

    pages_url = "https://graph.facebook.com/v20.0/me/accounts"
    pages_resp = requests.get(pages_url, params={"access_token": user_access_token})
    pages_data = pages_resp.json()
    
    if "data" not in pages_data:
        return JsonResponse({"error": "Failed to fetch pages", "details": pages_data})

    try:
        user = User.objects.get(id=state)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found"})

    saved_pages = []
    subscription_results = []

    for page in pages_data["data"]:
        page_id = page["id"]
        page_name = page.get("name", "")
        short_lived_token = page["access_token"]

        exchange_url = "https://graph.facebook.com/v20.0/oauth/access_token"
        exchange_params = {
            "grant_type": "fb_exchange_token",
            "client_id": settings.FB_APP_ID,
            "client_secret": settings.FB_APP_SECRET,
            "fb_exchange_token": short_lived_token,
        }
        
        exchange_resp = requests.get(exchange_url, params=exchange_params)
        exchange_data = exchange_resp.json()
        long_lived_token = exchange_data.get("access_token", short_lived_token)
        

        fb_profile, created = ChatProfile.objects.update_or_create(
            profile_id=page_id,
            defaults={
                "user": user,
                "name": page_name,
                "access_token": long_lived_token,
                "bot_active": True,
                "platform": "facebook",
            }
        )

        subscription_success = subscribe_page_to_webhook(page_id, long_lived_token)
        
        subscription_status = check_page_subscription(page_id, long_lived_token)

        saved_pages.append({
            "id": page_id,
            "name": page_name,
            "subscribed": subscription_success
        })
        subscription_results.append({
            "page": page_name,
            "subscription_success": subscription_success,
            "subscription_status": subscription_status
        })
    if _from == "app":
        return render(request,'redirect.html')
    else:
        return JsonResponse({
            "status": "success",
            "message": "Facebook pages connected and subscribed successfully",
            "pages": saved_pages,
        "subscription_details": subscription_results
    })

class InstagramConnectView(APIView):
    # permission_classes = [AllowAny]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fb_app_id = settings.FB_APP_ID
        redirect_uri = "https://ape-in-eft.ngrok-free.app/instagram/callback/"
        scope = "instagram_basic,instagram_manage_messages,pages_show_list,pages_manage_metadata"
        state = request.user.id 

        fb_login_url = (
            f"https://www.facebook.com/v20.0/dialog/oauth"
            f"?client_id={fb_app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&state={state}"
            f"&from={request.data.get('from',"web")}"
        )
        return Response({"redirect_url":fb_login_url})

@api_view(['GET'])
@permission_classes([AllowAny])
def instagram_callback(request):
    code = request.GET.get("code")
    error = request.GET.get("error")
    state = request.GET.get("state")
    _from = request.GET.get("from")

    if error:
        return Response({"error": error}, status=400)

    if not code:
        return Response({"error": "Missing code parameter"}, status=400)

    token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": "https://ape-in-eft.ngrok-free.app/instagram/callback/",
        "client_secret": settings.FB_APP_SECRET,
        "code": code,
    }
    resp = requests.get(token_url, params=params)
    data = resp.json()

    if "access_token" not in data:
        return Response({"error": "Token exchange failed", "details": data}, status=400)

    user_access_token = data["access_token"]

    pages_resp = requests.get(
        "https://graph.facebook.com/v20.0/me/accounts",
        params={"access_token": user_access_token}
    )
    pages_data = pages_resp.json()

    if "data" not in pages_data:
        return Response({"error": "No pages found", "details": pages_data}, status=400)

    user = User.objects.get(id=state)

    debug_pages = []

    for page in pages_data["data"]:
        page_id = page["id"]
        page_name = page.get("name")
        page_token = page["access_token"]

        insta_resp = requests.get(
            f"https://graph.facebook.com/v20.0/{page_id}",
            params={
                "fields": "instagram_business_account",
                "access_token": page_token
            }
        )
        insta_data = insta_resp.json()

        debug_pages.append({
            "page_id": page_id,
            "page_name": page_name,
            "insta_response": insta_data
        })

        insta_account = insta_data.get("instagram_business_account")

        if insta_account:
            ig_id = insta_account["id"]

            ChatProfile.objects.update_or_create(
                profile_id=ig_id,
                defaults={
                    "user": user,
                    "page": ChatProfile.objects.get(profile_id=page_id),
                    "access_token": page_token,
                    "bot_active": True,
                    'platform': 'instagram',
                },
            )
        else:
            return Response({"error": "Account not found"}, status=400)

    if _from == "app":
        return render(request,'redirect.html')
    else:
        return Response({
        "status": "debug",
        "pages_checked": len(debug_pages),
        "pages": debug_pages
    })


class ChatProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatProfileSerializers

    def get_object(self):
        platform = self.request.query_params.get("platform") or self.request.data.get("platform") or "facebook"
        
        try:
            return ChatProfile.objects.get(user=self.request.user, platform=platform)
        except ChatProfile.DoesNotExist:
            raise NotFound(detail=f"ChatProfile with platform '{platform}' not found.")
        
class CommonAskedLeaderboard(APIView):
    def get(self, request):
        company = Company.objects.filter(user=request.user).first()

        if not company:
            return Response({"error": "Company not found"}, status=404)

        data = ChatMessage.objects.filter(
            room__profile__user=request.user,
            type='incoming'
        ).values('text').annotate(
            count=Count('id')
        ).order_by('-count')[:10]  # top 20 questions

        return Response(data)

class GetOldMessage(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request,room_id,platform):
        user = request.user
        if not ChatRoom.objects.filter(id=room_id,profile__user=user,profile__platform=platform).exists():
            return Response({"error": "Room not found"}, status=404)
            

        try:
            room = ChatRoom.objects.get(id=room_id,profile__platform=platform)
            messages = ChatMessage.objects.filter(room=room).order_by('-timestamp')[:50]
            serializer = ChatMessageSerializer(messages, many=True)
            return Response(serializer.data)
        except ChatRoom.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)
        


