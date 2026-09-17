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
