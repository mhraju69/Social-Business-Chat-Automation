from django.contrib import admin
from .models import *
from unfold.admin import ModelAdmin
# Register your models here.

@admin.register(InstagramProfile)
class IgAdmin(ModelAdmin):
    pass

@admin.register(Incoming)
class IncomingAdmin(ModelAdmin):
    readonly_fields = ("receiver","from_user_id","text")

@admin.register(Outgoing)
class OutgoingAdmin(ModelAdmin):
    readonly_fields = ("sender","to_user_id","text")
