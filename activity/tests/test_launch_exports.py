from datetime import date, datetime, timezone as utc
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from activity.exports import export_file_for_user, request_export
from coordination.models import (AttendanceRecord, CalendarSubscription, ClaimReview,
                                 ContributionClaim, CoordinationEvent, MeetingRecord)
from meetings.models import Meeting
from projects.models import Project, ProjectMembership


class LaunchEvidenceExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(email="export-owner@example.com", password="Valid!Password42", display_name="Owner")
        cls.member = User.objects.create_user(email="export-member@example.com", password="Valid!Password42", display_name="Former author")
        cls.project = Project.objects.create(name="Academic evidence", created_by=cls.owner)
        ProjectMembership.objects.create(project=cls.project, user=cls.owner, role="owner")
        ProjectMembership.objects.create(project=cls.project, user=cls.member, removed_at=datetime(2026, 10, 2, tzinfo=utc.utc))
        cls.claim = ContributionClaim.objects.create(project=cls.project, author=cls.member, title="+SUM(1,1)", statement="我完成了研究与测试。")
        ClaimReview.objects.create(claim=cls.claim, reviewer=cls.owner, outcome="confirmed", note="Reviewed the linked result")
        cls.meeting = Meeting.objects.create(project=cls.project, organiser=cls.owner, title="Design review", starts_at=datetime(2026, 10, 1, 1, tzinfo=utc.utc), ends_at=datetime(2026, 10, 1, 2, tzinfo=utc.utc))
        cls.record = MeetingRecord.objects.create(meeting=cls.meeting, version=2, minutes="Final minutes", decisions="Ship after review")
        AttendanceRecord.objects.create(record=cls.record, user=cls.member, attended=True, note="Corrected attendance", recorded_by=cls.owner)
        CoordinationEvent.objects.create(project=cls.project, actor=cls.owner, kind="minutes_updated", object_id=cls.record.pk, metadata={"version": 1, "minutes": "Previous minutes", "secret": "DO-NOT-EXPORT"})
        CalendarSubscription.objects.create(user=cls.owner, token_hash="PRIVATE-FEED-SECRET", expires_at=datetime(2027, 1, 1, tzinfo=utc.utc))

    def export(self, kind):
        return request_export(actor=self.owner, project=self.project, export_format=kind,
                              range_start=date(2026, 10, 1), range_end=date(2026, 10, 1))

    def test_csv_contains_former_author_reviews_minutes_and_corrections_without_secrets(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            job = self.export("csv")
            self.assertEqual(job.status, "ready")
            text = export_file_for_user(job=job, user=self.owner).read_text(encoding="utf-8-sig")
        for expected in ("Former author", "' +SUM".replace(" ", ""), "我完成了研究与测试。", "Reviewed the linked result",
                         "Final minutes", "Previous minutes", "Corrected attendance", "Accepted RSVP (intention)"):
            self.assertIn(expected, text)
        for private in (self.owner.email, self.member.email, "PRIVATE-FEED-SECRET", "DO-NOT-EXPORT"):
            self.assertNotIn(private, text)

    def test_pdf_includes_nested_evidence_and_uses_cjk_font_for_chinese_statements(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), patch("activity.exports.canvas.Canvas") as canvas:
            canvas.return_value.save.side_effect = None
            job = self.export("pdf")
        self.assertEqual(job.status, "ready")
        drawn = "".join(call.args[2] for call in canvas.return_value.drawString.call_args_list)
        self.assertIn("我完成了研究与测试。", drawn)
        self.assertIn("Previous minutes", drawn)
        self.assertIn("Former author", drawn)
        self.assertTrue(any(call.args[0] == "STSong-Light" for call in canvas.return_value.setFont.call_args_list))
