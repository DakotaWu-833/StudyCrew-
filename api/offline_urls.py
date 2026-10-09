from django.urls import path
from .offline_views import sync_task

app_name = "offline_sync"
urlpatterns = [path("tasks/<uuid:task_id>/sync/", sync_task, name="sync-task")]
