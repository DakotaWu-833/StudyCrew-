from django.urls import path
from . import views

app_name = "learning_exchange"
urlpatterns = [
    path("sample/", views.sample),
    path("projects/<uuid:project_id>/", views.overview),
    path("projects/<uuid:project_id>/preview/", views.preview),
    path("projects/<uuid:project_id>/import/", views.confirm),
    path("projects/<uuid:project_id>/export/", views.export),
    path("projects/<uuid:project_id>/batches/<uuid:batch_id>/export/", views.export),
]
