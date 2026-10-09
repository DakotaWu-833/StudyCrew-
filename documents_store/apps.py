from django.apps import AppConfig


class DocumentsStoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents_store"

    def ready(self):
        from . import checks  # noqa: F401
