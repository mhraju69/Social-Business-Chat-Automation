from django.shortcuts import render
import requests
from django.urls import reverse
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
from Accounts.utils import get_company_user
from collections import Counter
from django.http import HttpResponseRedirect
# Create your views here.


def Connect(request):
    return render(request,'connect.html')


class FacebookConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fb_app_id = settings.FB_APP_ID
        redirect_uri = request.build_absolute_uri(reverse("facebook_callback"))
        
        # ✅ Added pages_messaging permission
        scope = "pages_show_list,pages_manage_metadata,pages_read_engagement,pages_messaging"
        # state = 1
        target_user = get_company_user(request.user)
        state = target_user.id if target_user else request.user.id

        fb_login_url = (
            f"https://www.facebook.com/v20.0/dialog/oauth"
            f"?client_id={fb_app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&state={state},{request.query_params.get('from',"web")}"
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
    state_data = request.GET.get("state")
    state = state_data.split(",")[0]
    _from = state_data.split(",")[1]
    print(f"Facebook callback: code={code}, error={error}, state={state_data}, from={_from}")

    if error:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/user/integrations")

    if not code:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/user/integrations")

    token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
    # Dynamic redirect_uri to match the one sent in ConnectView
    redirect_uri = request.build_absolute_uri(reverse("facebook_callback")).split('?')[0]
    
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": redirect_uri,
        "client_secret": settings.FB_APP_SECRET,
        "code": code,
    }
    
    resp = requests.get(token_url, params=params)
    data = resp.json()

    # print("😏😏😏Facebook callback response:",data)
    
    if "access_token" not in data:
        return JsonResponse({"error": "Token exchange failed", "details": data})

    user_access_token = data["access_token"]

    # Debug token to check actual scopes
    debug_url = "https://graph.facebook.com/debug_token"
    debug_params = {
        "input_token": user_access_token,
        "access_token": f"{settings.FB_APP_ID}|{settings.FB_APP_SECRET}"
    }
    debug_resp = requests.get(debug_url, params=debug_params)
    print("😏😏😏 Token Scopes Debug:", debug_resp.json().get('data', {}).get('scopes'))

    # 1. Exchange short-lived User Access Token for Long-lived User Access Token
    exchange_url = "https://graph.facebook.com/v20.0/oauth/access_token"
    exchange_params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.FB_APP_ID,
        "client_secret": settings.FB_APP_SECRET,
        "fb_exchange_token": user_access_token,
    }
    
    exchange_resp = requests.get(exchange_url, params=exchange_params)
    exchange_data = exchange_resp.json()
    long_lived_user_token = exchange_data.get("access_token", user_access_token)

    # 2. Get pages with Long-lived Page Tokens using Long-lived User Token
    pages_url = "https://graph.facebook.com/v20.0/me/accounts"
    pages_resp = requests.get(pages_url, params={"access_token": long_lived_user_token})
    pages_data = pages_resp.json()

    print("😏😏😏Facebook pages response:",pages_data)
    
    if "data" not in pages_data:
        return JsonResponse({"error": "Failed to fetch pages", "details": pages_data})

    try:
        user = User.objects.get(id=state)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found"})

    saved_pages = []
    for page in pages_data["data"]:
        page_id = page["id"]
        page_name = page.get("name", "")
        # This token is already long-lived because we used long-lived user token to fetch accounts
        page_access_token = page["access_token"] 

        fb_profile, created = ChatProfile.objects.update_or_create(
            profile_id=page_id,
            defaults={
                "user": user,
                "name": page_name,
                "access_token": page_access_token,
                "bot_active": True,
                "platform": "facebook",
            }
        )
        saved_pages.append(page_id)
        
    if _from == "app":
        return render(request,'redirect.html')
    else:
        return redirect(f"{settings.FRONTEND_URL}/user/chat-profile")


class InstagramConnectView(APIView):
    # permission_classes = [AllowAny]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fb_app_id = settings.FB_APP_ID
        redirect_uri = request.build_absolute_uri(reverse("instagram_callback"))
        scope = "instagram_basic,instagram_manage_messages,pages_show_list,pages_manage_metadata"
        target_user = get_company_user(request.user)
        state = target_user.id if target_user else request.user.id 

        fb_login_url = (
            f"https://www.facebook.com/v20.0/dialog/oauth"
            f"?client_id={fb_app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&state={state},{request.query_params.get('from',"web")}"
        )
        return Response({"redirect_url":fb_login_url})


@api_view(['GET'])
@permission_classes([AllowAny])
def instagram_callback(request):
    code = request.GET.get("code")
    error = request.GET.get("error")
    state_data = request.GET.get("state")
    state = state_data.split(",")[0]
    _from = state_data.split(",")[1]

    if error:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/user/integrations")

    if not code:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/user/integrations")

    token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
    redirect_uri = request.build_absolute_uri(reverse("instagram_callback")).split('?')[0]
    
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": redirect_uri,
        "client_secret": settings.FB_APP_SECRET,
        "code": code,
    }
    resp = requests.get(token_url, params=params)
    data = resp.json()

    if "access_token" not in data:
        return Response({"error": "Token exchange failed", "details": data}, status=400)

    short_lived_token = data["access_token"]
    
    # Exchange for Long-lived User Token
    exchange_url = "https://graph.facebook.com/v20.0/oauth/access_token"
    exchange_params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.FB_APP_ID,
        "client_secret": settings.FB_APP_SECRET,
        "fb_exchange_token": short_lived_token,
    }
    try:
        exchange_resp = requests.get(exchange_url, params=exchange_params)
        exchange_data = exchange_resp.json()
        user_access_token = exchange_data.get("access_token", short_lived_token)
    except Exception as e:
        print(f"Error exchanging token: {e}")
        user_access_token = short_lived_token

    pages_resp = requests.get(
        "https://graph.facebook.com/v20.0/me/accounts",
        params={"access_token": user_access_token}
    )
    pages_data = pages_resp.json()

    if "data" not in pages_data:
        return Response({"error": "No pages found", "details": pages_data}, status=400)

    user = User.objects.get(id=state)

    profile_created = False
    
    for page in pages_data["data"]:
        page_id = page["id"]
        page_name = page.get("name")
        page_token = page["access_token"]  # This should be long-lived now since we used long-lived user token

        insta_resp = requests.get(
            f"https://graph.facebook.com/v20.0/{page_id}",
            params={
                "fields": "instagram_business_account",
                "access_token": page_token
            }
        )
        insta_data = insta_resp.json()
        
        insta_account = insta_data.get("instagram_business_account")

        if insta_account:
            ig_id = insta_account["id"]

            # Strict check for Instagram: Single profile policy
            existing_ig_profile = ChatProfile.objects.filter(user=user, platform='instagram').first()
            
            if existing_ig_profile and existing_ig_profile.profile_id != ig_id:
                # If an IG profile exists and it's NOT this one, skip.
                continue
            
            # Also prevent creating multiple in the same loop if user selects multiple (though less likely for IG logic here)
            if ChatProfile.objects.filter(user=user, platform='instagram').exclude(profile_id=ig_id).exists():
                continue

            ChatProfile.objects.update_or_create(
                profile_id=ig_id,
                defaults={
                    "user": user,
                    # "page": ... removed as it does not exist in model
                    "name": page_name, # Storing page name as profile name
                    "access_token": page_token,
                    "bot_active": True,
                    'platform': 'instagram',
                },
            )
            profile_created = True
        
        # If no insta_account, just continue to next page
    
    if not profile_created:
         # Check if we failed because one already exists (silent success?) or because none found
         if ChatProfile.objects.filter(user=user, platform='instagram').exists():
             pass # Already had one, just didn't update (maybe IDs mismatch) - treat as success redirect
         else:
             return Response({"error": "No Instagram Business account found linked to your pages."}, status=400)

    if _from == "app":
        return render(request,'redirect.html')
    else:
        return redirect(f"{settings.FRONTEND_URL}/user/integrations")


class ConnectWhatsappView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        target_user = get_company_user(request.user)
        if not target_user:
            return Response({"error": "User not found (company user)"}, status=404)
        
        try:
            company = target_user.company
        except Exception:
            return Response({"error": "Company not found"}, status=404)
    
        state = target_user.id
        redirect_url = request.build_absolute_uri(reverse("whatsapp_callback"))

        redirect_url = f"https://www.facebook.com/v19.0/dialog/oauth?client_id={settings.FB_APP_ID}&redirect_uri={redirect_url}&state={state},{request.query_params.get('from','web')}&response_type=code&config_id={settings.WHATSAPP_CONFIG_ID}"
        
        return Response({"redirect_url": redirect_url})


@api_view(['GET'])
@permission_classes([AllowAny])
def whatsapp_callback(request):
    code = request.GET.get("code")
    error = request.GET.get("error")
    state_data = request.GET.get("state")
    
    # Parse state to get user ID and source
    if state_data and "," in state_data:
        state = state_data.split(",")[0]
        _from = state_data.split(",")[1]
    else:
        state = state_data
        _from = "web"
    
    print(f"WhatsApp callback: code={code}, error={error}, state={state_data}, from={_from}")

    if error:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/user/integrations")

    if not code:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/user/integrations")

    # Exchange code for access token
    token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
    redirect_uri = request.build_absolute_uri(reverse("whatsapp_callback")).split('?')[0]
    
    params = {
        "client_id": settings.FB_APP_ID,
        "redirect_uri": redirect_uri,
        "client_secret": settings.FB_APP_SECRET,
        "code": code,
    }
    
    resp = requests.get(token_url, params=params)
    data = resp.json()
    
    if "access_token" not in data:
        return JsonResponse({"error": "Token exchange failed", "details": data})

    access_token = data["access_token"]

    # Get WhatsApp Business Account details
    # First, get the WABA ID from the debug token or business accounts
    debug_url = "https://graph.facebook.com/v19.0/debug_token"
    debug_params = {
        "input_token": access_token,
        "access_token": f"{settings.FB_APP_ID}|{settings.FB_APP_SECRET}"
    }
    
    debug_resp = requests.get(debug_url, params=debug_params)
    debug_data = debug_resp.json()
    
    # Get WABA (WhatsApp Business Account) information
    # Try to get WABA from the user's business accounts
    waba_url = "https://graph.facebook.com/v19.0/me"
    waba_params = {
        "fields": "id,name",
        "access_token": access_token
    }
    
    waba_resp = requests.get(waba_url, params=waba_params)
    waba_data = waba_resp.json()
    
    # Get phone number ID and details
    # The embedded signup flow should provide WABA ID in the token granular scopes
    # Let's try to get the phone number ID from the accounts endpoint
    phone_url = "https://graph.facebook.com/v19.0/me/accounts"
    phone_params = {
        "access_token": access_token
    }
    
    phone_resp = requests.get(phone_url, params=phone_params)
    phone_data = phone_resp.json()
    
    # For WhatsApp, we need to get the WABA and phone number ID
    # The token should have granular_scopes that include the WABA ID
    granular_scopes = debug_data.get("data", {}).get("granular_scopes", [])
    waba_id = None
    
    for scope in granular_scopes:
        if scope.get("scope") == "whatsapp_business_management":
            target_ids = scope.get("target_ids", [])
            if target_ids:
                waba_id = target_ids[0]
                break
    
    if not waba_id:
        return JsonResponse({"error": "WhatsApp Business Account ID not found in token"})

    # Get phone numbers associated with this WABA
    phone_numbers_url = f"https://graph.facebook.com/v19.0/{waba_id}/phone_numbers"
    phone_numbers_params = {
        "access_token": access_token
    }
    
    phone_numbers_resp = requests.get(phone_numbers_url, params=phone_numbers_params)
    phone_numbers_data = phone_numbers_resp.json()
    
    if "data" not in phone_numbers_data or not phone_numbers_data["data"]:
        return JsonResponse({"error": "No phone numbers found for WhatsApp Business Account"})

    try:
        user = User.objects.get(id=state)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found"})

    # Save the first phone number (or you can modify to save all)
    saved_profiles = []
    
    for phone in phone_numbers_data["data"]:
        phone_number_id = phone["id"]
        display_phone_number = phone.get("display_phone_number", "")
        verified_name = phone.get("verified_name", "")
        
        # Create or update the WhatsApp ChatProfile
        whatsapp_profile, created = ChatProfile.objects.update_or_create(
            profile_id=phone_number_id,
            defaults={
                "user": user,
                "name": verified_name or display_phone_number,
                "access_token": access_token,
                "bot_active": True,
                "platform": "whatsapp",
            }
        )
        
        saved_profiles.append({
            "id": phone_number_id,
            "name": verified_name or display_phone_number,
            "display_phone_number": display_phone_number,
            "created": created
        })
        
        # For now, only save the first phone number
    
    if _from == "app":
        return render(request, 'redirect.html')
    else:
        return redirect(f"{settings.FRONTEND_URL}/user/integrations")
    

class ChatProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatProfileSerializers

    def get_object(self):
        platform = self.request.query_params.get("platform") or self.request.data.get("platform") or "facebook"
        
        target_user = get_company_user(self.request.user)
        if not target_user:
             raise NotFound("Company user not found.")
        
        try:
            return ChatProfile.objects.filter(user=target_user, platform=platform).first()
        except ChatProfile.DoesNotExist:
            raise NotFound(detail=f"ChatProfile with platform '{platform}' not found.")


class ChatProfileListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatProfileSerializers

    def get_queryset(self):
        platform = self.request.query_params.get("platform") or self.request.data.get("platform") or "facebook"
        
        target_user = get_company_user(self.request.user)
        if not target_user:
             raise NotFound("Company user not found.")
        
        try:
            return ChatProfile.objects.filter(user=target_user, platform=platform)
        except ChatProfile.DoesNotExist:
            raise NotFound(detail=f"ChatProfile with platform '{platform}' not found.")


class CommonAskedLeaderboard(APIView):
    def get(self, request):
        target_user = get_company_user(request.user)
        company = Company.objects.filter(user=target_user).first()

        if not company:
            return Response({"error": "Company not found"}, status=404)

        # Get all incoming messages for this user's rooms
        messages = ChatMessage.objects.filter(
            room__profile__user=target_user,
            type='incoming'
        ).values_list('text', flat=True)

        # Define question starters
        question_starters = (
            "what", "why", "how", "when", "where", "who",
            "can", "could", "would", "should", "is", "are", "do", "does"
        )

        # Filter messages that are questions
        questions = []
        for text in messages:
            stripped_text = text.strip()
            if stripped_text.endswith('?'):
                questions.append(stripped_text)
            else:
                # Check if it starts with a question word
                first_word = stripped_text.split(' ')[0].lower()
                if first_word in question_starters:
                    questions.append(stripped_text)

        # Count the occurrences of each question
        question_counts = Counter(questions)

        # Get top 10 most common questions
        top_questions = question_counts.most_common(10)

        # Format data as list of dicts
        data = [{"text": q, "count": c} for q, c in top_questions]

        return Response(data)


class GetOldMessage(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request,room_id,platform):
        target_user = get_company_user(request.user)
        if not ChatRoom.objects.filter(id=room_id,profile__user=target_user,profile__platform=platform).exists():
            return Response({"error": "Room not found"}, status=404)
            

        try:
            room = ChatRoom.objects.get(id=room_id,profile__platform=platform)
            messages = ChatMessage.objects.filter(room=room).order_by('-timestamp')[:50]
            serializer = ChatMessageSerializer(messages[::-1], many=True)
            return Response(serializer.data)
        except ChatRoom.DoesNotExist:
            return Response({"error": "Room not found"}, status=404)

      
class GetTestChatOldMessage(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        target_user = get_company_user(request.user)
        if not target_user:
            return Response({"error": "User not found (company user)"}, status=404)

        try:
            company = target_user.company
        except Exception:
            return Response({"error": "Company not found"}, status=404)

        messages = TestChat.objects.filter(company=company).order_by('-timestamp')[:50]
        # Reverse to show oldest first in the list if that is desired, or keep as is.
        # Use [::-1] as in GetOldMessage to likely match frontend expectation (chronological order)
        serializer = TestChatSerializer(messages[::-1], many=True)
        return Response(serializer.data)


class SubscribeFacebookPageToWebhook(views.APIView):
    def post(self,request,*args,**kwargs):
        profile = ChatProfile.objects.filter(id=request.query_params.get("profile_id")).first()
        if not profile:
            return Response({"error": "Profile not found"}, status=404)
        
        subscribe = subscribe_page_to_webhook(profile.profile_id, profile.access_token)

        if not subscribe:
            return Response({"error": "Failed to subscribe page to webhook"}, status=500)
            
        ChatProfile.objects.filter(user=profile.user).exclude(id=profile.id).delete()
        return Response({"success": "Page subscribed to webhook"}, status=200)