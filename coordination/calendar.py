"""RFC 5545 iCalendar output with UTC instants and escaped, folded text."""

from datetime import datetime, timezone


def _text(value):
    return str(value).replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _instant(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line):
    chunks, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            chunks.append(current)
            current = " "
        current += char
    chunks.append(current)
    return "\r\n".join(chunks)


def render_calendar(events, *, include_details=True):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//StudyCrew//Private Calendar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:StudyCrew"]
    for item in events:
        summary = f"{item['title']} · {item['project_name']}" if include_details else {"meeting": "StudyCrew meeting", "task": "StudyCrew task deadline", "task_official": "StudyCrew official task deadline", "project": "StudyCrew project deadline", "submission_internal": "StudyCrew internal submission deadline", "submission_official": "StudyCrew official submission deadline", "milestone": "StudyCrew milestone deadline"}.get(item["kind"], "StudyCrew deadline")
        lines.extend(["BEGIN:VEVENT", f"UID:{item['kind']}-{item['id']}@studycrew", f"DTSTAMP:{stamp}", f"LAST-MODIFIED:{_instant(item['updated_at'])}", f"DTSTART:{_instant(item['starts_at'])}", f"DTEND:{_instant(item['ends_at'])}", f"SUMMARY:{_text(summary)}", "CLASS:PRIVATE", f"STATUS:{'CANCELLED' if item['cancelled'] else 'CONFIRMED'}"])
        if include_details:
            lines.extend([f"DESCRIPTION:{_text(item['description'])}", f"LOCATION:{_text(item['location'])}"])
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")
