from django.shortcuts import render
import requests
from django.http import JsonResponse
from django.conf import settings
from .models import FacebookProfile
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny,IsAuthenticated
User = get_user_model()

# Create your views here.

def Connect(request):
    return render(request,'connect.html')


class FacebookConnectView(APIView):
    permission_classes = [AllowAny]
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        
        fb_app_id = settings.FB_APP_ID
        redirect_uri = "https://ape-in-eft.ngrok-free.app/facebook/callback/"
        scope = "pages_show_list,pages_manage_metadata,pages_read_engagement,pages_messaging"
        state = 2
        # state = request.user.id

        fb_login_url = (
            f"https://www.facebook.com/v20.0/dialog/oauth"
            f"?client_id={fb_app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&state={state}"
        )

        return redirect(fb_login_url)
        
from rest_framework.decorators import api_view,permission_classes

@api_view(['GET'])
@permission_classes([AllowAny])
def facebook_callback(request):
    """
    Callback after Facebook login.
    Exchange code → get user token → fetch pages → save Page tokens
    """
    code = request.GET.get("code")
    error = request.GET.get("error")
    state = request.GET.get("state")  # optional: you can use this to pass user_id/session

    if error:
        return JsonResponse({"error": error})

    if not code:
        return JsonResponse({"error": "Missing code parameter"})

    # Step 1: Exchange code for User Access Token
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

    # Step 2: Get user's Facebook Pages
    pages_url = "https://graph.facebook.com/v20.0/me/accounts"
    pages_resp = requests.get(pages_url, params={"access_token": user_access_token})
    pages_data = pages_resp.json()

    if "data" not in pages_data:
        return JsonResponse({"error": "Failed to fetch pages", "details": pages_data})

    # Step 3: Get Django user instance
    # You can replace state with proper session/user management
    user = User.objects.get(id=state)

    saved_pages = []

    # Step 4: Save each page in FacebookProfile
    for page in pages_data["data"]:
        page_id = page["id"]
        page_token = page["access_token"]
        page_name = page.get("name", "")

        fb_profile, created = FacebookProfile.objects.update_or_create(
            page_id=page_id,
            defaults={
                "user": user,
                "page_access_token": page_token,
                "bot_active": True
            }
        )
        saved_pages.append({"id": page_id, "name": page_name})

    return  Response({"status": "success", "accounts": saved_pages})