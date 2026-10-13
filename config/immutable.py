"""Shared append-only record guards, independent of HTTP or domain models."""
from django.db import models


class ImmutableRecordError(TypeError):
    """An existing audit record cannot be changed through application code."""


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Append-only records cannot be updated.")

    def delete(self):
        raise ImmutableRecordError("Append-only records cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ImmutableRecordError("Append-only records cannot be updated.")


class ImmutableModelMixin(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Append-only records cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Append-only records cannot be deleted.")
