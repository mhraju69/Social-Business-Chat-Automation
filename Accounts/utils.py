import logging,requests
from .models import *
from Finance.models import *
from django.utils import timezone
from django.conf import settings
logger = logging.getLogger(__name__)
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from Others.models import UserSession

def send_otp(email, task=None):
    if not email:
        raise ValueError("Email is required.")

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return {"success": False, "message": "User not found."}
    

    otp = OTP.objects.filter(user__email=email).first()
    if otp and not otp.is_expired():
        return {"success": False, "message": "An OTP has already sent. Please check your email."}
    

    # Remove old OTP if exists
    OTP.objects.filter(user=user).delete()

    # Generate new OTP
    otp = OTP.generate_otp(user)

    subject = "OTP Verification"

    # Render HTML template (templates/email/otp_email.html)
    html_content = render_to_string("email/otp_email.html", {
        "otp": otp.otp,
        "task": task or "Verification",
        "user": user.name or user.email,
    })

    # Plain text fallback (for clients that don’t support HTML)
    text_content = f"""
        TALK FUSION - OTP Verification

        Hello {user.name or user.email}!

        Your verification code for {task or 'account verification'} is:

        {otp.otp}

        This code will expire in 3 minutes for security reasons.

        Enter this code in the verification page to complete your {task or 'verification'} process.

        SECURITY NOTICE:
        - Never share this code with anyone
        - Talk Fusion will never ask for your password
        - If you didn't request this, please ignore this email

        Having trouble? Contact support: support@talkfusion.com

        © 2024 Talk Fusion. All rights reserved.
        """

    msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [email])
    msg.attach_alternative(html_content, "text/html")
    msg.send()

    return {"success": True, "message": f"OTP sent successfully for {task or 'Verification'}."}

def verify_otp(email, otp_code):
    try:
        otp_obj = OTP.objects.filter(user__email=email).latest('created_at')
        
    except OTP.DoesNotExist:
        return {"success": False, "message": "Invalid OTP or email."}

    # Check expiry
    if otp_obj.is_expired():
        return {"success": False, "message": "OTP has expired."}
    
    if otp_code != otp_obj.otp:
            return {"success": False, "message": "Invalid OTP or email."}
    # OTP verified, activate user & delete OTP
    user = otp_obj.user
    user.is_active = True
    user.save()
    otp_obj.delete()

    return {"success": True, "message": "OTP verified successfully."}

def send_employee_invitation(email, password, company_name,roles):
        subject = f"Welcome to {company_name} - Your Talk Fusion Employee Account"
        
        # Render HTML template
        html_content = render_to_string("email/employee_invitation.html", {
            "email": email,
            "password": password,
            "company_name": company_name,
            "roles": roles,
            "login_url": "https://yourdomain.com/login"  # Replace with actual login URL
        })

        # Plain text fallback
        text_content = f"""
        Welcome to Talk Fusion!

        You've been invited to join {company_name} as an employee.

        Your login credentials:
        Email: {email}
        Temporary Password: {password}

        Login URL: https://yourdomain.com/login

        Important:
        - Change your password after first login
        - Never share your credentials
        - Contact support if you need help

        © 2024 Talk Fusion. All rights reserved.
        """

        msg = EmailMultiAlternatives(
            subject, 
            text_content, 
            settings.DEFAULT_FROM_EMAIL, 
            [email]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def get_location(ip):
    try:
        url = f"http://ip-api.com/json/{ip}"
        response = requests.get(url).json()
        return f"{response['city']}, {response['country']}"
    except:
        return "Unknown"
        
def check_plan(company):
    plan = Subscriptions.objects.filter(company=company).first()
    if not plan or not plan.active or plan.end < timezone.now():
        return False
    return True

def get_company_user(user):
    """
    If user is employee, return the company owner (user).
    If user is owner/admin, return the user itself.
    """
    if getattr(user, 'role', '') == 'employee':
        try:
            # Match by email since User and Employee are linked by email
            # Use iexact for case-insensitive matching
            employee = Employee.objects.get(email__iexact=user.email)
            return employee.company.user
        except Employee.DoesNotExist:
            return None
    return user

def generate_session(request, user, access):
    # Try to parse User Agent and Client Info
    try:
        ua_string = request.META.get('HTTP_USER_AGENT', '')
        print(f"☘️☘️☘️☘️☘️☘️User Agent: {ua_string}")
        
        details = ua_string.split(",")
        device = f"{details[0].strip()} {details[1].strip()}"
        platform = details[2].strip()
        
    except :
        
        ua_string = request.META.get('HTTP_USER_AGENT', '')
        client_info_str = request.META.get('HTTP_X_CLIENT_INFO', '')
        
        device = "Unknown"
        platform = "Unknown"
        
        try:
            if client_info_str:
                import json
                client_data = json.loads(client_info_str)
                p_platform = client_data.get('platform', '')
                platform = p_platform if p_platform else "Unknown"
        except Exception as e:
            print(f"Error parsing HTTP_X_CLIENT_INFO: {e}")

        try:
            from user_agents import parse
            user_agent = parse(ua_string)
            
            d_family = user_agent.device.family
            if d_family == "Other":
                d_family = "Desktop" # Or just Generic
            
            device = f"{d_family} / {user_agent.browser.family} {user_agent.browser.version_string}"
            platform = f"{user_agent.os.family} {user_agent.os.version_string}"
            
        except ImportError:
            pass
        except Exception as e:
            print(f"Error parsing User Agent with lib: {e}")
            try:
                if "Windows" in ua_string:
                    platform = "Windows"
                    device = "Desktop"
                elif "Android" in ua_string:
                    platform = "Android"
                    device = "Mobile"
                elif "iPhone" in ua_string:
                    platform = "iOS"
                    device = "Mobile"
            except:
                pass


    session = UserSession.objects.create(
        user=user,
        device=device,
        browser=platform,
        ip_address=get_client_ip(request),
        token=str(access['jti']),
        location=get_location(get_client_ip(request))
    )

    # Trigger AI Analysis Pre-warming
    try:
        # Check if user has a company attributed to them
        if hasattr(user, 'company'):
            from Ai.tasks import analyze_company_data_task
            # Run in background
            analyze_company_data_task.delay(user.company.id)
    except Exception as e:
        # logging.error(f"Failed to trigger analysis task: {e}")
        print(f"Failed to trigger analysis task: {e}")


    return session
