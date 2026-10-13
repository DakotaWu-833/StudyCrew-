"""Strict request contracts shared by independently registered HTTP interfaces."""

from collections.abc import Mapping
from rest_framework import serializers


class StrictFieldsMixin:
    """Reject undeclared and read-only input instead of silently ignoring it."""

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        writable_fields = {field.field_name for field in self._writable_fields}
        unexpected = set(data) - writable_fields
        if unexpected:
            raise serializers.ValidationError({field: "This field is not accepted." for field in sorted(unexpected)})
        return super().to_internal_value(data)


class StrictFieldsSerializer(StrictFieldsMixin, serializers.Serializer):
    pass


class EmptyActionSerializer(StrictFieldsSerializer):
    """An explicitly empty action body also rejects unknown client fields."""
