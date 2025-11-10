import logging
from .models import *
from django.conf import settings
logger = logging.getLogger(__name__)
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

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

