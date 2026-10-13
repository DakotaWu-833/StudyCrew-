"""A bounded, current corpus; private text is never stored in a second index."""
import hashlib
import json
import subprocess
import sys
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import Http404

from coordination.models import MeetingRecord
from documents_store.models import ProjectDocument
from documents_store.services import _open_version
from documents_store.storage import MIMES, validate_contents

from .retrieval import chunks

SUPPORTED = {MIMES[extension]: extension for extension in ("txt", "csv", "pdf", "docx")}
MAX_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_CHARS = 32000


def fingerprint(row, version=None):
    if isinstance(row, ProjectDocument):
        return (str(version.pk), version.number, version.sha256, version.scan_status,
                row.revision, row.title, row.removed_at)
    return (row.version, row.updated_at, row.meeting.title, row.meeting.cancelled_at,
            row.meeting.archived_at, hashlib.sha256((row.minutes + "\n" + row.decisions).encode()).hexdigest())


def extract(data, extension, timeout):
    if extension in {"txt", "csv"}:
        text = data.decode("utf-8-sig")
        return {"pages": [{"page": None, "text": text[:MAX_CHARS]}], "limited": len(text) > MAX_CHARS}
    result = subprocess.run([sys.executable, "-m", "knowledge.parsing", extension], input=data,
                            capture_output=True, timeout=timeout, cwd=settings.BASE_DIR, check=False)
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise ValueError("The document could not be parsed")
    return json.loads(result.stdout)


def corpus(user, project, *, timeout_seconds=8):
    deadline = time.monotonic() + min(8, timeout_seconds)
    warnings = set()
    rows = []
    limited = False
    byte_count = 0
    max_files = settings.RAG_MAX_FILES
    documents = list(ProjectDocument.objects.filter(project=project, removed_at__isnull=True)
                     .prefetch_related("versions").order_by("-updated_at", "id")[:max_files + 1])
    if len(documents) > max_files:
        limited = True
        warnings.add("Only the most recently updated files were searched; the project has more files than the search limit.")
    for document in documents[:max_files]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            limited = True
            warnings.add("The search time limit was reached. Some files were not searched.")
            break
        version = next(iter(document.versions.all()), None)
        extension = SUPPORTED.get(version.content_type) if version else None
        if not extension:
            limited = True
            warnings.add("Some files use unsupported formats. Search supports TXT, CSV, PDF and DOCX; images require OCR.")
            continue
        if version.size > MAX_BYTES or byte_count + version.size > MAX_TOTAL_BYTES:
            limited = True
            warnings.add("Some files exceeded the 5 MiB file or 20 MiB search budget and were not searched.")
            continue
        byte_count += version.size
        try:
            stream, _ = _open_version(version)
            with stream:
                data = stream.read(MAX_BYTES + 1)
            validate_contents(data, extension)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                limited = True
                warnings.add("The search time limit was reached. Some files were not searched.")
                break
            parsed = extract(data, extension, min(settings.RAG_PARSE_TIMEOUT_SECONDS, remaining))
        except (OSError, ValueError, ValidationError, Http404, subprocess.TimeoutExpired):
            limited = True
            warnings.add("Some files could not be read, verified or safely parsed and were not searched.")
            continue
        if parsed["limited"]:
            limited = True
            warnings.add("Some documents were partially searched (first 30 PDF pages and up to 32,000 characters per file).")
        has_text = False
        for page in parsed["pages"]:
            for excerpt in chunks(page["text"]):
                has_text = True
                locator = f"Version {version.number}" + (f", page {page['page']}" if page["page"] else "")
                rows.append({"kind": "file", "source_id": str(document.pk), "title": document.title,
                             "version": version.number, "page": page["page"], "excerpt": excerpt, "locator": locator,
                             "url": f"/api/v1/files/projects/{project.pk}/documents/{document.pk}/download/?version={version.pk}",
                             "_fingerprint": fingerprint(document, version)})
        if not has_text:
            limited = True
            warnings.add("Some files contain no extractable text. Scanned PDFs and images need OCR, which is not enabled.")
    if time.monotonic() >= deadline:
        warnings.add("The search time limit was reached. Meeting notes were not searched.")
        return rows, sorted(warnings), True
    max_meetings = settings.RAG_MAX_MEETINGS
    records = list(MeetingRecord.objects.filter(meeting__project=project, meeting__cancelled_at__isnull=True,
                                                meeting__archived_at__isnull=True)
                   .select_related("meeting").order_by("-updated_at", "id")[:max_meetings + 1])
    if len(records) > max_meetings:
        limited = True
        warnings.add("Only the most recently updated meeting notes were searched; more notes exist.")
    for record in records[:max_meetings]:
        if time.monotonic() >= deadline:
            limited = True
            warnings.add("The search time limit was reached. Some meeting notes were not searched.")
            break
        text = "\n".join(part for part in (record.minutes, record.decisions) if part.strip())
        for excerpt in chunks(text):
            rows.append({"kind": "meeting", "source_id": str(record.pk), "title": record.meeting.title,
                         "version": record.version, "page": None, "excerpt": excerpt,
                         "locator": f"Meeting notes, version {record.version}",
                         "url": f"/app/projects/{project.pk}/coordination/?meeting={record.meeting_id}",
                         "_fingerprint": fingerprint(record)})
    return rows, sorted(warnings), limited


def unchanged(project, rows):
    """Reject a result if a source was removed or replaced while it was used."""
    seen = set()
    for row in rows:
        identity = (row["kind"], row["source_id"])
        if identity in seen:
            continue
        seen.add(identity)
        if row["kind"] == "file":
            document = ProjectDocument.objects.filter(pk=row["source_id"], project=project,
                                                      removed_at__isnull=True).first()
            version = document.versions.first() if document else None
            if not version or fingerprint(document, version) != row["_fingerprint"]:
                return False
            # Integrity and scan requirements apply again before returning evidence.
            try:
                stream, _ = _open_version(version)
                stream.close()
            except (OSError, Http404):
                return False
        else:
            record = MeetingRecord.objects.filter(pk=row["source_id"], meeting__project=project,
                                                   meeting__cancelled_at__isnull=True,
                                                   meeting__archived_at__isnull=True).select_related("meeting").first()
            if not record or fingerprint(record) != row["_fingerprint"]:
                return False
    return True
