from django.db import models

class AdminActivity(models.Model):
    user = models.ForeignKey('Accounts.User', on_delete=models.CASCADE)
    new_user_added = models.IntegerField(default=0)
    invoices_download = models.DateTimeField(null=True, blank=True)

class UserPlanRequest(models.Model):
    user = models.ForeignKey('Accounts.User', on_delete=models.CASCADE)
    msg_limit = models.IntegerField()
    user_limit = models.IntegerField()
    token_limit = models.IntegerField()
    is_approved = models.BooleanField(default=False)
    custom_plan = models.ForeignKey('Finance.Plan', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"Plan Request by {self.user.email}"