import os
import django
import sys

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set your Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Talkfusion.settings")  # adjust to your project name

# Initialize Django
django.setup()

from Accounts.models import User,Service
from Others.models import KnowledgeBase , AITrainingFile ,Booking , OpeningHours


# print(KnowledgeBase.objects.filter(user__id=1).values())
# print(AITrainingFile.objects.filter(company__id=2).values())
# print(AITrainingFile.objects.all().values())
