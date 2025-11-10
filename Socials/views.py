from django.shortcuts import render,HttpResponse
import requests
from django.http import JsonResponse
from django.conf import settings
from .models import *
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny,IsAuthenticated
User = get_user_model()
from rest_framework.decorators import api_view,permission_classes

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
        
@api_view(['GET'])
@permission_classes([AllowAny])
def facebook_callback(request):

    code = request.GET.get("code")
    error = request.GET.get("error")
    state = request.GET.get("state")  # can pass user id/session

    if error:
        return JsonResponse({"error": error})
    if not code:
        return JsonResponse({"error": "Missing code parameter"})

    # Step 1: Exchange code for short-lived User Access Token
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

    # Step 2: Get all pages of the user
    pages_url = "https://graph.facebook.com/v20.0/me/accounts"
    pages_resp = requests.get(pages_url, params={"access_token": user_access_token})
    pages_data = pages_resp.json()
    if "data" not in pages_data:
        return JsonResponse({"error": "Failed to fetch pages", "details": pages_data})

    # Step 3: Get Django user instance
    user = User.objects.get(id=state)  # replace with real session handling

    saved_pages = []

    # Step 4: Save each page in FacebookProfile
    for page in pages_data["data"]:
        page_id = page["id"]
        page_name = page.get("name", "")
        short_lived_token = page["access_token"]

        # Step 4a: Exchange for long-lived Page Access Token
        exchange_url = "https://graph.facebook.com/v20.0/oauth/access_token"
        exchange_params = {
            "grant_type": "fb_exchange_token",
            "client_id": settings.FB_APP_ID,
            "client_secret": settings.FB_APP_SECRET,
            "fb_exchange_token": short_lived_token,
        }
        exchange_resp = requests.get(exchange_url, params=exchange_params)
        exchange_data = exchange_resp.json()
        long_lived_token = exchange_data.get("access_token", short_lived_token)  # fallback

        # Step 4b: Save/update FacebookProfile in DB
        fb_profile, created = ChatProfile.objects.update_or_create(
            profile_id=page_id,
            defaults={
                "user": user,
                "access_token": long_lived_token,
                "bot_active": True,
                'platform': 'facebook',
            }
        )
        saved_pages.append({"id": page_id, "name": page_name})

    # return Response({"status": "success", "accounts": saved_pages})
    return HttpResponse("Facebook pages connected successfully.")

class InstagramConnectView(APIView):
    permission_classes = [AllowAny]
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Redirect user to Facebook login to get permission for Instagram connected pages
        """
        fb_app_id = settings.FB_APP_ID
        redirect_uri = "https://ape-in-eft.ngrok-free.app/instagram/callback/"
        scope = "instagram_basic,instagram_manage_messages,pages_show_list,pages_manage_metadata"
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

@api_view(['GET'])
@permission_classes([AllowAny])
def instagram_callback(request):
    code = request.GET.get("code")
    error = request.GET.get("error")
    state = request.GET.get("state")

    if error:
        return Response({"error": error}, status=400)

    if not code:
        return Response({"error": "Missing code parameter"}, status=400)

    # Step 1: Exchange code for User Access Token
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

    # Step 2: Get user's Facebook Pages
    pages_resp = requests.get(
        "https://graph.facebook.com/v20.0/me/accounts",
        params={"access_token": user_access_token}
    )
    pages_data = pages_resp.json()

    if "data" not in pages_data:
        return Response({"error": "No pages found", "details": pages_data}, status=400)

    user = User.objects.get(id=state)

    debug_pages = []  # store for debug response

    # Step 3: Loop through pages and check for linked Instagram account
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

            # Save Instagram profile
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

    return Response({
        "status": "debug",
        "pages_checked": len(debug_pages),
        "pages": debug_pages
    })

