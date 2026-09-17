#!/usr/bin/env python3
"""Verify HTTPS, edge hardening, static delivery and five-user concurrency."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import ssl
import sys
from threading import Barrier, BrokenBarrierError
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener, urlopen


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch(url: str, *, follow_redirects: bool = True) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, headers={"User-Agent": "StudyCrew-deployment-check/1.0"})
    try:
        if follow_redirects:
            response = urlopen(request, timeout=10, context=ssl.create_default_context())
        else:
            response = build_opener(
                NoRedirect,
                HTTPSHandler(context=ssl.create_default_context()),
            ).open(request, timeout=10)
        with response:
            return (
                response.status,
                {name.lower(): value for name, value in response.headers.items()},
                response.read(4096),
            )
    except HTTPError as error:
        return (
            error.code,
            {name.lower(): value for name, value in error.headers.items()},
            error.read(4096),
        )
    except (URLError, TimeoutError, OSError) as error:
        return 0, {}, str(error).encode("utf-8", errors="replace")[:4096]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Deployed HTTPS origin, e.g. https://studycrew.example")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlparse(base)
    failures: list[str] = []
    if parsed.scheme != "https" or not parsed.hostname:
        parser.error("base_url must be an HTTPS origin")

    status, headers, _body = fetch(f"http://{parsed.netloc}/", follow_redirects=False)
    expected_https_origin = f"https://{parsed.netloc}"
    if status not in {301, 302, 307, 308} or not headers.get("location", "").startswith(
        f"{expected_https_origin}/"
    ):
        failures.append("HTTP does not redirect to HTTPS")

    status, headers, _body = fetch(f"{base}/")
    if status != 200:
        failures.append(f"Home page returned {status}")
    required_headers = {
        "strict-transport-security",
        "content-security-policy",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
    }
    missing_headers = sorted(name for name in required_headers if name not in headers)
    if missing_headers:
        failures.append(f"Missing security headers: {', '.join(missing_headers)}")
    if "/" in headers.get("server", ""):
        failures.append("Server response exposes a software version")

    login_status, login_headers, _login_body = fetch(f"{base}/account/login/")
    cookie = login_headers.get("set-cookie", "").lower()
    if login_status != 200:
        failures.append(f"Sign-in page returned {login_status}")
    if "csrftoken=" not in cookie or "secure" not in cookie or "samesite=lax" not in cookie:
        failures.append("CSRF cookie is missing Secure or SameSite=Lax")

    static_status, static_headers, static_body = fetch(f"{base}/static/workspace/main.js")
    if static_status != 200 or not static_body:
        failures.append(f"Reviewed frontend bundle returned {static_status}")
    if "max-age=" not in static_headers.get("cache-control", ""):
        failures.append("Static bundle is not cache-controlled by Nginx")

    sensitive_paths = (
        "/.env",
        "/.git/config",
        "/.ssh/id_rsa",
        "/config/settings.py",
        "/deploy/studycrew.env.example",
        "/database.sqlite3",
        "/etc/passwd",
        "/proc/self/environ",
        "/protected-media/exports/not-authorised.csv",
    )
    for path in sensitive_paths:
        blocked_status, _headers, _body = fetch(f"{base}{path}")
        if blocked_status not in {403, 404}:
            failures.append(f"Sensitive path {path} returned {blocked_status}")

    missing_status, _headers, missing_body = fetch(f"{base}/definitely-not-a-studycrew-route")
    unsafe_error_markers = (
        b"traceback (most recent call last)",
        b"django_settings_module",
        b"/srv/studycrew/",
    )
    lowered_missing_body = missing_body.lower()
    if missing_status != 404:
        failures.append(f"Missing-resource check returned {missing_status}")
    if any(marker in lowered_missing_body for marker in unsafe_error_markers):
        failures.append("Error response exposes an internal trace or server path")

    simulated_users = 5
    iterations_per_user = 5
    start_barrier = Barrier(simulated_users)

    def user_journey(number: int) -> tuple[int, list[str]]:
        passed = 0
        journey_failures: list[str] = []
        try:
            start_barrier.wait(timeout=10)
        except BrokenBarrierError:
            return 0, [f"user {number} could not start concurrently"]
        for iteration in range(iterations_per_user):
            home_status, _home_headers, _home_body = fetch(f"{base}/")
            health_status, _health_headers, body = fetch(f"{base}/api/v1/health/")
            if home_status == 200 and health_status == 200 and b'"database":"ok"' in body.replace(
                b" ", b""
            ):
                passed += 2
            else:
                journey_failures.append(
                    f"user {number}, iteration {iteration + 1}: home={home_status}, health={health_status}"
                )
        return passed, journey_failures

    started_at = perf_counter()
    with ThreadPoolExecutor(max_workers=simulated_users) as executor:
        results = [
            future.result()
            for future in as_completed(
                executor.submit(user_journey, number) for number in range(1, simulated_users + 1)
            )
        ]
    elapsed_seconds = round(perf_counter() - started_at, 3)
    concurrent_passes = sum(result[0] for result in results)
    concurrent_failures = [item for result in results for item in result[1]]
    expected_requests = simulated_users * iterations_per_user * 2
    if concurrent_passes != expected_requests or concurrent_failures:
        failures.append(
            f"Concurrent journeys passed {concurrent_passes}/{expected_requests}: "
            + "; ".join(concurrent_failures[:5])
        )

    report = {
        "origin": base,
        "simulated_users": simulated_users,
        "iterations_per_user": iterations_per_user,
        "concurrent_requests": expected_requests,
        "concurrent_requests_passed": concurrent_passes,
        "elapsed_seconds": elapsed_seconds,
        "passed": not failures,
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
