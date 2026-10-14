"""Withhold model output that repeats recognizable credential literals.

This conservative check covers labeled credentials and common token formats;
it is not a general secret detector or an entailment/prompt-injection proof.
Authorized source previews retain the original content and access policy.
"""
import re

LABELED = re.compile(
    r"(?:\b(?:password|passphrase|api[ _-]?key|access[ _-]?token|client[ _-]?secret)\b|密码|密钥|访问令牌)"
    r"\s*(?:is\s+|为\s*|是\s*|[:=：]\s*)[\"']?([A-Za-z0-9_+/@=.\-]{8,256})",
    re.IGNORECASE,
)
TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,256}|gh[pousr]_[A-Za-z0-9]{20,255}|AKIA[A-Z0-9]{16})\b")


def repeats_credential(answer, rows):
    """Compare only source-derived literals, without returning/logging secrets."""
    if not isinstance(answer, str):
        return False
    folded = answer.casefold()
    for row in rows:
        text = row.get("excerpt", "")
        literals = [match.group(1).rstrip(".") for match in LABELED.finditer(text)]
        literals.extend(match.group(0) for match in TOKEN.finditer(text))
        if any(value and value.casefold() in folded for value in literals):
            return True
    return False
