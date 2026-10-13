from django.conf import settings
from django.core.checks import Error, register
import shutil
from .storage import limits, scan_required


@register(deploy=True)
def private_upload_deploy_checks(app_configs, **kwargs):
    errors = []
    if getattr(settings, "ENVIRONMENT", "development") == "production":
        if not scan_required() or not str(getattr(settings, "PROJECT_FILES_CLAMSCAN", "")).strip():
            errors.append(Error("Production private uploads require malware scanning and PROJECT_FILES_CLAMSCAN.", id="documents_store.E001"))
        elif not shutil.which(str(settings.PROJECT_FILES_CLAMSCAN)):
            errors.append(Error("The configured malware scanner executable is unavailable on this host.", id="documents_store.E003"))
    if any(value <= 0 for value in limits().values()):
        errors.append(Error("Private upload quotas must be positive.", id="documents_store.E002"))
    return errors
