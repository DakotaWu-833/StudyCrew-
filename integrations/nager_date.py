"""Resilient, cached access to Nager.Date Australian public holidays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import logging
from typing import Any

from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils import timezone
import httpx

from .models import ApiCacheEntry


logger = logging.getLogger(__name__)

PROVIDER = "nager_date"
COUNTRY_CODE = "AU"
# The host and path are code-owned. No part of a caller-provided URL is fetched.
PUBLIC_HOLIDAYS_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/AU"


@dataclass(frozen=True, slots=True)
class PublicHoliday:
    date: date
    name: str
    local_name: str


@dataclass(frozen=True, slots=True)
class PublicHolidayResult:
    holidays: tuple[PublicHoliday, ...]
    source: str
    available: bool

    @property
    def is_stale(self) -> bool:
        return self.source == "stale"


def _cache_key(year: int) -> str:
    return f"public-holidays:{COUNTRY_CODE}:{year}"


def _normalise_items(items: Any, *, expected_year: int) -> tuple[PublicHoliday, ...]:
    if not isinstance(items, list):
        raise ValueError("Holiday payload must be a list.")

    holidays: list[PublicHoliday] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Holiday item must be an object.")
        if item.get("countryCode", COUNTRY_CODE) != COUNTRY_CODE:
            raise ValueError("Holiday payload contained another country.")
        holiday_date = date.fromisoformat(str(item["date"]))
        if holiday_date.year != expected_year:
            raise ValueError("Holiday payload contained another year.")
        name = str(item.get("name", "")).strip()
        local_name = str(item.get("localName", name)).strip()
        if not name or not local_name:
            raise ValueError("Holiday names must not be empty.")
        holidays.append(PublicHoliday(holiday_date, name, local_name))
    holidays.sort(key=lambda item: (item.date, item.name))
    return tuple(holidays)


def _decode_cache(payload: Any, *, year: int) -> tuple[PublicHoliday, ...]:
    if not isinstance(payload, dict) or payload.get("country_code") != COUNTRY_CODE:
        raise ValueError("Invalid cached holiday payload.")
    if payload.get("year") != year:
        raise ValueError("Cached holiday year does not match.")
    return _normalise_items(payload.get("holidays"), expected_year=year)


def _encode_cache(holidays: tuple[PublicHoliday, ...], *, year: int) -> dict[str, Any]:
    return {
        "country_code": COUNTRY_CODE,
        "year": year,
        "holidays": [
            {
                "date": item.date.isoformat(),
                "name": item.name,
                "localName": item.local_name,
                "countryCode": COUNTRY_CODE,
            }
            for item in holidays
        ],
    }


def get_australian_public_holidays(year: int) -> PublicHolidayResult:
    """Return fresh, live, stale, or unavailable holiday data without raising.

    Stale data is preferred over making meeting pages fail. A malformed cache is
    ignored and refreshed. The cache is one row per calendar year.
    """

    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        return PublicHolidayResult((), "unavailable", False)

    now = timezone.now()
    key = _cache_key(year)
    cache = ApiCacheEntry.objects.filter(provider=PROVIDER, cache_key=key).first()
    if cache is not None and cache.is_fresh(at=now):
        try:
            return PublicHolidayResult(
                _decode_cache(cache.payload, year=year),
                "cache",
                True,
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring malformed fresh Nager.Date cache for year %s.", year)

    try:
        timeout = float(getattr(settings, "EXTERNAL_API_TIMEOUT_SECONDS", 3.0))
        if timeout <= 0:
            timeout = 3.0
        response = httpx.get(
            PUBLIC_HOLIDAYS_URL.format(year=year),
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": "StudyCrew/1.0"},
        )
        response.raise_for_status()
        holidays = _normalise_items(response.json(), expected_year=year)
        ttl_seconds = int(getattr(settings, "NAGER_DATE_CACHE_TTL_SECONDS", 86400))
        expires_at = now + timedelta(seconds=max(ttl_seconds, 60))
        try:
            with transaction.atomic():
                ApiCacheEntry.objects.update_or_create(
                    provider=PROVIDER,
                    cache_key=key,
                    defaults={
                        "payload": _encode_cache(holidays, year=year),
                        "fetched_at": now,
                        "expires_at": expires_at,
                    },
                )
        except DatabaseError:
            logger.exception("Could not persist Nager.Date cache for year %s.", year)
        return PublicHolidayResult(holidays, "live", True)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        logger.warning("Nager.Date is unavailable for year %s.", year)

    if cache is not None:
        try:
            return PublicHolidayResult(
                _decode_cache(cache.payload, year=year),
                "stale",
                True,
            )
        except (KeyError, TypeError, ValueError):
            pass
    return PublicHolidayResult((), "unavailable", False)
