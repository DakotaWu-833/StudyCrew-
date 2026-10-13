from rest_framework import serializers
from config.serializers import StrictFieldsSerializer


class TextQuestion(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("Use a text question.")
        return super().to_internal_value(data)


class QuestionInput(StrictFieldsSerializer):
    question = TextQuestion(max_length=1000, allow_blank=False, trim_whitespace=True)
    max_sources = serializers.IntegerField(min_value=1, max_value=6, default=5)


class SourceOutput(serializers.Serializer):
    citation = serializers.CharField()
    kind = serializers.ChoiceField(choices=["file", "meeting"])
    source_id = serializers.UUIDField()
    title = serializers.CharField()
    version = serializers.IntegerField(allow_null=True)
    page = serializers.IntegerField(allow_null=True)
    excerpt = serializers.CharField()
    url = serializers.CharField()
    locator = serializers.CharField()


class SearchOutput(serializers.Serializer):
    question = serializers.CharField()
    sources = SourceOutput(many=True)
    warnings = serializers.ListField(child=serializers.CharField())
    retrieval = serializers.CharField()
    limited = serializers.BooleanField()


class AnswerOutput(SearchOutput):
    answer = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=["answered", "no_evidence", "model_unavailable", "unverified_answer"])
    model = serializers.CharField(allow_null=True)


class CapabilitiesOutput(serializers.Serializer):
    generation_available = serializers.BooleanField()
    provider = serializers.ChoiceField(choices=["disabled", "ollama", "compatible"])
    source_types = serializers.ListField(child=serializers.CharField())
    supported_files = serializers.ListField(child=serializers.CharField())
    max_question_length = serializers.IntegerField()
    retrieval = serializers.CharField()
    notice = serializers.CharField()
