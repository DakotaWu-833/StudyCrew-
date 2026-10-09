from rest_framework import serializers


class PreviewInput(serializers.Serializer):
    file = serializers.FileField()
    source = serializers.ChoiceField(choices=("generic", "canvas", "moodle"), default="generic")
    source_namespace = serializers.CharField(max_length=80, default="manual")
    timezone_name = serializers.CharField(max_length=64, required=False)


class ConfirmInput(serializers.Serializer):
    preview_id = serializers.UUIDField()
    confirmed = serializers.BooleanField()
