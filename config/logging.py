"""Redact bearer links before console/central logs format a request record."""
import logging
import re
from urllib.parse import unquote


class SensitiveURLFilter(logging.Filter):
    patterns = (
        (re.compile(r"(/coordination/subscriptions/feed/)[^\s/?\"']+"), r"\1[redacted]"),
        (re.compile(r"(/help/verify/[0-9a-f-]+/)[^\s/?\"']+", re.I), r"\1[redacted]"),
    )
    query_parameters = re.compile(r"([?&])([^=\s?&\"']+)=([^\s&\"']*)")
    sensitive_parameters = {"token", "code", "secret", "key", "join", "next"}
    url_paths = re.compile(r"(?P<origin>https?://[^/\s\"']+)?(?P<path>/[^\s?\"']*)")
    bearer_prefixes = ("/api/v1/coordination/subscriptions/feed/", "/help/verify/")

    @classmethod
    def redact(cls, message):
        def redact_path(match):
            # Django resolves percent-decoded paths. Check that representation
            # too, while emitting only a constant path rather than decoded input.
            path = unquote(match.group("path"))
            for prefix in cls.bearer_prefixes:
                if path.startswith(prefix):
                    return f"{match.group('origin') or ''}{prefix}[redacted]/"
            return match.group(0)
        message = cls.url_paths.sub(redact_path, message)
        for pattern, replacement in cls.patterns:
            message = pattern.sub(replacement, message)
        # Login's next value can itself be an encoded private joining URL.
        # Decode only parameter names for comparison (as Django does), never
        # output decoded untrusted values or introduce control characters.
        def redact_parameter(match):
            separator, name, _ = match.groups()
            return f"{separator}{name}=[redacted]" if unquote(name).lower() in cls.sensitive_parameters else match.group(0)
        return cls.query_parameters.sub(redact_parameter, message)

    def filter(self, record):
        record.msg, record.args = self.redact(record.getMessage()), ()
        # A transport or request exception can include a sensitive URL too.
        # Format once into sanitized text so downstream formatters do not append
        # the original exception string after the filtered request message.
        if record.exc_info:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True
