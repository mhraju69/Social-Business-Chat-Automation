import random
from django.db import models
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import BaseUserManager, AbstractBaseUser, PermissionsMixin

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    ROLE = (('user', 'User'),('admin', 'Admin'),)
    name = models.CharField(max_length=200, blank=True, null=True,verbose_name="User Name")
    email = models.EmailField(max_length=255,unique=True,verbose_name="User Email")
    image = models.ImageField(upload_to='profile_images/', blank=True, null=True,) #storage=MediaCloudinaryStorage()
    phone = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=10, choices=ROLE, default='user',verbose_name="User Role")
    dob = models.DateField(blank=True, null=True,verbose_name="Date of Birs")
    is_active = models.BooleanField(default=False,verbose_name="Active User")
    is_staff = models.BooleanField(default=False,verbose_name="Staff User")  
    is_superuser = models.BooleanField(default=False,verbose_name="Super User")  
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name="Joining Date")
    block = models.BooleanField(default=False,verbose_name="Suspend User")

    objects = UserManager()
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email
        
    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith('pbkdf2_sha256$'):
            self.set_password(self.password)
        if self.role == 'admin':
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)

class Company(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='company'
    )
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    open = models.TimeField(blank=True, null=True)
    close = models.TimeField(blank=True, null=True)
    is_24_hours_open = models.BooleanField(default=False)

    address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    # Map preview could be integrated later via coordinates
    latitude = models.CharField(max_length=100, blank=True, null=True)
    longitude = models.CharField(max_length=100, blank=True, null=True)

    system_language = models.CharField(max_length=50, default='English')
    # Dynamic service list
    services = models.JSONField(default=list, blank=True)  # e.g. [{"name": "SEO Setup", "price": 49.99}]

    # Tone & Personality
    formality_level = models.PositiveIntegerField(default=5)  # 1–10 scale

    # AI training
    training_files = models.FileField(upload_to='ai_training/', blank=True, null=True)

    # Website link
    website = models.URLField(blank=True, null=True)

    # Company summary
    summary = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    refresh_token = models.TextField(blank=True, null=True)  # For Google Calendar integration

    def __str__(self):
        return self.name
     
class OTP(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        related_name='user_otp',  
        on_delete=models.CASCADE
    )
    otp = models.CharField(max_length=6,verbose_name="OTP Code")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OTP for: {self.user}."

    @staticmethod
    def generate_otp(user):
        otp_code = str(random.randint(1000, 9999))
        return OTP.objects.create(user=user, otp=otp_code)

    def is_expired(self):
        return self.created_at + timedelta(minutes=3) < timezone.now()

