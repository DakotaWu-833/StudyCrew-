from rest_framework import serializers
from config.serializers import StrictFieldsMixin
from .models import ContactRequest, NotificationPreference, OutboundMessage, ServiceNotice, SupportTicket, TicketReply, UserAlert

DELIVERY_STATUS_CHOICES = OutboundMessage.Status.choices
SUPPORT_STATUS_CHOICES = SupportTicket._meta.get_field("status").choices


class PreferenceSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["in_app", "email", "task_reminders", "meeting_reminders", "assignments", "mentions", "invitations", "meeting_changes", "digest", "quiet_start", "quiet_end"]


class AlertSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)

    class Meta:
        model = UserAlert
        fields = ["id", "project", "project_name", "category", "title", "body", "target_url", "created_at", "read_at"]
        read_only_fields = fields


class DeliverySerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = OutboundMessage
        fields = ["id", "subject", "category", "status", "created_at", "available_at", "accepted_at", "confirmed_at", "attempts", "failure_reason"]
        read_only_fields = fields


class ReplySerializer(StrictFieldsMixin, serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.profile.display_name", read_only=True)

    class Meta:
        model = TicketReply
        fields = ["id", "author_name", "body", "created_at"]
        read_only_fields = fields


class TicketSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    replies = ReplySerializer(many=True, read_only=True)
    requester_name = serializers.CharField(source="user.profile.display_name", read_only=True)

    class Meta:
        model = SupportTicket
        fields = ["id", "category", "subject", "description", "status", "resolution", "created_at", "updated_at", "requester_name", "replies"]
        read_only_fields = ["id", "status", "resolution", "created_at", "updated_at", "replies"]


class TicketUpdateSerializer(StrictFieldsMixin, serializers.Serializer):
    status = serializers.ChoiceField(choices=SupportTicket._meta.get_field("status").choices, required=False)
    resolution = serializers.CharField(max_length=2000, allow_blank=True, required=False)


class NoticeSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = ServiceNotice
        fields = ["id", "title", "body", "severity", "starts_at", "ends_at"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs.get("ends_at") and attrs.get("starts_at") and attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError("End time must follow start time.")
        return attrs


class PayloadSerializer(StrictFieldsMixin, serializers.Serializer):
    results = serializers.JSONField(required=False)
    count = serializers.IntegerField(required=False)
    detail = serializers.CharField(required=False)


class MuteSerializer(StrictFieldsMixin, serializers.Serializer):
    project = serializers.UUIDField()
    muted = serializers.BooleanField()


class BlockSerializer(StrictFieldsMixin, serializers.Serializer):
    user_id = serializers.UUIDField()
    blocked = serializers.BooleanField(default=True)


class BodySerializer(StrictFieldsMixin, serializers.Serializer):
    body = serializers.CharField(max_length=2000)


class RetrySerializer(StrictFieldsMixin, serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=160)
    acknowledge_uncertain_delivery = serializers.BooleanField(default=False)


class ContactSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = ContactRequest
        fields = ["id", "email", "category", "subject", "description", "created_at", "verified_at", "resolved_at", "response"]
        read_only_fields = fields


class ContactResponseSerializer(StrictFieldsMixin, serializers.Serializer):
    response = serializers.CharField(max_length=2000)
