"""Input validation for account security endpoints."""

from rest_framework import serializers


class ReauthenticationSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, max_length=512, write_only=True)


class RecoveryEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class CloseAccountSerializer(serializers.Serializer):
    confirmation = serializers.CharField(max_length=80)
