"""Synchronous, authorised CSV/PDF evidence exports for modest course datasets."""

from __future__ import annotations

import csv
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


def _render_csv(*, project, insights: dict) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["StudyCrew contribution evidence"])
    writer.writerow(["Project", _safe_csv_cell(project.name)])
    writer.writerow(["Range", insights["range_start"].isoformat(), insights["range_end"].isoformat()])
    writer.writerow([])
    writer.writerow(["Member", "Role", "Activity events", "Completed tasks", "Comments", "Accepted meetings"])
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
    return output.getvalue().encode("utf-8-sig")


def _render_pdf(*, project, insights: dict) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    width, height = A4
    left = 42
    y = height - 48

    def line(text: str, *, bold: bool = False, gap: int = 15) -> None:
        nonlocal y
        font_name = "Helvetica-Bold" if bold else "Helvetica"
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
            f"{member['completed_tasks']} completed tasks; {member['comments']} comments; "
            f"{member['accepted_meetings']} accepted meetings"
        )
    y -= 8
    line("Activity events", bold=True, gap=18)
    for event_row in _event_rows(insights):
        line(" | ".join(event_row))
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
) -> ExportJob:
    """Create and generate one small export, retaining a safe failure status."""

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

    destination: Path | None = None
    try:
        job.status = ExportJob.Status.PROCESSING
        job.save(update_fields=("status", "updated_at"))
        insights = contribution_insights(
            user=actor,
            project=project,
            range_start=range_start,
            range_end=range_end,
        )
        payload = (
            _render_csv(project=project, insights=insights)
            if export_format == ExportJob.Format.CSV
            else _render_pdf(project=project, insights=insights)
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
        logger.exception("Evidence export %s failed.", job.id)
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
