import os
from celery import Celery

# Django settings মডিউল লোড করা
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Talkfusion.settings')

# Celery app create
app = Celery('Talkfusion')

# Django settings থেকে celery config load করা
app.config_from_object('django.conf:settings', namespace='CELERY')

# সকল registered Django app থেকে tasks auto discover করা
app.autodiscover_tasks()
app.autodiscover_tasks(related_name='task')
