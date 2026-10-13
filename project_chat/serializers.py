from rest_framework import serializers
from config.serializers import StrictFieldsSerializer


class ChatQuery(StrictFieldsSerializer):
    since = serializers.IntegerField(min_value=0, required=False)
    before = serializers.UUIDField(required=False)

    def validate(self, values):
        if "since" in values and "before" in values:
            raise serializers.ValidationError("Choose a reconnect cursor or an older-message cursor.")
        return values


class ChatSendInput(StrictFieldsSerializer):
    body = serializers.CharField(min_length=1, max_length=2000, trim_whitespace=True)
    client_nonce = serializers.UUIDField()


class ChatRemoveInput(StrictFieldsSerializer):
    expected_updated_at = serializers.DateTimeField()
    reason = serializers.CharField(min_length=3, max_length=300, required=False, default="Message withdrawn")
