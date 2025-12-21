from django.db import models

class AdminActivity(models.Model):
    user = models.ForeignKey('Accounts.User', on_delete=models.CASCADE)
    new_user_added = models.IntegerField(default=0)
    invoices_download = models.DateTimeField(null=True, blank=True)
