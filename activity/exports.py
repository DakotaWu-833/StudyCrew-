"""Synchronous, authorised CSV/PDF evidence exports for modest course datasets."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from io import BytesIO, StringIO
import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from activity.insights import contribution_insights, validate_date_range
from activity.models import ActivityEvent, ExportJob
from activity.policies import require_project_activity_access
from activity.services import record_event


logger = logging.getLogger(__name__)


def _safe_csv_cell(value) -> str:
    """Prevent spreadsheet software from treating exported text as a formula."""

    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return f"'{text}"
    return text


def _event_rows(insights: dict) -> list[list[str]]:
    rows = []
    for event in insights["events"].order_by("occurred_at", "id"):
        actor_name = getattr(getattr(event.actor, "profile", None), "display_name", event.actor.email)
        rows.append(
            [
                event.occurred_at.isoformat(),
                _safe_csv_cell(actor_name),
                event.event_type,
                event.target_type,
                str(event.target_id or ""),
            ]
        )
    return rows


def _render_csv(*, project, insights: dict, evidence: dict | None = None) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["StudyCrew contribution evidence"])
    writer.writerow(["Project", _safe_csv_cell(project.name)])
    writer.writerow(["Range", insights["range_start"].isoformat(), insights["range_end"].isoformat()])
    writer.writerow([])
    writer.writerow(["Member", "Role", "System events", "Tasks marked done", "Comments created", "Accepted RSVP (intention)"])
    for member in insights["members"]:
        writer.writerow(
            [
                _safe_csv_cell(member["display_name"]),
                member["role"],
                member["total_events"],
                member["completed_tasks"],
                member["comments"],
                member["accepted_meetings"],
            ]
        )
    writer.writerow([])
    writer.writerow(["Occurred at (UTC)", "Actor", "Event type", "Target type", "Target ID"])
    writer.writerows(_event_rows(insights))
    if evidence is not None:
        writer.writerow([])
        writer.writerow(["Evidence definitions", _safe_csv_cell(evidence["basis"])])
        writer.writerow(["Date time zone", evidence["time_zone"]])
        writer.writerow(["Contribution statement scope", evidence["claim_scope"]])
        writer.writerow(["Meeting scope", evidence["meeting_scope"]])
        for key, title in (("members", "Retained member facts"), ("claims", "Contribution statements and their complete history"),
                           ("meetings", "Meeting records, confirmations, attendance and actions"),
                           ("coordination_events", "Meeting and scheduling correction history")):
            writer.writerow([])
            writer.writerow([title])
            rows = evidence[key]
            if rows:
                columns = list(rows[0])
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([_safe_csv_cell(json.dumps(row.get(column), ensure_ascii=False)
                                      if isinstance(row.get(column), (list, dict)) else row.get(column, "")) for column in columns])
    return output.getvalue().encode("utf-8-sig")


def _render_pdf(*, project, insights: dict, evidence: dict | None = None) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    width, height = A4
    left = 42
    y = height - 48

    def footer():
        document.setFont("Helvetica", 7)
        document.drawRightString(width - left, 26, f"StudyCrew evidence | Page {document.getPageNumber()}")

    def line(text: str, *, bold: bool = False, gap: int = 15) -> None:
        nonlocal y
        # ReportLab's standard CID font keeps CJK names and statements readable.
        cjk = any("\u2e80" <= character <= "\uffef" for character in str(text))
        if cjk and "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light" if cjk else "Helvetica-Bold" if bold else "Helvetica"
        font_size = 11 if bold else 9
        safe_text = str(text).replace("\n", " ").replace("\r", " ")
        max_width = width - (left * 2)
        wrapped: list[str] = []
        current = ""
        for character in safe_text:
            candidate = current + character
            if current and stringWidth(candidate, font_name, font_size) > max_width:
                wrapped.append(current)
                current = character
            else:
                current = candidate
        wrapped.append(current)
        for index, segment in enumerate(wrapped):
            if y < 55:
                footer()
                document.showPage()
                y = height - 48
            document.setFont(font_name, font_size)
            document.drawString(left, y, segment)
            y -= gap if index == len(wrapped) - 1 else 12

    document.setTitle(f"StudyCrew evidence - {project.name}")
    line("StudyCrew contribution evidence", bold=True, gap=20)
    line(f"Project: {project.name}")
    line(f"Range: {insights['range_start'].isoformat()} to {insights['range_end'].isoformat()}", gap=22)
    line("Member summaries", bold=True, gap=18)
    for member in insights["members"]:
        line(
            f"{member['display_name']} ({member['role']}): {member['total_events']} events; "
            f"{member['completed_tasks']} tasks marked done; {member['comments']} comments created; "
            f"{member['accepted_meetings']} accepted meetings (RSVP intention)"
        )
    y -= 8
    line("Activity events", bold=True, gap=18)
    for event_row in _event_rows(insights):
        line(" | ".join(event_row))
    if evidence is not None:
        y -= 8
        line("Evidence definitions and scope", bold=True, gap=18)
        line(evidence["basis"])
        line(f"Date time zone: {evidence['time_zone']}")
        line(evidence["claim_scope"])
        line(evidence["meeting_scope"])

        def detail(value, label=""):
            if isinstance(value, dict):
                if label:
                    line(label, bold=True)
                for key, item in value.items():
                    detail(item, key.replace("_", " "))
            elif isinstance(value, list):
                line(f"{label}: {len(value)} retained records", bold=True)
                for index, item in enumerate(value, 1):
                    detail(item, f"{label} {index}")
            else:
                line(f"{label}: {value if value is not None else 'not set'}")

        for key, title in (("members", "Retained member facts"), ("claims", "Contribution statement history"),
                           ("meetings", "Meeting records"), ("coordination_events", "Meeting correction history")):
            y -= 8
            detail(evidence[key], title)
    footer()
    document.save()
    return output.getvalue()


def _destination(job: ExportJob) -> Path:
    root = Path(settings.MEDIA_ROOT).resolve()
    relative = Path("exports") / str(job.project_id) / str(job.requested_by_id) / f"{job.id}.{job.format}"
    destination = (root / relative).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:  # defensive guard against future path changes
        raise ValidationError("Invalid export destination.") from exc
    return destination


def request_export(
    *,
    actor,
    project,
    export_format: str,
    range_start: date,
    range_end: date,
    defer: bool = False,
) -> ExportJob:
    """Create an authorised export and optionally defer generation to the worker."""

    require_project_activity_access(actor, project)
    validate_date_range(range_start, range_end)
    if export_format not in ExportJob.Format.values:
        raise ValidationError({"format": "Choose csv or pdf."})

    with transaction.atomic():
        job = ExportJob(
            project=project,
            requested_by=actor,
            format=export_format,
            range_start=range_start,
            range_end=range_end,
        )
        job.full_clean()
        job.save(force_insert=True)
        record_event(
            project=project,
            actor=actor,
            event_type=ActivityEvent.Type.EXPORT_REQUESTED,
            target_type=ActivityEvent.TargetType.EXPORT,
            target_id=job.id,
        )

    if defer:
        return job
    return generate_export(job)


def generate_export(job: ExportJob) -> ExportJob:
    """Generate an already authorised job, rechecking access at execution time."""
    actor, project = job.requested_by, job.project
    range_start, range_end = job.range_start, job.range_end
    export_format = job.format
    destination: Path | None = None
    try:
        job.status = ExportJob.Status.PROCESSING
        job.save(update_fields=("status", "updated_at"))
        insights = contribution_insights(
            user=actor,
            project=project,
            range_start=range_start,
            range_end=range_end,
            include_former=True,
        )
        from coordination.selectors import evidence_export_data
        evidence = evidence_export_data(user=actor, project=project, range_start=range_start, range_end=range_end)
        payload = (
            _render_csv(project=project, insights=insights, evidence=evidence)
            if export_format == ExportJob.Format.CSV
            else _render_pdf(project=project, insights=insights, evidence=evidence)
        )
        destination = _destination(job)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        relative_key = destination.relative_to(Path(settings.MEDIA_ROOT).resolve()).as_posix()
        with transaction.atomic():
            job.status = ExportJob.Status.READY
            job.storage_key = relative_key
            job.error_message = ""
            job.completed_at = timezone.now()
            job.expires_at = job.completed_at + timedelta(hours=24)
            job.full_clean()
            job.save(
                update_fields=(
                    "status",
                    "storage_key",
                    "error_message",
                    "completed_at",
                    "expires_at",
                    "updated_at",
                )
            )
            record_event(
                project=project,
                actor=actor,
                event_type=ActivityEvent.Type.EXPORT_READY,
                target_type=ActivityEvent.TargetType.EXPORT,
                target_id=job.id,
            )
    except Exception:  # the export boundary must degrade without exposing internals
        logger.error("Evidence export %s failed.", job.id)
        if destination and destination.exists():
            destination.unlink()
        with transaction.atomic():
            job.status = ExportJob.Status.FAILED
            job.storage_key = ""
            job.error_message = "Export generation failed. Please try again."
            job.completed_at = timezone.now()
            job.expires_at = None
            job.save(
                update_fields=(
                    "status",
                    "storage_key",
                    "error_message",
                    "completed_at",
                    "expires_at",
                    "updated_at",
                )
            )
            if not actor.is_active:
                return job
            record_event(
                project=project,
                actor=actor,
                event_type=ActivityEvent.Type.EXPORT_FAILED,
                target_type=ActivityEvent.TargetType.EXPORT,
                target_id=job.id,
            )
    return job


def export_file_for_user(*, job: ExportJob, user) -> Path:
    """Resolve a ready, unexpired export only for its requesting member."""

    require_project_activity_access(user, job.project)
    if job.requested_by_id != user.id:
        raise PermissionDenied("This export belongs to another user.")
    if job.status != ExportJob.Status.READY or not job.storage_key:
        raise ValidationError("This export is not ready for download.")
    if not job.expires_at or job.expires_at <= timezone.now():
        job.status = ExportJob.Status.EXPIRED
        job.save(update_fields=("status", "updated_at"))
        raise ValidationError("This export has expired.")
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / job.storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PermissionDenied("The export path is invalid.") from exc
    if not path.is_file():
        raise ValidationError("The export file is unavailable.")
    return path
