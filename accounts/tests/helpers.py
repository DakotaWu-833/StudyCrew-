import re


VALID_PASSWORD = "ValidPass!234"
NEW_VALID_PASSWORD = "AnotherPass!456"


def extract_otp(body: str) -> str:
    match = re.search(r"\b(\d{6})\b", body)
    if not match:
        raise AssertionError("The test email did not contain a six-digit code.")
    return match.group(1)
