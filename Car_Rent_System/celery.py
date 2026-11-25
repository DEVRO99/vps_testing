import os
from celery import Celery

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Car_Rent_System.settings")

# Create Celery application
app = Celery("Car_Rent_System")

# Read configuration from Django settings.py
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatically discover tasks.py in installed Django apps
app.autodiscover_tasks()
