from django.urls import path
from . import views

app_name = "productivity"
urlpatterns = [
    path("timer/", views.active_timer, name="active-timer"),
    path("timer/discard/", views.discard_timer, name="discard-timer"),
    path("projects/<uuid:project_id>/workload/", views.workload, name="workload"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/", views.task_overview, name="task-overview"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/schedules/", views.create_schedule, name="create-schedule"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/schedules/<uuid:schedule_id>/stop/", views.stop_schedule, name="stop-schedule"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/timer/start/", views.start_timer, name="start-timer"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/timer/stop/", views.stop_timer, name="stop-timer"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/time/", views.add_manual, name="add-manual"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/time/<uuid:entry_id>/", views.correct_entry, name="correct-entry"),
    path("projects/<uuid:project_id>/tasks/<uuid:task_id>/time/<uuid:entry_id>/discard/", views.delete_entry, name="discard-entry"),
]
