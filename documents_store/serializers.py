from rest_framework import serializers
from drf_spectacular.utils import extend_schema_serializer


class MetadataInput(serializers.Serializer):
    title = serializers.CharField(max_length=150, required=False)
    folder = serializers.CharField(max_length=80, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=32), max_length=10, required=False)
    pinned = serializers.BooleanField(required=False)
    expected_revision = serializers.IntegerField(min_value=1, required=True)


class UploadInput(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=150, required=False)
    folder = serializers.CharField(max_length=80, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=32), max_length=10, required=False)
    pinned = serializers.BooleanField(required=False, default=False)
    expected_revision = serializers.IntegerField(min_value=1, required=False)


@extend_schema_serializer(component_name="DocumentRevisionInput")
class RevisionInput(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)


class DiffInput(serializers.Serializer):
    from_version = serializers.UUIDField()
    to_version = serializers.UUIDField()
