import pytz
from datetime import datetime, timedelta
from django.utils import timezone


def get_today(user=None, timezone_name=None):
    tz_name = timezone_name or getattr(user, 'timezone', 'UTC')
    company_tz = pytz.timezone(tz_name)

    now_utc = timezone.now()
    now_local = now_utc.astimezone(company_tz)

    start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    start_utc = start_of_day.astimezone(pytz.UTC)
    end_utc = end_of_day.astimezone(pytz.UTC)

    return start_utc, end_utc
    