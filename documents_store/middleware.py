"""Bound private upload parsing before session authentication reads request.POST."""
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import JsonResponse

from .storage import limits


class BoundedPrivateUploadHandler(FileUploadHandler):
    def __init__(self, request=None, maximum=None):
        super().__init__(request)
        self.total = 0
        self.file_count = 0
        self.maximum = limits()["file_limit"] if maximum is None else maximum

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_count += 1
        if self.file_count > 1:
            self.request.private_upload_rejected = True
            raise StopUpload(connection_reset=True)

    def receive_data_chunk(self, raw_data, start):
        self.total += len(raw_data)
        if self.total > self.maximum:
            self.request.private_upload_rejected = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None


class PrivateUploadLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        private_file = request.path.startswith("/api/v1/files/")
        learning_file = request.path.startswith("/api/v1/learning-exchange/projects/") and request.path.endswith("/preview/")
        if (private_file or learning_file) and request.method == "POST":
            maximum = limits()["file_limit"] if private_file else 262144
            overhead = 65536 if private_file else 16384
            try:
                declared = int(request.META.get("CONTENT_LENGTH", "0") or "0")
            except ValueError:
                declared = -1
            if declared < 0 or declared > maximum + overhead:
                return JsonResponse({"error": {"code": "validation_error", "message": "Upload request exceeds the size limit."}}, status=413)
            request.upload_handlers.insert(0, BoundedPrivateUploadHandler(request, maximum=maximum))
        return self.get_response(request)
