from django.contrib import admin
from .models import *
from unfold.admin import ModelAdmin
# Register your models here.

@admin.register(WhatsAppProfile)
class WPAdmin(ModelAdmin):
    pass
@admin.register(WhatsAppClient)
class WPCAdmin(ModelAdmin):
    pass

@admin.register(Incoming)
class IncomingAdmin(ModelAdmin):
    pass

@admin.register(Outgoing)
class OutgoingAdmin(ModelAdmin):
    pass
@admin.register(WPRoom)
class RoomAdmin(ModelAdmin):
    pass
