import os
import sys
import json

# Setup paths - Ensure Social-Business-Chat-Automation is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Setup Django (needed for models)
import django
from django.conf import settings
if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Talkfusion.settings')
    django.setup()

# Override Cache to use Local Memory instead of Redis (which might be down)
settings.CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

from Ai.data_analysis import analyze_company_data

def main():
    company_id = 2
    print(f"Running analysis for Company ID: {company_id}...")
    result = analyze_company_data(company_id)
    
    print("\n--- JSON OUTPUT ---")
    print(json.dumps(result, indent=2))
    print("-------------------")

if __name__ == "__main__":
    main()
