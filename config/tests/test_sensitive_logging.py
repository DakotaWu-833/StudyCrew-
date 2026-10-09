import logging
import io
from contextlib import ExitStack
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from config.logging import SensitiveURLFilter


class SensitiveLoggingTests(SimpleTestCase):
    def test_bearer_paths_and_recovery_queries_are_redacted(self):
        for path in ["/api/v1/coordination/subscriptions/feed/very-secret-token/",
                     "/help/verify/90e79593-f570-46f0-8d6c-eb969870983b/very-secret-token/",
                     "/account/password/reset/confirm/?token=very-secret-token"]:
            record = logging.LogRecord("django.request", logging.WARNING, "test", 1, "Not Found: %s", (path,), None)
            self.assertTrue(SensitiveURLFilter().filter(record))
            self.assertNotIn("very-secret-token", record.getMessage())
            self.assertIn("[redacted]", record.getMessage())

    def test_regular_paths_are_kept(self):
        record = logging.LogRecord("django.request", logging.INFO, "test", 1, "OK: %s", ("/api/v1/projects/",), None)
        SensitiveURLFilter().filter(record)
        self.assertEqual(record.getMessage(), "OK: /api/v1/projects/")

    @staticmethod
    def capture(logger, emit):
        stream = io.StringIO()
        handlers = []
        current = logger
        while current:
            handlers.extend(handler for handler in current.handlers if handler not in handlers)
            if not current.propagate:
                break
            current = current.parent
        with ExitStack() as context:
            for handler in handlers:
                if hasattr(handler, "stream"):
                    context.enter_context(patch.object(handler, "stream", stream))
            emit(logger)
        return stream.getvalue()

    def test_actual_runserver_logger_filters_public_bearers_with_debug_on_or_off(self):
        paths = [
            "/api/v1/coordination/subscriptions/feed/private-bearer/",
            "/help/verify/90e79593-f570-46f0-8d6c-eb969870983b/private-bearer/",
            "/help/%76erify/90e79593-f570-46f0-8d6c-eb969870983b/private-bearer/",
            "/api/v1/%63oordination/subscriptions/feed/private-bearer/",
            "/account/password/reset/confirm/?token=private-bearer",
            "/account/recovery/new-email/?token=private-bearer",
            "/app/campus/?join=private-bearer&page=2",
            "/app/campus/?%6Aoin=private-bearer",
            "/account/login/?next=%2Fapp%2Fcampus%2F%3Fjoin%3Dprivate-bearer",
        ]
        logger = logging.getLogger("django.server")
        for debug in (True, False):
            with override_settings(DEBUG=debug):
                for path in paths:
                    with self.subTest(debug=debug, path=path):
                        output = self.capture(logger, lambda target: target.info('"GET %s HTTP/1.1" %s %s', path, 200, 100,
                            extra={"status_code": 200}))
                        self.assertNotIn("private-bearer", output)
                        self.assertIn("[redacted]", output)
                        self.assertIn("HTTP/1.1", output)
                        self.assertEqual(output.count('"GET '), 1)

    @override_settings(DEBUG=True)
    def test_actual_request_and_security_loggers_do_not_emit_unfiltered_duplicates(self):
        for name in ("django.request", "django.security.csrf"):
            with self.subTest(logger=name):
                output = self.capture(logging.getLogger(name), lambda target: target.warning("Forbidden: %s",
                    "/help/verify/90e79593-f570-46f0-8d6c-eb969870983b/private-bearer/"))
                self.assertNotIn("private-bearer", output)
                self.assertIn("[redacted]", output)
                self.assertEqual(output.count("Forbidden:"), 1)

    def test_tracebacks_do_not_append_original_sensitive_urls(self):
        def emit(logger):
            try:
                raise OSError("Cannot open https://studycrew.example/app/campus/?join=private-bearer")
            except OSError:
                logger.exception("Request failed")
        output = self.capture(logging.getLogger("django.request"), emit)
        self.assertNotIn("private-bearer", output)
        self.assertIn("OSError", output)
        self.assertIn("join=[redacted]", output)

    def test_non_sensitive_pagination_values_remain_readable(self):
        record = logging.LogRecord("django.server", logging.INFO, "test", 1, 'GET %s HTTP/1.1',
            ("/api/v1/projects/?page=2&join=private-bearer&sort=name",), None)
        SensitiveURLFilter().filter(record)
        self.assertEqual(record.getMessage(), 'GET /api/v1/projects/?page=2&join=[redacted]&sort=name HTTP/1.1')
