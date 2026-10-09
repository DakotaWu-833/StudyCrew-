from datetime import timedelta
from math import ceil

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from config.serializers import EmptyActionSerializer
from meetings.models import Meeting
from projects.policies import require_project_member
from tasks.models import Task

from .calendar import render_calendar
from .models import CalendarSubscription, ContributionClaim, MeetingRecord, PollOption, SchedulingPoll
from . import selectors, serializers, services


def validated(data, schema):
    serializer = schema(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def member_object(model, pk, user):
    row = get_object_or_404(model.objects.select_related("project"), pk=pk)
    require_project_member(user, row.project)
    return row


def current_meeting(pk, user):
    return member_object(Meeting, pk, user)


def current_record(pk, user):
    meeting = current_meeting(pk, user)
    # GET never creates a record, and a mutation must explicitly initialise it.
    return meeting, get_object_or_404(MeetingRecord.objects.select_related("meeting__project"), meeting=meeting)


def calendar_response(data, *, details=True):
    response = HttpResponse(render_calendar(data["events"], include_details=details), content_type="text/calendar; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Content-Disposition"] = 'attachment; filename="studycrew.ics"'
    response["X-Calendar-Truncated"] = "true" if data["truncated"] else "false"
    return response


def paged(rows, page, size=25):
    count = rows.count()
    pages = max(1, ceil(count / size))
    page = min(page, pages)
    return rows[(page - 1) * size:page * size], {"page": page, "pages": pages, "count": count}


class CalendarView(APIView):
    @extend_schema(parameters=[serializers.CalendarQuery], responses=OpenApiTypes.OBJECT, operation_id="coordination_calendar_get")
    def get(self, request):
        data = validated(request.query_params, serializers.CalendarQuery)
        project = selectors.project_for_user(project_id=data["project"], user=request.user) if data.get("project") else None
        return Response(selectors.calendar_events(user=request.user, project=project, range_start=data["range_start"], range_end=data["range_end"]))


class CalendarExportView(CalendarView):
    @extend_schema(parameters=[serializers.CalendarQuery], responses={(200, "text/calendar"): OpenApiTypes.BINARY}, operation_id="coordination_calendar_export_get")
    def get(self, request):
        data = validated(request.query_params, serializers.CalendarQuery)
        project = selectors.project_for_user(project_id=data["project"], user=request.user) if data.get("project") else None
        return calendar_response(selectors.calendar_events(user=request.user, project=project, range_start=data["range_start"], range_end=data["range_end"]))


def subscription_data(row):
    return {"id": str(row.id), "project_id": str(row.project_id) if row.project_id else None, "include_details": row.include_details, "revoked_at": row.revoked_at, "expires_at": row.expires_at, "created_at": row.created_at}


class SubscriptionsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT, operation_id="coordination_subscriptions_get")
    def get(self, request):
        return Response({"subscriptions": [subscription_data(row) for row in CalendarSubscription.objects.filter(user=request.user).order_by("-created_at")[:100]]})

    @extend_schema(request=serializers.SubscriptionWrite, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_subscriptions_post")
    def post(self, request):
        data = validated(request.data, serializers.SubscriptionWrite)
        project = selectors.project_for_user(project_id=data["project"], user=request.user) if data.get("project") else None
        row, token = services.issue_subscription(actor=request.user, project=project, include_details=data["include_details"])
        return Response(dict(subscription_data(row), feed_url=request.build_absolute_uri(f"/api/v1/coordination/subscriptions/feed/{token}/")), status=201)


class SubscriptionRotateView(APIView):
    @extend_schema(request=EmptyActionSerializer, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_subscription_rotate_post")
    def post(self, request, pk):
        validated(request.data, EmptyActionSerializer)
        current = get_object_or_404(CalendarSubscription, pk=pk, user=request.user)
        row, token = services.issue_subscription(actor=request.user, subscription=current)
        return Response(dict(subscription_data(row), feed_url=request.build_absolute_uri(f"/api/v1/coordination/subscriptions/feed/{token}/")), status=201)


class SubscriptionRevokeView(APIView):
    @extend_schema(request=EmptyActionSerializer, responses=OpenApiTypes.OBJECT, operation_id="coordination_subscription_revoke_post")
    def post(self, request, pk):
        validated(request.data, EmptyActionSerializer)
        row = get_object_or_404(CalendarSubscription, pk=pk, user=request.user)
        services.revoke_subscription(actor=request.user, subscription=row)
        return Response(subscription_data(row))


class FeedIPThrottle(AnonRateThrottle):
    rate = "120/hour"


class SubscriptionFeedView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [FeedIPThrottle]

    @extend_schema(auth=[], responses={(200, "text/calendar"): OpenApiTypes.BINARY}, operation_id="coordination_subscription_feed_get")
    def get(self, request, token):
        row = services.consume_subscription(token)
        today = timezone.localdate()
        data = selectors.calendar_events(user=row.user, project=row.project, range_start=today - timedelta(days=7), range_end=today + timedelta(days=180))
        return calendar_response(data, details=row.include_details)


class AvailabilityView(APIView):
    @extend_schema(parameters=[serializers.AvailabilityQuery], responses=OpenApiTypes.OBJECT, operation_id="coordination_availability_get")
    def get(self, request):
        data = validated(request.query_params, serializers.AvailabilityQuery)
        project = selectors.project_for_user(project_id=data["project"], user=request.user)
        return Response(selectors.availability_for_project(user=request.user, project=project, week_start=data["week_start"]))

    @extend_schema(request=serializers.AvailabilityWrite, responses=OpenApiTypes.OBJECT, operation_id="coordination_availability_put")
    def put(self, request):
        data = validated(request.data, serializers.AvailabilityWrite)
        project = selectors.project_for_user(project_id=data.pop("project"), user=request.user)
        row = services.save_availability(actor=request.user, project=project, **data)
        return Response({"slots": row.slots, "time_zone": row.time_zone})


class PollsView(APIView):
    @extend_schema(parameters=[serializers.PagedProjectQuery], responses=OpenApiTypes.OBJECT, operation_id="coordination_polls_get")
    def get(self, request):
        data = validated(request.query_params, serializers.PagedProjectQuery)
        project = selectors.project_for_user(project_id=data["project"], user=request.user)
        rows = SchedulingPoll.objects.filter(project=project).prefetch_related("options__votes")
        rows, pagination = paged(rows, data["page"])
        return Response({"polls": [selectors.poll_data(row, request.user) for row in rows], "truncated": False, **pagination})

    @extend_schema(request=serializers.PollWrite, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_polls_post")
    def post(self, request):
        data = validated(request.data, serializers.PollWrite)
        project = selectors.project_for_user(project_id=data.pop("project"), user=request.user)
        row = services.create_poll(actor=request.user, project=project, **data)
        return Response(selectors.poll_data(row, request.user), status=201)


class VoteView(APIView):
    @extend_schema(request=serializers.VoteWrite, responses=OpenApiTypes.OBJECT, operation_id="coordination_vote_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.VoteWrite)
        option = get_object_or_404(PollOption.objects.select_related("poll__project"), pk=pk)
        require_project_member(request.user, option.poll.project)
        services.vote_option(actor=request.user, option=option, **data)
        return Response(selectors.poll_data(option.poll, request.user))


class ClosePollView(APIView):
    @extend_schema(request=serializers.PollClose, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_close_poll_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.PollClose)
        poll = member_object(SchedulingPoll, pk, request.user)
        meeting = services.close_poll(actor=request.user, poll=poll, **data)
        return Response(selectors.meeting_data(meeting, request.user), status=201)


class CancelPollView(APIView):
    @extend_schema(request=EmptyActionSerializer, responses=OpenApiTypes.OBJECT, operation_id="coordination_cancel_poll_post")
    def post(self, request, pk):
        validated(request.data, EmptyActionSerializer)
        poll = member_object(SchedulingPoll, pk, request.user)
        poll = services.cancel_poll(actor=request.user, poll=poll)
        return Response(selectors.poll_data(poll, request.user))


class MeetingRecordsView(APIView):
    @extend_schema(parameters=[serializers.PagedProjectQuery], responses=OpenApiTypes.OBJECT, operation_id="coordination_meeting_records_get")
    def get(self, request):
        data = validated(request.query_params, serializers.PagedProjectQuery)
        project = selectors.project_for_user(project_id=data["project"], user=request.user)
        rows = Meeting.objects.filter(project=project).order_by("-starts_at", "id")
        rows, pagination = paged(rows, data["page"])
        members = project.memberships.select_related("user__profile").all()
        return Response({"meetings": [selectors.meeting_data(row, request.user) for row in rows], "truncated": False, **pagination, "members": [dict(selectors.member_identity(row.user), active=row.removed_at is None and row.user.is_active) for row in members]})


class MeetingRecordView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT, operation_id="coordination_meeting_record_get")
    def get(self, request, pk):
        return Response(selectors.meeting_data(current_meeting(pk, request.user), request.user))

    @extend_schema(request=serializers.RecordWrite, responses=OpenApiTypes.OBJECT, operation_id="coordination_meeting_record_put")
    def put(self, request, pk):
        data = validated(request.data, serializers.RecordWrite)
        meeting = current_meeting(pk, request.user)
        services.save_meeting_record(actor=request.user, meeting=meeting, **data)
        return Response(selectors.meeting_data(meeting, request.user))


class ConfirmMinutesView(APIView):
    @extend_schema(request=serializers.ConfirmationWrite, responses=OpenApiTypes.OBJECT, operation_id="coordination_confirm_minutes_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.ConfirmationWrite)
        meeting, record = current_record(pk, request.user)
        services.confirm_minutes(actor=request.user, record=record, **data)
        return Response(selectors.meeting_data(meeting, request.user))


class AttendanceView(APIView):
    @extend_schema(request=serializers.AttendanceWrite, responses=OpenApiTypes.OBJECT, operation_id="coordination_attendance_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.AttendanceWrite)
        meeting, record = current_record(pk, request.user)
        services.record_attendance(actor=request.user, record=record, **data)
        return Response(selectors.meeting_data(meeting, request.user))


class MeetingActionView(APIView):
    @extend_schema(request=serializers.ActionWrite, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_meeting_action_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.ActionWrite)
        meeting, record = current_record(pk, request.user)
        services.add_action(actor=request.user, record=record, **data)
        return Response(selectors.meeting_data(meeting, request.user), status=201)


class RepeatMeetingView(APIView):
    @extend_schema(request=serializers.RepeatWrite, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_repeat_meeting_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.RepeatWrite)
        meeting = current_meeting(pk, request.user)
        series = services.repeat_meeting(actor=request.user, meeting=meeting, **data)
        return Response({"id": str(series.id), "occurrence_ids": series.occurrence_ids, "time_zone": series.time_zone}, status=201)


class ClaimsView(APIView):
    @extend_schema(parameters=[serializers.EvidenceQuery], responses=OpenApiTypes.OBJECT, operation_id="coordination_claims_get")
    def get(self, request):
        data = validated(request.query_params, serializers.EvidenceQuery)
        project = selectors.project_for_user(project_id=data.pop("project"), user=request.user)
        return Response(selectors.claims_for_project(user=request.user, project=project, **data))

    @extend_schema(request=serializers.ClaimWrite, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_claims_post")
    def post(self, request):
        data = validated(request.data, serializers.ClaimWrite)
        project = selectors.project_for_user(project_id=data.pop("project"), user=request.user)
        task_id, previous_id = data.pop("task_id", None), data.pop("supersedes_id", None)
        task = get_object_or_404(Task, pk=task_id, project=project) if task_id else None
        previous = get_object_or_404(ContributionClaim, pk=previous_id, project=project) if previous_id else None
        claim = services.create_claim(actor=request.user, project=project, task=task, supersedes=previous, **data)
        return Response({"id": str(claim.id)}, status=201)


class ClaimResponseView(APIView):
    @extend_schema(request=serializers.ClaimResponse, responses=OpenApiTypes.OBJECT, operation_id="coordination_claim_response_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.ClaimResponse)
        row = member_object(ContributionClaim, pk, request.user)
        services.respond_claim(actor=request.user, claim=row, **data)
        return Response({"id": str(row.id)})


class ClaimReviewView(APIView):
    @extend_schema(request=serializers.ReviewWrite, responses={201: OpenApiTypes.OBJECT}, operation_id="coordination_claim_review_post")
    def post(self, request, pk):
        data = validated(request.data, serializers.ReviewWrite)
        row = member_object(ContributionClaim, pk, request.user)
        services.review_claim(actor=request.user, claim=row, **data)
        return Response({"id": str(row.id)}, status=201)


class ClaimWithdrawView(APIView):
    @extend_schema(request=EmptyActionSerializer, responses=OpenApiTypes.OBJECT, operation_id="coordination_claim_withdraw_post")
    def post(self, request, pk):
        validated(request.data, EmptyActionSerializer)
        row = member_object(ContributionClaim, pk, request.user)
        services.withdraw_claim(actor=request.user, claim=row)
        return Response({"id": str(row.id)})
