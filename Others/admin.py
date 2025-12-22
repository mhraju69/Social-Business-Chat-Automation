from django.contrib import admin
from .models import *
from unfold.admin import ModelAdmin
# Register your models here.

admin.site.register(Booking,ModelAdmin)
admin.site.register(OpeningHours,ModelAdmin)
admin.site.register(Alert,ModelAdmin)
admin.site.register(KnowledgeBase,ModelAdmin)
admin.site.register(SupportTicket,ModelAdmin)
admin.site.register(GoogleCalendar,ModelAdmin)
admin.site.register(UserSession,ModelAdmin)
admin.site.register(AITrainingFile,ModelAdmin)

