from django.urls import path
from . import views

app_name = "knowledge"
urlpatterns = [
    path("projects/<uuid:project_id>/assistant/tasks/", views.approve_task, name="approve-task"),
    path("projects/<uuid:project_id>/assistant/", views.assistant, name="assistant"),
    path("projects/<uuid:project_id>/", views.capabilities, name="capabilities"),
    path("projects/<uuid:project_id>/search/", views.search, name="search"),
    path("projects/<uuid:project_id>/ask/", views.ask, name="ask"),
]
