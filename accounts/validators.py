"""Password policy enforced by Django on every supported password-setting path."""

import re
from functools import lru_cache
from zoneinfo import available_timezones

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


@lru_cache(maxsize=1)
def _iana_time_zones() -> frozenset[str]:
    """Cache the platform time-zone catalogue for form and model validation."""

    return frozenset(available_timezones())


def validate_iana_timezone(value: str) -> None:
    """Reject aliases or file-like values that are not known IANA zone names."""

    if value not in _iana_time_zones():
        raise ValidationError(
            _("Select a recognised IANA time zone."),
            code="invalid_time_zone",
        )


class ComplexityPasswordValidator:
    """Require character variety in addition to Django's standard validators."""

    patterns = (
        (r"[a-z]", _("a lowercase letter")),
        (r"[A-Z]", _("an uppercase letter")),
        (r"\d", _("a number")),
        (r"[^A-Za-z0-9]", _("a symbol")),
    )

    def validate(self, password: str, user=None) -> None:
        missing = [label for pattern, label in self.patterns if not re.search(pattern, password)]
        if missing:
            raise ValidationError(
                _("This password must contain %(requirements)s."),
                code="password_missing_character_types",
                params={"requirements": ", ".join(str(item) for item in missing)},
            )

    def get_help_text(self) -> str:
        return _("Your password must include uppercase, lowercase, numeric, and symbol characters.")
def _validate_profile_list(value, maximum: int) -> None:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(f"Provide a list of up to {maximum} entries.")
    normalised = []
    for entry in value:
        if not isinstance(entry, str) or not 1 <= len(entry.strip()) <= 40:
            raise ValidationError("Each entry must contain 1 to 40 characters.")
        normalised.append(entry.strip().casefold())
    if len(set(normalised)) != len(normalised):
        raise ValidationError("Remove duplicate entries.")


def validate_skills_list(value) -> None:
    _validate_profile_list(value, 12)


def validate_languages_list(value) -> None:
    _validate_profile_list(value, 8)
