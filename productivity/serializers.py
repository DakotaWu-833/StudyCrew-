from datetime import datetime
from rest_framework import serializers


class OffsetDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise ValueError
        except (TypeError, ValueError):
            raise serializers.ValidationError("Include a UTC offset or Z in the date and time.") from None
        return super().to_internal_value(value)


class RecurrenceInput(serializers.Serializer):
    frequency = serializers.ChoiceField(choices=("weekly", "monthly"))
    interval = serializers.IntegerField(min_value=1, max_value=12, default=1)
    timezone_name = serializers.CharField(max_length=64)
    start_local = serializers.CharField(max_length=32)
    until_date = serializers.DateField()
    occurrence_limit = serializers.IntegerField(min_value=1, max_value=520, default=52)
    lead_days = serializers.IntegerField(min_value=0, max_value=30, default=7)


class TimerStopInput(serializers.Serializer):
    note = serializers.CharField(max_length=500, allow_blank=True, default="")


class ManualTimeInput(serializers.Serializer):
    started_at = OffsetDateTimeField()
    minutes = serializers.IntegerField(min_value=1, max_value=1440)
    note = serializers.CharField(max_length=500, allow_blank=True, default="")


class CorrectTimeInput(ManualTimeInput):
    expected_updated_at = serializers.DateTimeField()


class DiscardTimeInput(serializers.Serializer):
    expected_updated_at = serializers.DateTimeField()
