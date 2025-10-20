from django.db import models
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
# from cloudinary_storage.storage import MediaCloudinaryStorage
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
    name = models.CharField(max_length=200, blank=True, null=True,verbose_name="User Name")
    email = models.EmailField(max_length=255,unique=True,verbose_name="User Email")
    image = models.ImageField(upload_to='profile_images/', blank=True, null=True,) #storage=MediaCloudinaryStorage()
    phone = models.CharField(max_length=20, blank=True, null=True)
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
        super().save(*args, **kwargs)
