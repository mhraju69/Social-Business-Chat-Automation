from django.contrib import admin
from .models import *
from unfold.admin import ModelAdmin

# Register your models here.

admin.site.register(ChatProfile,ModelAdmin)
admin.site.register(ChatClient,ModelAdmin)
admin.site.register(ChatRoom,ModelAdmin)
admin.site.register(ChatMessage,ModelAdmin)
