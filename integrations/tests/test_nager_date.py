from datetime import timedelta
from unittest.mock import Mock, patch

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
import httpx

from integrations.models import ApiCacheEntry
from integrations.nager_date import (
    COUNTRY_CODE,
    PROVIDER,
    PUBLIC_HOLIDAYS_URL,
    get_australian_public_holidays,
)


def payload(year=2026):
    return {
        "country_code": COUNTRY_CODE,
        "year": year,
        "holidays": [
            {
                "date": f"{year}-01-26",
                "name": "Australia Day",
                "localName": "Australia Day",
                "countryCode": COUNTRY_CODE,
            }
        ],
    }


class NagerDateTests(TestCase):
    def cache_entry(self, *, year=2026, fresh=True):
        now = timezone.now()
        return ApiCacheEntry.objects.create(
            provider=PROVIDER,
            cache_key=f"public-holidays:AU:{year}",
            payload=payload(year),
            fetched_at=now - timedelta(days=2),
            expires_at=now + timedelta(hours=1) if fresh else now - timedelta(days=1),
        )

    @patch("integrations.nager_date.httpx.get")
    def test_exact_fresh_cache_hit_makes_no_external_call(self, http_get):
        self.cache_entry()

        first = get_australian_public_holidays(2026)
        second = get_australian_public_holidays(2026)

        self.assertEqual(first.source, "cache")
        self.assertEqual(second.source, "cache")
        self.assertEqual(first.holidays[0].name, "Australia Day")
        http_get.assert_not_called()

    @override_settings(EXTERNAL_API_TIMEOUT_SECONDS=3)
    @patch("integrations.nager_date.httpx.get")
    def test_live_result_is_cached_per_year_without_duplicate_call(self, http_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload()["holidays"]
        http_get.return_value = response

        live = get_australian_public_holidays(2026)
        cached = get_australian_public_holidays(2026)

        self.assertEqual(live.source, "live")
        self.assertEqual(cached.source, "cache")
        http_get.assert_called_once_with(
            PUBLIC_HOLIDAYS_URL.format(year=2026),
            timeout=3.0,
            headers={"Accept": "application/json", "User-Agent": "StudyCrew/1.0"},
        )
        self.assertEqual(
            ApiCacheEntry.objects.filter(provider=PROVIDER, cache_key="public-holidays:AU:2026").count(),
            1,
        )

    @patch("integrations.nager_date.httpx.get")
    def test_timeout_uses_expired_cache_as_stale_fallback(self, http_get):
        self.cache_entry(fresh=False)
        http_get.side_effect = httpx.ReadTimeout("provider timed out")

        result = get_australian_public_holidays(2026)

        self.assertTrue(result.available)
        self.assertTrue(result.is_stale)
        self.assertEqual(result.holidays[0].date.isoformat(), "2026-01-26")

    @patch("integrations.nager_date.httpx.get")
    def test_timeout_without_cache_is_gracefully_unavailable(self, http_get):
        http_get.side_effect = httpx.ConnectTimeout("provider timed out")

        result = get_australian_public_holidays(2026)

        self.assertFalse(result.available)
        self.assertEqual(result.source, "unavailable")
        self.assertEqual(result.holidays, ())

    @patch("integrations.nager_date.httpx.get")
    def test_wrong_country_payload_is_not_cached(self, http_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "date": "2026-01-01",
                "name": "Wrong country",
                "localName": "Wrong country",
                "countryCode": "NZ",
            }
        ]
        http_get.return_value = response

        result = get_australian_public_holidays(2026)

        self.assertFalse(result.available)
        self.assertFalse(ApiCacheEntry.objects.exists())

    def test_cache_database_constraints_enforce_unique_key_and_time_order(self):
        entry = self.cache_entry()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ApiCacheEntry.objects.create(
                    provider=entry.provider,
                    cache_key=entry.cache_key,
                    payload={},
                    fetched_at=entry.fetched_at,
                    expires_at=entry.expires_at,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                now = timezone.now()
                ApiCacheEntry.objects.create(
                    provider=PROVIDER,
                    cache_key="bad-expiry",
                    payload={},
                    fetched_at=now,
                    expires_at=now,
                )

    def test_cache_model_validation_freshness_and_label(self):
        entry = self.cache_entry()

        self.assertTrue(entry.is_fresh())
        self.assertEqual(str(entry), "nager_date:public-holidays:AU:2026")
        entry.expires_at = entry.fetched_at
        with self.assertRaises(ValidationError):
            entry.full_clean()

    @patch("integrations.nager_date.httpx.get")
    def test_invalid_year_is_unavailable_without_network(self, http_get):
        for invalid in (True, 0, 10000, "2026"):
            with self.subTest(year=invalid):
                result = get_australian_public_holidays(invalid)
                self.assertFalse(result.available)
        http_get.assert_not_called()

    @override_settings(EXTERNAL_API_TIMEOUT_SECONDS=-1)
    @patch("integrations.nager_date.httpx.get")
    def test_malformed_fresh_cache_is_replaced_from_fixed_endpoint(self, http_get):
        entry = self.cache_entry()
        entry.payload = {"country_code": "AU", "year": 2025, "holidays": []}
        entry.save(update_fields=("payload", "updated_at"))
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload()["holidays"]
        http_get.return_value = response

        result = get_australian_public_holidays(2026)

        self.assertTrue(result.available)
        self.assertEqual(result.source, "live")
        self.assertEqual(http_get.call_args.kwargs["timeout"], 3.0)

    @patch("integrations.nager_date.httpx.get")
    def test_malformed_stale_cache_does_not_mask_provider_failure(self, http_get):
        entry = self.cache_entry(fresh=False)
        entry.payload = []
        entry.save(update_fields=("payload", "updated_at"))
        http_get.side_effect = httpx.ConnectError("offline")

        result = get_australian_public_holidays(2026)

        self.assertFalse(result.available)
