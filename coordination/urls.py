from django.urls import path

from . import views

app_name = "coordination"
urlpatterns = [
    path("calendar/", views.CalendarView.as_view(), name="calendar"),
    path("calendar/export/", views.CalendarExportView.as_view(), name="calendar-export"),
    path("subscriptions/", views.SubscriptionsView.as_view(), name="subscriptions"),
    path("subscriptions/<uuid:pk>/rotate/", views.SubscriptionRotateView.as_view(), name="subscription-rotate"),
    path("subscriptions/<uuid:pk>/revoke/", views.SubscriptionRevokeView.as_view(), name="subscription-revoke"),
    path("subscriptions/feed/<str:token>/", views.SubscriptionFeedView.as_view(), name="subscription-feed"),
    path("availability/", views.AvailabilityView.as_view(), name="availability"),
    path("polls/", views.PollsView.as_view(), name="polls"),
    path("poll-options/<uuid:pk>/vote/", views.VoteView.as_view(), name="poll-vote"),
    path("polls/<uuid:pk>/close/", views.ClosePollView.as_view(), name="poll-close"),
    path("polls/<uuid:pk>/cancel/", views.CancelPollView.as_view(), name="poll-cancel"),
    path("meeting-records/", views.MeetingRecordsView.as_view(), name="meeting-records"),
    path("meeting-records/<uuid:pk>/", views.MeetingRecordView.as_view(), name="meeting-record"),
    path("meeting-records/<uuid:pk>/confirm/", views.ConfirmMinutesView.as_view(), name="minutes-confirm"),
    path("meeting-records/<uuid:pk>/attendance/", views.AttendanceView.as_view(), name="attendance"),
    path("meeting-records/<uuid:pk>/actions/", views.MeetingActionView.as_view(), name="meeting-action"),
    path("meeting-records/<uuid:pk>/repeat/", views.RepeatMeetingView.as_view(), name="meeting-repeat"),
    path("claims/", views.ClaimsView.as_view(), name="claims"),
    path("claims/<uuid:pk>/respond/", views.ClaimResponseView.as_view(), name="claim-respond"),
    path("claims/<uuid:pk>/review/", views.ClaimReviewView.as_view(), name="claim-review"),
    path("claims/<uuid:pk>/withdraw/", views.ClaimWithdrawView.as_view(), name="claim-withdraw"),
]
