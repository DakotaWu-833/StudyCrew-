from rest_framework import serializers

from config.serializers import StrictFieldsSerializer


class CalendarQuery(StrictFieldsSerializer):
    project = serializers.UUIDField(required=False)
    range_start = serializers.DateField()
    range_end = serializers.DateField()

    def validate(self, data):
        if data["range_start"].year < 1900 or data["range_end"].year > 9998:
            raise serializers.ValidationError("Choose dates between 1900 and 9998.")
        return data


class ProjectQuery(StrictFieldsSerializer):
    project = serializers.UUIDField()


class PagedProjectQuery(ProjectQuery):
    page = serializers.IntegerField(min_value=1, default=1)


class EvidenceQuery(PagedProjectQuery):
    range_start = serializers.DateField(required=False)
    range_end = serializers.DateField(required=False)


class AvailabilityQuery(ProjectQuery):
    week_start = serializers.DateField()

    def validate_week_start(self, value):
        if value.year < 1900 or value.year > 9998:
            raise serializers.ValidationError("Choose a week between 1900 and 9998.")
        return value


class AvailabilityWrite(ProjectQuery):
    time_zone = serializers.CharField(max_length=64)
    slots = serializers.JSONField()


class Participant(StrictFieldsSerializer):
    user_id = serializers.UUIDField()
    required = serializers.BooleanField()


class Candidate(StrictFieldsSerializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class PollWrite(ProjectQuery):
    title = serializers.CharField(min_length=3, max_length=120)
    agenda = serializers.CharField(max_length=4000, allow_blank=True, default="")
    location = serializers.CharField(max_length=2048, allow_blank=True, default="")
    participants = Participant(many=True)
    options = Candidate(many=True)


class VoteWrite(StrictFieldsSerializer):
    response = serializers.ChoiceField(choices=("yes", "maybe", "no"))


class PollClose(StrictFieldsSerializer):
    option_id = serializers.UUIDField()


class RecordWrite(StrictFieldsSerializer):
    expected_version = serializers.IntegerField(min_value=0, required=False)
    participants = Participant(many=True, required=False)
    minutes = serializers.CharField(max_length=12000, allow_blank=True, required=False)
    decisions = serializers.CharField(max_length=6000, allow_blank=True, required=False)


class ConfirmationWrite(StrictFieldsSerializer):
    version = serializers.IntegerField(min_value=1)


class AttendanceWrite(StrictFieldsSerializer):
    user_id = serializers.UUIDField()
    attended = serializers.BooleanField()
    note = serializers.CharField(min_length=1, max_length=500)


class ActionWrite(StrictFieldsSerializer):
    title = serializers.CharField(min_length=3, max_length=120)
    description = serializers.CharField(max_length=4000, allow_blank=True, default="")
    due_at = serializers.DateTimeField(allow_null=True, default=None)
    assignee_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100, default=list)


class RepeatWrite(StrictFieldsSerializer):
    count = serializers.IntegerField(min_value=1, max_value=12)
    interval_days = serializers.ChoiceField(choices=(7, 14))
    time_zone = serializers.CharField(max_length=64)


class SubscriptionWrite(StrictFieldsSerializer):
    project = serializers.UUIDField(required=False, allow_null=True)
    include_details = serializers.BooleanField(default=False)


class ClaimWrite(ProjectQuery):
    title = serializers.CharField(min_length=3, max_length=160)
    statement = serializers.CharField(min_length=10, max_length=6000)
    artifact_url = serializers.URLField(max_length=2048, allow_blank=True, default="")
    task_id = serializers.UUIDField(required=False, allow_null=True)
    contributor_ids = serializers.ListField(child=serializers.UUIDField(), max_length=100, default=list)
    supersedes_id = serializers.UUIDField(required=False, allow_null=True)


class ClaimResponse(StrictFieldsSerializer):
    response = serializers.ChoiceField(choices=("confirmed", "declined"))


class ReviewWrite(StrictFieldsSerializer):
    outcome = serializers.ChoiceField(choices=("confirmed", "changes_requested"))
    note = serializers.CharField(min_length=1, max_length=1000)
