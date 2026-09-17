from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        # Importing registers drf-spectacular's authentication extension.
        from api import schema  # noqa: F401
