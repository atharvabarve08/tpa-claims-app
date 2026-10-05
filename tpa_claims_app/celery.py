"""
Celery application for tpa_claims_app.

This file's only job is to create the Celery `app` object and point it at
Django's settings, so that `celery -A tpa_claims_app worker` can find it and
autodiscover the tasks defined in claims/tasks.py.
"""

import os

from celery import Celery

# Tell Celery where your Django settings live before anything else runs.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tpa_claims_app.settings")

app = Celery("tpa_claims_app")

# Read CELERY_* settings from settings.py (that's what namespace="CELERY" means —
# e.g. CELERY_BROKER_URL, CELERY_RESULT_BACKEND).
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatically find tasks.py inside every app listed in INSTALLED_APPS —
# this is how it picks up ingest_claim, validate_claim, price_claim, etc.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    """Quick sanity-check task — run app.send_task('tpa_claims_app.celery.debug_task') or see below."""
    print(f"Request: {self.request!r}")