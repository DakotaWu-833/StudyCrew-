from django.urls import path
from . import views

app_name = "documents_store"
urlpatterns = [
    path("projects/<uuid:project_id>/", views.project_files, name="project-files"),
    path("projects/<uuid:project_id>/trash/", views.trash, name="file-trash"),
    path("projects/<uuid:project_id>/documents/<uuid:document_id>/", views.document_detail, name="document-detail"),
    path("projects/<uuid:project_id>/documents/<uuid:document_id>/versions/", views.versions, name="document-versions"),
    path("projects/<uuid:project_id>/documents/<uuid:document_id>/download/", views.download, name="document-download"),
    path("projects/<uuid:project_id>/documents/<uuid:document_id>/preview/", views.preview, name="document-preview"),
    path("projects/<uuid:project_id>/documents/<uuid:document_id>/compare/", views.compare, name="document-compare"),
    path("projects/<uuid:project_id>/documents/<uuid:document_id>/restore/", views.restore, name="document-restore"),
]
