"""Session/MFA/CSRF-protected user and operational APIs."""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers
from config.serializers import EmptyActionSerializer
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.policies import require_site_moderator
from activity.models import Notification
from projects.models import Project
from projects.policies import require_project_member
from .models import ContactRequest, OperationAudit, OutboundMessage, ProjectMute, ServiceNotice, SupportTicket, UserBlock
from .selectors import alerts_for, current_notices, operations_summary, tickets_for
from .serializers import (AlertSerializer, BlockSerializer, BodySerializer, DeliverySerializer,
                          MuteSerializer, NoticeSerializer, PayloadSerializer, PreferenceSerializer,
                          ContactSerializer, ContactResponseSerializer, RetrySerializer, TicketSerializer, TicketUpdateSerializer)
from .services import (create_ticket, preferences_for, reply_to_ticket, resolve_ticket,
                       respond_to_contact, update_preferences)


def _page(request, rows, serializer, *, size=25):
    page = Paginator(rows, size).get_page(request.query_params.get("page", 1))
    return {"results": serializer(page.object_list, many=True).data,
            "total": page.paginator.count, "page": page.number,
            "page_size": size, "pages": page.paginator.num_pages}


PAGE_PARAMETER = OpenApiParameter("page", OpenApiTypes.INT, description="One-based page; 25 records per page.")

def _page_contract(name, row, *, unread=False):
    fields = {"results": row(many=True), "total": serializers.IntegerField(),
              "page": serializers.IntegerField(), "page_size": serializers.IntegerField(),
              "pages": serializers.IntegerField()}
    if unread:
        fields["count"] = serializers.IntegerField(help_text="Unread reminders across all pages.")
    return inline_serializer(name=name, fields=fields)


class PreferencesView(APIView):
    serializer_class = PreferenceSerializer

    def get(self, request):
        return Response(PreferenceSerializer(preferences_for(request.user)).data)

    def patch(self, request):
        serializer = PreferenceSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(PreferenceSerializer(update_preferences(request.user, serializer.validated_data)).data)


@extend_schema_view(get=extend_schema(responses=PayloadSerializer))
class MutesView(APIView):
    serializer_class = MuteSerializer

    def get(self, request):
        rows = ProjectMute.objects.filter(user=request.user, project__memberships__user=request.user, project__memberships__removed_at__isnull=True).distinct()
        return Response({"results": [{"project": row.project_id, "muted": row.muted} for row in rows]})

    def post(self, request):
        serializer = MuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = get_object_or_404(Project, pk=data["project"])
        require_project_member(request.user, project)
        row, _ = ProjectMute.objects.update_or_create(user=request.user, project=project, defaults={"muted": data["muted"]})
        return Response({"project": row.project_id, "muted": row.muted})


@extend_schema_view(get=extend_schema(parameters=[PAGE_PARAMETER], responses=_page_contract("AlertsViewPage", AlertSerializer, unread=True)))
class AlertsView(APIView):
    serializer_class = AlertSerializer

    def get(self, request):
        rows = alerts_for(request.user)
        return Response({**_page(request, rows.select_related("project").order_by("-created_at", "-id"), AlertSerializer),
                         "count": rows.filter(read_at__isnull=True).count()})

    @extend_schema(request=EmptyActionSerializer, responses=PayloadSerializer)
    def post(self, request):
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        now = timezone.now()
        alerts_for(request.user).filter(read_at__isnull=True).update(read_at=now)
        Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=now)
        return Response({"detail": "All notifications marked as read."})


class AlertReadView(APIView):
    serializer_class = AlertSerializer

    @extend_schema(request=EmptyActionSerializer)
    def patch(self, request, identifier):
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        alert = get_object_or_404(alerts_for(request.user), pk=identifier)
        alert.read_at = timezone.now()
        alert.save(update_fields=["read_at", "updated_at"])
        return Response(AlertSerializer(alert).data)


@extend_schema_view(get=extend_schema(parameters=[PAGE_PARAMETER], responses=_page_contract("DeliveriesViewPage", DeliverySerializer, unread=False)))
class DeliveriesView(APIView):
    serializer_class = DeliverySerializer

    def get(self, request):
        return Response(_page(request, OutboundMessage.objects.filter(user=request.user).order_by("-created_at", "-id"), DeliverySerializer))


@extend_schema_view(get=extend_schema(parameters=[PAGE_PARAMETER], responses=_page_contract("TicketsViewPage", TicketSerializer, unread=False)))
class TicketsView(APIView):
    serializer_class = TicketSerializer

    def get(self, request):
        return Response(_page(request, tickets_for(request.user).order_by("-created_at", "-id"), TicketSerializer))

    def post(self, request):
        serializer = TicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(TicketSerializer(create_ticket(request.user, serializer.validated_data)).data, status=201)


@extend_schema_view(post=extend_schema(responses=TicketSerializer))
class TicketRepliesView(APIView):
    serializer_class = BodySerializer

    def post(self, request, identifier):
        ticket = get_object_or_404(SupportTicket, pk=identifier)
        serializer = BodySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply_to_ticket(request.user, ticket, serializer.validated_data["body"])
        return Response(TicketSerializer(ticket).data)


@extend_schema_view(get=extend_schema(responses=PayloadSerializer))
class BlocksView(APIView):
    serializer_class = BlockSerializer

    def get(self, request):
        rows = UserBlock.objects.filter(user=request.user).select_related("blocked__profile")
        return Response({"results": [{"user_id": row.blocked_id, "display_name": row.blocked.profile.display_name} for row in rows]})

    def post(self, request):
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        target = get_object_or_404(User, pk=data["user_id"])
        if target.pk == request.user.pk:
            raise ValidationError("You cannot block yourself.")
        if not data["blocked"]:
            # Revoking an existing block must work even after a team closes or
            # a membership ends. It does not reveal another user's identity.
            UserBlock.objects.filter(user=request.user, blocked=target).delete()
            return Response({"user_id": target.pk, "blocked": False})
        # No arbitrary UUID lookup: the target must share a current project or
        # have sent an invitation to this user's verified email address.
        from projects.models import ProjectMembership, ProjectInvitation
        common = ProjectMembership.objects.active().filter(user=request.user).values_list("project_id", flat=True)
        shared = ProjectMembership.objects.active().filter(user=target, project_id__in=common).exists()
        invited = ProjectInvitation.objects.filter(invited_by=target, invited_email=request.user.email).exists()
        if not shared and not invited:
            raise PermissionDenied("This user is unavailable.")
        if data["blocked"]:
            UserBlock.objects.get_or_create(user=request.user, blocked=target)
        else:
            UserBlock.objects.filter(user=request.user, blocked=target).delete()
        return Response({"user_id": target.pk, "blocked": data["blocked"]})


@extend_schema_view(get=extend_schema(responses=OpenApiTypes.OBJECT))
class AdminSummaryView(APIView):
    serializer_class = PayloadSerializer

    def get(self, request):
        return Response(operations_summary(request.user))


@extend_schema_view(get=extend_schema(parameters=[PAGE_PARAMETER], responses=_page_contract("AdminTicketsViewPage", TicketSerializer, unread=False)))
class AdminTicketsView(APIView):
    serializer_class = TicketSerializer

    def get(self, request):
        require_site_moderator(request.user)
        return Response(_page(request, SupportTicket.objects.select_related("user__profile").prefetch_related("replies__author__profile").order_by("-updated_at", "-id"), TicketSerializer))


@extend_schema_view(get=extend_schema(parameters=[PAGE_PARAMETER], responses=_page_contract("AdminContactsViewPage", ContactSerializer, unread=False)))
class AdminContactsView(APIView):
    serializer_class = ContactSerializer

    def get(self, request):
        require_site_moderator(request.user)
        rows = ContactRequest.objects.filter(verified_at__isnull=False).order_by("-updated_at", "-id")
        return Response(_page(request, rows, ContactSerializer))


@extend_schema_view(post=extend_schema(responses=ContactSerializer))
class AdminContactView(APIView):
    serializer_class = ContactResponseSerializer

    def post(self, request, identifier):
        require_site_moderator(request.user)
        contact = get_object_or_404(ContactRequest, pk=identifier, verified_at__isnull=False)
        serializer = ContactResponseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ContactSerializer(respond_to_contact(request.user, contact, serializer.validated_data["response"])).data)


@extend_schema_view(patch=extend_schema(responses=TicketSerializer))
class AdminTicketView(APIView):
    serializer_class = TicketUpdateSerializer

    def patch(self, request, identifier):
        require_site_moderator(request.user)
        ticket = get_object_or_404(SupportTicket, pk=identifier)
        serializer = TicketUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(TicketSerializer(resolve_ticket(request.user, ticket, serializer.validated_data)).data)


@extend_schema_view(get=extend_schema(parameters=[PAGE_PARAMETER], responses=_page_contract("AdminDeliveriesViewPage", DeliverySerializer, unread=False)))
class AdminDeliveriesView(APIView):
    serializer_class = DeliverySerializer

    def get(self, request):
        require_site_moderator(request.user)
        return Response(_page(request, OutboundMessage.objects.order_by("-created_at", "-id"), DeliverySerializer))


@extend_schema_view(post=extend_schema(responses=DeliverySerializer))
class AdminRetryView(APIView):
    serializer_class = RetrySerializer

    @transaction.atomic
    def post(self, request, identifier):
        require_site_moderator(request.user)
        serializer = RetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = get_object_or_404(OutboundMessage.objects.select_for_update(), pk=identifier)
        if message.status != "failed":
            raise ValidationError("Only failed messages can be retried.")
        if "uncertain" in message.failure_reason.lower() and not serializer.validated_data["acknowledge_uncertain_delivery"]:
            raise ValidationError("Acknowledge that this message may already have been delivered.")
        message.status, message.available_at, message.attempts = "queued", timezone.now(), 0
        message.save(update_fields=["status", "available_at", "attempts", "updated_at"])
        OperationAudit.objects.create(actor=request.user, action="mail_retry", target_id=message.id, metadata={"reason": serializer.validated_data["reason"]})
        return Response(DeliverySerializer(message).data)


@extend_schema_view(get=extend_schema(responses=PayloadSerializer))
class NoticesView(APIView):
    serializer_class = NoticeSerializer

    def get(self, request):
        return Response({"results": NoticeSerializer(current_notices(), many=True).data})

    def post(self, request):
        require_site_moderator(request.user)
        serializer = NoticeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notice = serializer.save(created_by=request.user)
        OperationAudit.objects.create(actor=request.user, action="notice_created", target_id=notice.id)
        return Response(NoticeSerializer(notice).data, status=201)


class NoticeEndView(APIView):
    serializer_class = NoticeSerializer

    @extend_schema(request=EmptyActionSerializer)
    def patch(self, request, identifier):
        require_site_moderator(request.user)
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        notice = get_object_or_404(ServiceNotice, pk=identifier)
        notice.ends_at = timezone.now()
        notice.save(update_fields=["ends_at", "updated_at"])
        OperationAudit.objects.create(actor=request.user, action="notice_ended", target_id=notice.id)
        return Response(NoticeSerializer(notice).data)
