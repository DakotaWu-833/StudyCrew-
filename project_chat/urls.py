from django.urls import path
from . import views

app_name = "project_chat"
urlpatterns = [
    path("projects/<uuid:project_id>/messages/", views.messages),
    path("projects/<uuid:project_id>/messages/<uuid:message_id>/remove/", views.remove),
    path("projects/<uuid:project_id>/presence/", views.presence),
]
