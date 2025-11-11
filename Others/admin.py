from django.contrib import admin
from .models import *
from unfold.admin import ModelAdmin
# Register your models here.

admin.site.register(Booking,ModelAdmin)
admin.site.register(ChatBot,ModelAdmin)
