"""Bounded UTF-8 CSV adapter. Canvas/Moodle names describe tested fixture headers."""
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import ValidationError

MAX_BYTES = 256 * 1024
MAX_ROWS = 100
ALIASES = {
    "generic": {"title": "title", "description": "description", "official_due_at": "official_due_at", "official_due": "official_due_at", "priority": "priority", "source_id": "source_id"},
    "canvas": {"assignment name": "title", "title": "title", "description": "description", "due date": "official_due_at", "assignment id": "source_id", "priority": "priority"},
    "moodle": {"item name": "title", "name": "title", "description": "description", "due date": "official_due_at", "id number": "source_id", "priority": "priority"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def deadline(value, timezone_name):
    if not value:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", value):
        raise ValueError("Use an ISO date and time, for example 2026-10-15T17:00:00+11:00; date-only values are ambiguous.")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("The deadline is not a valid ISO date and time.") from None
    if instant.year < 2000 or instant.year > 2100:
        raise ValueError("The deadline year must be between 2000 and 2100.")
    if instant.tzinfo is None:
        zone = ZoneInfo(timezone_name)
        candidates = set()
        for fold in (0, 1):
            aware = instant.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == instant:
                candidates.add(utc)
        if len(candidates) != 1:
            raise ValueError("This local time is missing or repeated during daylight saving. Supply an explicit UTC offset.")
        instant = candidates.pop()
    return instant.astimezone(timezone.utc).isoformat()


def parse(content, *, source, source_namespace, timezone_name):
    if source not in ALIASES:
        raise ValidationError({"source": "Choose generic, canvas or moodle."})
    if not isinstance(source_namespace, str) or not re.fullmatch(r"[\w .:-]{1,80}", source_namespace):
        raise ValidationError({"source_namespace": "Use a course/source label of 1 to 80 letters, digits, spaces or .:-_."})
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValidationError({"timezone_name": "Choose an IANA timezone such as Australia/Sydney."}) from None
    if len(content) > MAX_BYTES:
        raise ValidationError({"file": "CSV files must be at most 256 KiB."})
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError({"file": "Save the CSV as UTF-8."}) from None
    if "\x00" in text:
        raise ValidationError({"file": "Null bytes are not allowed."})
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader)
        if not 1 <= len(headers) <= 30:
            raise ValidationError({"file": "The CSV must have between 1 and 30 columns."})
        normal = [value.strip().lower() for value in headers]
        if len(set(normal)) != len(normal):
            raise ValidationError({"file": "Duplicate column names are not allowed."})
        mapped = [ALIASES[source].get(value) for value in normal]
        recognized = [value for value in mapped if value]
        if len(set(recognized)) != len(recognized) or "title" not in mapped:
            raise ValidationError({"file": "A single title column is required. Download the sample or choose the matching fixture format."})
        rows, seen = [], set()
        for cells in reader:
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise ValidationError({"file": "Import at most 100 assignments per file."})
            number = reader.line_num
            errors = []
            if len(cells) != len(headers):
                errors.append("The row has a different number of columns from the header.")
            data = {key: cells[index].strip() for index, key in enumerate(mapped) if key and index < len(cells)}
            title = data.get("title", "")
            description = data.get("description", "")
            priority = data.get("priority", "").lower() or "medium"
            if not 3 <= len(title) <= 120:
                errors.append("Title must contain 3 to 120 characters.")
            if len(description) > 4000:
                errors.append("Description must contain at most 4000 characters.")
            if any(ord(character) < 32 and character not in "\r\n\t" for character in title + description):
                errors.append("Text contains unsupported control characters.")
            if priority not in ("low", "medium", "high", "urgent"):
                errors.append("Priority must be low, medium, high or urgent.")
            try:
                due = deadline(data.get("official_due_at", ""), timezone_name)
            except ValueError as error:
                due = None
                errors.append(str(error))
            source_id = data.get("source_id", "") or "auto:" + digest({"title": title, "description": description, "due": due, "priority": priority})
            if len(source_id) > 160 or any(ord(character) < 32 for character in source_id):
                errors.append("Source ID must have at most 160 characters and no control characters.")
            if source_id in seen:
                errors.append("The file repeats this source ID. Give each assignment a unique source ID.")
            seen.add(source_id)
            rows.append({"row": number, "source_id": source_id, "title": title, "description": description, "priority": priority, "official_due_at": due, "errors": errors})
    except StopIteration:
        raise ValidationError({"file": "The CSV is empty."}) from None
    except csv.Error:
        raise ValidationError({"file": "The CSV quoting or field size is invalid."}) from None
    if not rows:
        raise ValidationError({"file": "The CSV has no assignment rows."})
    return rows, [headers[index] for index, key in enumerate(mapped) if key is None]
