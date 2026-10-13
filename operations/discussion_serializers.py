from rest_framework import serializers
from config.serializers import StrictFieldsSerializer


class PostInput(StrictFieldsSerializer):
    title = serializers.CharField(min_length=3, max_length=120)
    body = serializers.CharField(max_length=6000)
    kind = serializers.ChoiceField(choices=["discussion", "announcement"], default="discussion")
    pinned = serializers.BooleanField(default=False)
    mention_ids = serializers.ListField(child=serializers.UUIDField(), max_length=50, default=list)
    expected_updated_at = serializers.DateTimeField(required=False)


class ReplyInput(StrictFieldsSerializer):
    body = serializers.CharField(max_length=2000)
    mention_ids = serializers.ListField(child=serializers.UUIDField(), max_length=50, default=list)


class ReportInput(StrictFieldsSerializer):
    reason = serializers.CharField(min_length=5, max_length=500)
    reply_id = serializers.UUIDField(required=False, allow_null=True)


class RemoveInput(StrictFieldsSerializer):
    reply_id = serializers.UUIDField(required=False, allow_null=True)


class ModerationInput(StrictFieldsSerializer):
    hide = serializers.BooleanField()
    reason = serializers.CharField(min_length=5, max_length=2000)
