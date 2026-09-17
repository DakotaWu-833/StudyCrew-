"""Persistent caches for optional backend-only integrations."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from config.models import TimestampedModel, UUIDPrimaryKeyModel


class ApiCacheEntry(UUIDPrimaryKeyModel, TimestampedModel):
    provider = models.CharField(max_length=64)
    cache_key = models.CharField(max_length=255)
    payload = models.JSONField()
    fetched_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "cache_key"),
                name="unique_api_provider_cache_key",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("fetched_at")),
                name="api_cache_expiry_after_fetch",
            ),
        ]
        indexes = [
            models.Index(fields=("provider", "expires_at"), name="api_cache_provider_exp_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.fetched_at and self.expires_at and self.expires_at <= self.fetched_at:
            raise ValidationError({"expires_at": "Expiry must be later than fetch time."})

    def is_fresh(self, *, at=None) -> bool:
        return self.expires_at > (at or timezone.now())

    def __str__(self) -> str:
        return f"{self.provider}:{self.cache_key}"
