from django.http import JsonResponse
from Socials.models import *
from Socials.webhook import *
import re,pytz,requests
from datetime import timedelta,datetime
from Socials.helper import send_message
from rest_framework.response import Response
from rest_framework import status
from .serializers import BookingSerializer
from .models import GoogleCalendar, UserSession
from django.conf import settings
from Accounts.models import Company
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from django.contrib.auth import get_user_model

User = get_user_model()

def validate_and_refresh_token(access_token, refresh_token):
    """
    Validates access token and refreshes it if needed.
    
    Args:
        access_token (str): The JWT access token to validate
        refresh_token (str): The JWT refresh token to use for refreshing
        
    Returns:
        dict: {
            'valid': bool,
            'access_token': str or None,
            'refresh_token': str or None,
            'user': User object or None,
            'error': str or None
        }
    """
    result = {
        'valid': False,
        'access_token': None,
        'refresh_token': None,
        'user': None,
        'error': None
    }
    
    # First, try to validate the access token
    try:
        access_token_obj = AccessToken(access_token)
        user_id = access_token_obj['user_id']
        
        # Get the user
        try:
            user = User.objects.get(id=user_id)
            
            # Check if user is still active and not blocked
            if user.block:
                result['error'] = 'Account has been blocked'
                return result
            
            if not user.is_active:
                result['error'] = 'Account is not active'
                return result
            
            # Access token is valid
            result['valid'] = True
            result['access_token'] = access_token
            result['refresh_token'] = refresh_token
            result['user'] = user
            
            print(f"✅ Access token is valid for user: {user.email}")
            return result
            
        except User.DoesNotExist:
            result['error'] = 'User not found'
            return result
            
    except (TokenError, InvalidToken) as e:
        # Access token is invalid or expired, try to refresh
        print(f"⚠️ Access token invalid/expired: {str(e)}")
        
        if not refresh_token:
            result['error'] = 'Access token expired and no refresh token provided'
            return result
        
        # Try to use refresh token to get new access token
        try:
            refresh_token_obj = RefreshToken(refresh_token)
            user_id = refresh_token_obj['user_id']
            
            # Get the user
            try:
                user = User.objects.get(id=user_id)
                
                # Check if user is still active and not blocked
                if user.block:
                    result['error'] = 'Account has been blocked'
                    return result
                
                if not user.is_active:
                    result['error'] = 'Account is not active'
                    return result
                
                # Generate new access token from refresh token
                new_access_token_obj = refresh_token_obj.access_token
                new_access_token = str(new_access_token_obj)
                new_jti = new_access_token_obj['jti']
                
                # Get the old token's JTI to find the session
                try:
                    old_access_token_obj = AccessToken(access_token)
                    old_jti = old_access_token_obj['jti']
                    
                    # Update the session with the new token
                    session = UserSession.objects.filter(
                        user=user, 
                        token=old_jti,
                        is_active=True
                    ).first()
                    
                    if session:
                        session.token = new_jti
                        session.save()
                        print(f"🔄 Updated session token from {old_jti[:10]}... to {new_jti[:10]}...")
                    else:
                        print(f"⚠️ No active session found with old token JTI: {old_jti[:10]}...")
                        
                except (TokenError, InvalidToken):
                    # Old token is completely invalid, can't extract JTI
                    # Try to find any active session for this user and update it
                    print(f"⚠️ Could not extract JTI from old token, updating most recent session")
                    session = UserSession.objects.filter(
                        user=user,
                        is_active=True
                    ).order_by('-last_active').first()
                    
                    if session:
                        session.token = new_jti
                        session.save()
                        print(f"🔄 Updated most recent session to new token: {new_jti[:10]}...")
                
                result['valid'] = True
                result['access_token'] = new_access_token
                result['refresh_token'] = refresh_token
                result['user'] = user
                
                print(f"✅ Generated new access token for user: {user.email}")
                return result
                
            except User.DoesNotExist:
                result['error'] = 'User not found'
                return result
                
        except (TokenError, InvalidToken) as e:
            result['error'] = f'Refresh token is invalid or expired: {str(e)}'
            return result
    
    except Exception as e:
        result['error'] = f'Unexpected error: {str(e)}'
        return result

def format_whatsapp_number(number):


    # Remove all non-digit characters
    digits = re.sub(r"\D", "", str(number))

    if digits.startswith("00"):
        # Remove international 00 prefix
        digits = digits[2:]

    if digits.startswith("+"):
        digits = digits[1:]

    return digits

def send_via_webhook_style(client_number, message_text):
    # Ensure the client exists
    client_obj, _ = ChatClient.objects.get_or_create(platform="whatsapp", client_id=client_number)
    
    # Get active WhatsApp profile
    profile = ChatProfile.objects.filter(platform="whatsapp", bot_active=True).first()
    if not profile:
        return {"error": "No active WhatsApp profile"}
    
    # Use the same send_message function your webhook uses
    print('☘️ Send successfuly')
    return send_message(profile, client_obj, message_text)

def parse_timezone_offset(tz_string):
    """Convert timezone string like '+6' to pytz FixedOffset"""
    try:
        offset_hours = float(tz_string)
        offset_minutes = int(offset_hours * 60)
        return pytz.FixedOffset(offset_minutes)
    except (ValueError, TypeError):
        return pytz.UTC

def get_timezone_object(tz_string):
    """
    Parse timezone string and return a timezone object.
    Handles both named timezones (e.g., 'Asia/Dhaka') and offset-based (e.g., '+6', '+06:00').
    
    Args:
        tz_string: Timezone string (named or offset)
        
    Returns:
        pytz timezone object or FixedOffset
    """
    if not tz_string:
        return pytz.UTC
        
    try:
        # Check if it's an offset-based timezone
        if any(char in tz_string for char in ['+', '-']) or tz_string.isdigit():
            return parse_timezone_offset(tz_string)
        # Otherwise treat as named timezone
        return pytz.timezone(tz_string)
    except Exception:
        return pytz.UTC

def local_to_utc(local_datetime, timezone_str):
    """
    Convert local datetime to UTC.
    
    Args:
        local_datetime: datetime object (naive or aware) in local timezone
        timezone_str: Timezone string (e.g., 'Asia/Dhaka', '+6', '+06:00')
        
    Returns:
        datetime object in UTC
    """
    from django.utils import timezone as django_timezone
    
    user_tz = get_timezone_object(timezone_str)
    
    # If datetime is naive, localize it to user timezone
    if django_timezone.is_naive(local_datetime):
        local_aware = user_tz.localize(local_datetime)
    else:
        # If already aware, convert to user timezone first
        local_aware = local_datetime.astimezone(user_tz)
    
    # Convert to UTC
    utc_datetime = local_aware.astimezone(pytz.UTC)
    return utc_datetime

def utc_to_local(utc_datetime, timezone_str):
    """
    Convert UTC datetime to local timezone.
    
    Args:
        utc_datetime: datetime object in UTC
        timezone_str: Timezone string (e.g., 'Asia/Dhaka', '+6', '+06:00')
        
    Returns:
        datetime object in local timezone
    """
    user_tz = get_timezone_object(timezone_str)
    
    # Convert UTC to local timezone
    local_datetime = utc_datetime.astimezone(user_tz)
    return local_datetime

def get_reminder_time_utc(start_time_utc, reminder_hours_before, tz_info):
    """
    Calculate reminder time in UTC.
    tz_info can be a pytz timezone object or an offset string.
    """
    if isinstance(tz_info, str):
        user_tz = parse_timezone_offset(tz_info)
    else:
        user_tz = tz_info
    
    # Convert to user local time
    start_local = start_time_utc.astimezone(user_tz)
    
    # Calculate reminder time in local timezone
    reminder_local = start_local - timedelta(hours=reminder_hours_before)
    
    # Convert to UTC for Celery
    reminder_utc = reminder_local.astimezone(pytz.UTC)
    
    # Debug logging
    print(f"🕐 Start time (UTC): {start_time_utc}")
    print(f"🌍 Start time (Local): {start_local}")
    print(f"⏰ Reminder time (Local): {reminder_local}")
    print(f"🌐 Reminder time (UTC): {reminder_utc}")
    print(f"⏱️  Current time (UTC): {timezone.now()}")
    
    return reminder_utc

def get_google_access_token(google_account):
    """Get a fresh access token using the refresh token"""
    if not google_account.refresh_token:
        print("❌ No refresh token available")
        return None
        
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": google_account.refresh_token,
        "grant_type": "refresh_token",
    }
    
    try:
        response = requests.post(google_account.token_uri, data=data)
        result = response.json()
        
        if response.status_code == 200:
            access_token = result.get("access_token")
            print(f"✅ Got new access token: {access_token[:20]}...")
            return access_token
        else:
            print(f"❌ Token refresh failed: {result}")
            return None
    except Exception as e:
        print(f"❌ Exception refreshing token: {e}")
        return None

def create_booking(request,company_id,data=None):

    company = Company.objects.filter(id=company_id).first()
        
    if not company:
        return Response(
            {"error": "Company not found"}, 
            status=status.HTTP_404_NOT_FOUND
        )
    if data is None:
        data = request.data.copy()
    number = data.get('number')
    
    # Get timezone from params (e.g., "Asia/Dhaka" or "+06:00")
    timezone_str = request.query_params.get('timezone') or company.timezone or 'UTC'
    
    # Calculate UTC times for Google Calendar
    start_dt = None
    end_dt = None
    start_utc = None
    end_utc = None

    if 'start_time' in data:
        start_time_local = data['start_time']
        
        if isinstance(start_time_local, str):
            # Parse the datetime string
            try:
                start_dt = datetime.strptime(start_time_local, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # Try alternate format if needed
                try:
                    start_dt = datetime.strptime(start_time_local, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                     pass
        else:
            start_dt = start_time_local
        
        if start_dt:
            # Convert local time to UTC using utility function
            start_utc = local_to_utc(start_dt, timezone_str)
            print(f"DEBUG: create_booking - Input: {start_dt}, TZ: {timezone_str}, UTC: {start_utc}")
            
            # Update data with UTC time for DB saving
            data['start_time'] = start_utc
            calendar_start_utc = start_utc
            
    
    if 'end_time' in data:
        end_time_local = data['end_time']
        
        if isinstance(end_time_local, str):
            try:
                end_dt = datetime.strptime(end_time_local, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    end_dt = datetime.strptime(end_time_local, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    pass
        else:
            end_dt = end_time_local
        
        if end_dt:
            if timezone.is_naive(end_dt):
                end_aware = user_tz.localize(end_dt)
            else:
                end_aware = end_dt.astimezone(user_tz)
            
            end_utc = end_aware.astimezone(pytz.UTC)
            
            # Update data with UTC time for DB saving
            data['end_time'] = end_utc
            calendar_end_utc = end_utc

    # Check concurrent booking limit using UTC times (since DB is in UTC)
    if start_utc and end_utc:
        from .models import Booking
        # Check specific overlap: (StartA < EndB) and (EndA > StartB)
        current_bookings_count = Booking.objects.filter(
            company=company,
            start_time__lt=end_utc, 
            end_time__gt=start_utc
        ).count()
        
        if current_bookings_count >= company.concurrent_booking_limit:
            return Response(
                {"error": "Slot is already booked. Maximum concurrent bookings reached."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    # Create booking
    # Data now contains UTC times
    serializer = BookingSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    booking = serializer.save(company=company)
    
    # Create Google Calendar event
    google_account = GoogleCalendar.objects.filter(company=company).first()
    calendar_error = None
    
    if google_account:
        try:
            access_token = get_google_access_token(google_account)
            if not access_token:
                calendar_error = "Unable to get access token from refresh token"
                print(f"❌ Google Calendar Error: {calendar_error}")
            else:
                # Use the calculated UTC times for Google Calendar
                # We send timeZone="UTC" because we already converted to UTC
                
                start_val = calendar_start_utc if calendar_start_utc else booking.start_time
                end_val = calendar_end_utc if calendar_end_utc else (booking.end_time or booking.start_time)
                
                # Prepare event data
                event_data = {
                    "summary": booking.title,
                    "description": booking.notes or "",
                    "start": {
                        "dateTime": start_val.isoformat(),
                        "timeZone": "UTC"
                    },
                    "end": {
                        "dateTime": end_val.isoformat(),
                        "timeZone": "UTC"
                    },
                    "location": booking.location or "",
                    "attendees": [{"email": booking.client}] if booking.client else [],
                }
                
                print(f"📅 Creating Google Calendar event...")
                print(f"   Timezone: UTC (Converted from {timezone_str})")
                print(f"   Start: {start_val.isoformat()}")
                
                headers = {"Authorization": f"Bearer {access_token}"}
                response = requests.post(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers=headers,
                    json=event_data
                )
                
                print(f"   Response Status: {response.status_code}")
                
                if response.status_code in [200, 201]:
                    event = response.json()
                    booking.google_event_id = event.get("id")
                    booking.event_link = event.get("htmlLink")
                    booking.save()
                    print(f"✅ Google Calendar event created: {booking.event_link}")
                else:
                    calendar_error = response.json()
                    print(f"❌ Google Calendar API Error: {calendar_error}")
                    
        except Exception as e:
            calendar_error = str(e)
            print(f"❌ Exception creating Google Calendar event: {e}")
    else:
        print("ℹ️ No Google Account found for this company")
    
    # Send confirmation SMS
    if number:
        # Convert UTC time back to user local time for display using utility function
        local_start = utc_to_local(booking.start_time, timezone_str)
        
        text_message = (
            f"Booking Confirmed ✓\n"
            f"Title: {booking.title}\n"
            f"Time: {local_start.strftime('%d %b %Y, %I:%M %p')}\n"
            f"Location: {booking.location or 'N/A'}\n"
            f"Event Link: {booking.event_link or 'N/A'}\n"
            f"\n⏰ Reminder: 1 hour before"
        )
        
        send_via_webhook_style(number, text_message)
    return booking

