from django.urls import path
from . import views

app_name = "knowledge"
urlpatterns = [
    path("projects/<uuid:project_id>/", views.capabilities, name="capabilities"),
    path("projects/<uuid:project_id>/search/", views.search, name="search"),
    path("projects/<uuid:project_id>/ask/", views.ask, name="ask"),
]
