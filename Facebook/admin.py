from django.contrib import admin
from .models import *
from unfold.admin import ModelAdmin
# Register your models here.

@admin.register(FacebookProfile)
class FbAdmin(ModelAdmin):
    pass

@admin.register(Incoming)
class IncomingAdmin(ModelAdmin):
    pass
@admin.register(Outgoing)
class OutgoingAdmin(ModelAdmin):
    pass
@admin.register(FacebookClient)
class FacebookClientAdmin(ModelAdmin):
    pass

@admin.register(FBRoom)
class FBRAdmin(ModelAdmin):
    pass