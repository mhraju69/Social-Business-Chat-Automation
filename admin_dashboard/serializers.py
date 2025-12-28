from rest_framework import serializers
from Accounts.models import User, Company
from Finance.models import Payment
from admin_dashboard.models import AdminActivity, UserPlanRequest

class SimpleUserSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    class Meta:
        model = User
        fields = ['id', 'name', 'role', 'email', 'company_name', 'is_active']

class  AdminCompanySerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    billing_contact = serializers.CharField(source='user.name', read_only=True)
    billing_email = serializers.EmailField(source='user.email', read_only=True)
    joining_date = serializers.DateTimeField(source='user.date_joined', read_only=True)
    total_paid = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)

    class Meta:
        model = Company
        fields = ['id', 'name', 'email', 'billing_contact', 'billing_email', 'joining_date', 'invoice', 'total_paid', 'is_active']

    def get_total_paid(self, obj):
        # return obj.invoices.filter(status='paid').aggregate(total=models.Sum('amount'))['total'] or 0
        return None
    
    def get_invoice(self, obj):
        payment = Payment.objects.filter(company=obj).first()
        invoice_url = payment.invoice_url if payment else None
        if invoice_url:
            return (
                {
                    'name': 'Sample Invoice',
                    'url': invoice_url,
                }
            )
        return (
                {
                    'name': 'Sample Invoice',
                    'url': invoice_url,
                }
            )
class AdminTeamMemberSerializer(serializers.ModelSerializer):
    new_user_added = serializers.SerializerMethodField()
    invoices_download = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ['id', 'name', 'image', 'role', 'email', 'is_active', 'last_login', 'new_user_added', 'invoices_download']
    
    def get_new_user_added(self, obj): 
        activity = AdminActivity.objects.get_or_create(user=obj)[0]
        return activity.new_user_added

    def get_invoices_download(self, obj):
        activity = AdminActivity.objects.get_or_create(user=obj)[0]
        return activity.invoices_download

class ChannelOverviewSerializer(serializers.ModelSerializer):
    # id = serializers.IntegerField()
    # name = serializers.CharField()
    status_message = serializers.SerializerMethodField()
    whatsapp = serializers.SerializerMethodField()
    facebook = serializers.SerializerMethodField()
    instagram = serializers.SerializerMethodField()
    class Meta:
        model = Company
        fields = ['id', 'name', 'status_message', 'whatsapp', 'facebook', 'instagram']

    def get_whatsapp(self, obj):
        whatsapp_channel = obj.user.chat_profiles.filter(platform='whatsapp').first()
        if whatsapp_channel:
            last_used = None
            return {
                'id': whatsapp_channel.id,
                'status': "sample status",
                'last_used': last_used,
                'messages_today':0
            }
        return None
    
    def get_facebook(self, obj):
        facebook_channel = obj.user.chat_profiles.filter(platform='facebook').first()
        if facebook_channel:
            last_used = None
            return {
                'id': facebook_channel.id,
                'status': "sample status",
                'last_used': last_used,
                'messages_today':0
            }
        return None
    
    def get_instagram(self, obj):
        instagram_channel = obj.user.chat_profiles.filter(platform='instagram').first()
        if instagram_channel:
            last_used = None
            return {
                'id': instagram_channel.id,
                'status': "sample status",
                'last_used': last_used,
                'messages_today':0
            }
        return None
    
    def get_status_message(self, obj):
        return "Healthy"

class UserPlanRequestSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    user = SimpleUserSerializer(read_only=True)
    class Meta:
        model = UserPlanRequest
        fields = ['id', 'user', 'email', 'msg_limit', 'user_limit', 'token_limit']
    