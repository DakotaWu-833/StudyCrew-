from django.urls import path
from . import views
from . import discussion_views as discussions

app_name = "operations"
urlpatterns = [
    path("projects/<uuid:project_id>/posts/", discussions.PostsView.as_view()),
    path("posts/<uuid:identifier>/", discussions.PostView.as_view()),
    path("posts/<uuid:identifier>/replies/", discussions.PostRepliesView.as_view()),
    path("posts/<uuid:identifier>/remove/", discussions.PostRemoveView.as_view()),
    path("posts/<uuid:identifier>/report/", discussions.PostReportView.as_view()),
    path("admin/post-reports/", discussions.PostReportsView.as_view()),
    path("admin/post-reports/<uuid:identifier>/resolve/", discussions.PostModerateView.as_view()),
    path("preferences/", views.PreferencesView.as_view()),
    path("project-mutes/", views.MutesView.as_view()),
    path("alerts/", views.AlertsView.as_view()),
    path("alerts/<uuid:identifier>/read/", views.AlertReadView.as_view()),
    path("deliveries/", views.DeliveriesView.as_view()),
    path("support/", views.TicketsView.as_view()),
    path("support/<uuid:identifier>/replies/", views.TicketRepliesView.as_view()),
    path("blocks/", views.BlocksView.as_view()),
    path("notices/", views.NoticesView.as_view()),
    path("notices/<uuid:identifier>/end/", views.NoticeEndView.as_view()),
    path("admin/summary/", views.AdminSummaryView.as_view()),
    path("admin/support/", views.AdminTicketsView.as_view()),
    path("admin/support/<uuid:identifier>/", views.AdminTicketView.as_view()),
    path("admin/contacts/", views.AdminContactsView.as_view()),
    path("admin/contacts/<uuid:identifier>/response/", views.AdminContactView.as_view()),
    path("admin/deliveries/", views.AdminDeliveriesView.as_view()),
    path("admin/deliveries/<uuid:identifier>/retry/", views.AdminRetryView.as_view()),
]
