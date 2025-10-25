from django.contrib import admin
from .models import Booking
from unfold.admin import ModelAdmin
# Register your models here.

admin.site.register(Booking,ModelAdmin)
