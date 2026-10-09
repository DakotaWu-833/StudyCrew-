from django.urls import path
from . import views

app_name = "recruiting"
urlpatterns = [
    path("overview/", views.overview),
    path("recommendations/", views.recommendations),
    path("listings/", views.listings),
    path("listings/<uuid:listing_id>/", views.detail),
    path("listings/<uuid:listing_id>/close/", views.close),
    path("listings/<uuid:listing_id>/reopen/", views.reopen),
    path("listings/<uuid:listing_id>/apply/", views.apply),
    path("listings/<uuid:listing_id>/applications/", views.applications),
    path("listings/<uuid:listing_id>/bookmark/", views.bookmark),
    path("listings/<uuid:listing_id>/report/", views.report),
    path("applications/<uuid:application_id>/decision/", views.decision),
    path("applications/<uuid:application_id>/withdraw/", views.withdraw),
    path("reports/", views.reports),
    path("reports/<uuid:report_id>/resolve/", views.resolve_report),
]

