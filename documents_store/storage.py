"""UUID-only local paths and bounded content checks. These are not antivirus."""
from __future__ import annotations

import csv
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import unicodedata
import warnings
import zipfile
from xml.etree import ElementTree

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image


MIMES = {"pdf": "application/pdf", "txt": "text/plain", "csv": "text/csv", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "zip": "application/zip"}
BLOCKED = {"exe", "dll", "com", "msi", "bat", "cmd", "ps1", "sh", "py", "js", "jar", "html", "htm", "svg", "php", "asp", "vbs", "lnk", "scr", "docm", "xlsm", "pptm"}
KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f-]{36}\.blob$")


def limits():
    return {"file_limit": int(getattr(settings, "PROJECT_FILE_MAX_BYTES", 10 * 1024 * 1024)),
        "limit": int(getattr(settings, "PROJECT_FILE_QUOTA_BYTES", 250 * 1024 * 1024)),
        "daily_bytes_limit": int(getattr(settings, "PROJECT_FILE_DAILY_BYTES", 100 * 1024 * 1024)),
        "daily_upload_limit": int(getattr(settings, "PROJECT_FILE_DAILY_UPLOADS", 30)),
        "retained_version_limit": int(getattr(settings, "PROJECT_FILE_MAX_VERSIONS_TOTAL", 2000))}


def scan_required():
    return bool(getattr(settings, "PROJECT_FILES_REQUIRE_SCAN", getattr(settings, "ENVIRONMENT", "development") == "production"))


def root():
    media = Path(settings.MEDIA_ROOT).resolve()
    path = media / "private-project-files"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.resolve().parent != media:
        raise ValidationError("Private file storage is unavailable.")
    return path


def blob_path(key):
    if not KEY.fullmatch(key):
        raise ValidationError("Invalid private file reference.")
    base = root()
    path = base / key
    if path.parent.is_symlink() or path.is_symlink() or base not in path.resolve().parents:
        raise ValidationError("Invalid private file reference.")
    return path


def safe_name(raw):
    raw = unicodedata.normalize("NFKC", str(raw))
    if any(ord(c) < 32 for c in raw) or any(c in raw for c in ("/", "\\", ":", "\x7f")):
        raise ValidationError({"file": "Use a plain filename without path characters."})
    name = re.sub(r"[^\w .()\-]", "_", raw, flags=re.UNICODE).strip(" .")
    if not name or len(name) > 160:
        raise ValidationError({"file": "Filename must contain 1–160 characters."})
    pieces = name.lower().split(".")
    if len(pieces) < 2 or pieces[-1] not in MIMES or any(part in BLOCKED for part in pieces[:-1]):
        raise ValidationError({"file": "This file type is not supported."})
    return name, pieces[-1]


def _xml(data):
    # OOXML parts use UTF-8 here. Reject NUL-interleaved UTF-16 before an XML
    # parser could accept entity declarations that evade the raw byte checks.
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValidationError({"file": "XML entities are not allowed."})
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise ValidationError({"file": "Invalid office document XML."})


def _zip(data, extension):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            max_bytes = int(getattr(settings, "PROJECT_FILE_ZIP_EXPANDED_BYTES", 50 * 1024 * 1024))
            if not members or len(members) > 500 or sum(m.file_size for m in members) > max_bytes:
                raise ValidationError({"file": "Archive exceeds the member or expanded-size limit."})
            seen = set()
            total = 0
            for member in members:
                name = member.filename
                path = PurePosixPath(name)
                mode = member.external_attr >> 16
                suffix = path.suffix.lower().lstrip(".")
                if (name in seen or "\\" in name or ":" in name or any(ord(c) < 32 for c in name) or path.is_absolute()
                    or ".." in path.parts or member.flag_bits & 1 or stat.S_ISLNK(mode) or (mode & 0o111 and not member.is_dir())
                    or suffix in BLOCKED or suffix == "zip" or member.file_size > max(1, member.compress_size) * 100):
                    raise ValidationError({"file": "Archive contains an unsafe member."})
                seen.add(name)
                if member.is_dir():
                    continue
                # Bound actual expansion as well as trusting no central-directory sizes.
                with archive.open(member) as stream:
                    payload = stream.read(max_bytes - total + 1)
                total += len(payload)
                if total > max_bytes or len(payload) != member.file_size:
                    raise ValidationError({"file": "Archive expanded-size validation failed."})
                lower = name.lower()
                if extension == "zip":
                    # A conservative archive is a bundle of ordinary documents,
                    # not a general executable/code distribution service.
                    if suffix not in {"txt", "csv", "png", "jpg", "jpeg", "pdf"}:
                        raise ValidationError({"file": "ZIP members must be PDF, UTF-8 text/CSV, PNG or JPEG files."})
                    validate_contents(payload, suffix)
                if extension != "zip":
                    if any(token in lower for token in ("vbaproject", "/embeddings/", "activex", "oleobject")):
                        raise ValidationError({"file": "Macros, embedded objects and active controls are not supported."})
                    if suffix in {"xml", "rels"}:
                        tree = _xml(payload)
                        for node in tree.iter():
                            if node.attrib.get("TargetMode", "").lower() == "external":
                                raise ValidationError({"file": "External office relationships are not supported."})
            if extension != "zip":
                required = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}[extension]
                if "[Content_Types].xml" not in seen or required not in seen:
                    raise ValidationError({"file": "File contents do not match the office extension."})
                manifest = archive.read("[Content_Types].xml").lower()
                if b"macroenabled" in manifest or b"vbaproject" in manifest or b"activex" in manifest:
                    raise ValidationError({"file": "Macro-enabled office files are not supported."})
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, ValueError):
        raise ValidationError({"file": "Archive could not be safely validated."})


def validate_contents(data, extension):
    if not data:
        raise ValidationError({"file": "Empty files are not supported."})
    if extension in {"docx", "xlsx", "pptx", "zip"}:
        _zip(data, extension)
    elif extension in {"png", "jpg", "jpeg"}:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format != ("PNG" if extension == "png" else "JPEG") or image.width * image.height > 20_000_000:
                        raise ValueError
                    image.verify()
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValidationError({"file": "Image contents do not match a supported bounded image."})
    elif extension == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise ValidationError({"file": "File contents do not match a PDF."})
        # Conservative local handling; no CDR or complete PDF parser safety claim.
        if re.search(rb"/(?:JavaScript|JS|Launch|EmbeddedFile|RichMedia|OpenAction|AA)\b", data):
            raise ValidationError({"file": "Active or embedded PDF content is not supported."})
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError({"file": "Text and CSV files must use UTF-8."})
        if "\x00" in text or any(ord(c) < 32 and c not in "\t\r\n" for c in text):
            raise ValidationError({"file": "Binary content is not supported in text files."})
        if extension == "csv":
            try:
                for index, row in enumerate(csv.reader(io.StringIO(text), strict=True)):
                    if index >= 100_000 or len(row) > 1000:
                        raise ValidationError({"file": "CSV exceeds the row or column limit."})
            except csv.Error:
                raise ValidationError({"file": "Invalid CSV data."})


def scan(path):
    command = str(getattr(settings, "PROJECT_FILES_CLAMSCAN", "")).strip()
    if not command:
        if scan_required():
            raise ValidationError({"file": "Uploads require a configured malware scanner."})
        return "local_unscanned"
    try:
        result = subprocess.run([command, "--no-summary", "--", str(path)], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValidationError({"file": "Malware scanning is unavailable; no file was saved."})
    if result.returncode != 0:
        raise ValidationError({"file": "Malware scanning rejected this upload or could not complete."})
    return "clean"


def prepare(upload):
    filename, extension = safe_name(upload.name)
    maximum = limits()["file_limit"]
    if upload.size > maximum:
        raise ValidationError({"file": "File exceeds the upload-size limit."})
    data = bytearray()
    for chunk in upload.chunks():
        data.extend(chunk)
        if len(data) > maximum:
            raise ValidationError({"file": "File exceeds the upload-size limit."})
    payload = bytes(data)
    validate_contents(payload, extension)
    declared = str(getattr(upload, "content_type", "") or "").split(";")[0].lower()
    accepted = {MIMES[extension], "application/octet-stream", ""}
    if extension in {"docx", "xlsx", "pptx"}:
        accepted.add("application/zip")
    if extension in {"csv", "txt"}:
        accepted.add("text/plain")
    if declared not in accepted:
        raise ValidationError({"file": "The declared media type does not match the file."})
    descriptor, temporary = tempfile.mkstemp(prefix="pending-", dir=root())
    path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        scan_status = scan(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": path, "filename": filename, "content_type": MIMES[extension], "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(), "scan_status": scan_status}
