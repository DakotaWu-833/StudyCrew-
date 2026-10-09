from rest_framework import serializers
from drf_spectacular.utils import extend_schema_serializer


class RecruitmentInput(serializers.Serializer):
    project = serializers.UUIDField()
    title = serializers.CharField(max_length=120)
    university = serializers.CharField(max_length=120)
    course = serializers.CharField(max_length=60)
    term = serializers.CharField(max_length=80)
    description = serializers.CharField(max_length=3000)
    skills = serializers.ListField(child=serializers.CharField(max_length=50), max_length=10, allow_empty=True, required=False, default=list)
    languages = serializers.ListField(child=serializers.CharField(max_length=40), max_length=5, allow_empty=True, required=False, default=list)
    cooperation = serializers.ChoiceField(choices=["online", "campus", "hybrid"], required=False, default="hybrid")
    capacity = serializers.IntegerField(min_value=1, max_value=20)
    expires_at = serializers.DateTimeField()
    publish_consent = serializers.BooleanField()


class RecruitmentEdit(RecruitmentInput):
    project = None
    publish_consent = None
    expected_updated_at = serializers.DateTimeField()


class ApplicationInput(serializers.Serializer):
    message = serializers.CharField(max_length=1500)


class RecommendationPreferences(serializers.Serializer):
    course = serializers.CharField(max_length=60, required=False, allow_blank=True)
    university = serializers.CharField(max_length=120, required=False, allow_blank=True)
    skill = serializers.CharField(max_length=50, required=False, allow_blank=True)
    language = serializers.CharField(max_length=40, required=False, allow_blank=True)
    cooperation = serializers.ChoiceField(choices=["", "online", "campus", "hybrid"], required=False)


class DecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="RecruitmentReportInput")
class ReportInput(serializers.Serializer):
    reason = serializers.ChoiceField(choices=["spam", "harassment", "misleading", "other"])
    details = serializers.CharField(max_length=2000)


@extend_schema_serializer(component_name="RecruitmentModerationInput")
class ModerationInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["dismiss", "hide", "restore"])
    reason = serializers.CharField(max_length=1000)

