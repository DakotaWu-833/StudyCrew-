from django.urls import path
from . import public_views

app_name = "public_operations"
urlpatterns = [
    path("help/", public_views.help_page, name="help"),
    path("help/verify/<uuid:identifier>/<str:token>/", public_views.contact_verify, name="verify_contact"),
    path("privacy/", public_views.privacy_page, name="privacy"),
    path("status/", public_views.status_page, name="status"),
    path("health/", public_views.health_page, name="health"),
    path("delivery/events/", public_views.mail_webhook, name="mail_event"),
]
