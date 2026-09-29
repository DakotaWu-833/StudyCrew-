from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from integrations.nager_date import PublicHoliday, PublicHolidayResult
from meetings.models import Meeting, MeetingAttendance
from meetings.policies import can_manage_meeting, require_meeting_manager
from meetings.selectors import (
    attendance_counts,
    meeting_for_member,
    meeting_holiday_advisory,
    meetings_for_project,
)
from projects.models import Project, ProjectMembership


PASSWORD = "Correct-Horse-7-Battery!"


class MeetingSelectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(email="member-select@example.com", password=PASSWORD)
        cls.outsider = User.objects.create_user(email="outside-select@example.com", password=PASSWORD)
        cls.project = Project.objects.create(name="Selector project", created_by=cls.member)
        ProjectMembership.objects.create(
            project=cls.project,
            user=cls.member,
            role=ProjectMembership.Role.OWNER,
        )
        # 14:30 UTC on 25 January is 01:30 AEDT on Australia Day.
        cls.meeting = Meeting.objects.create(
            project=cls.project,
            organiser=cls.member,
            title="Australia Day planning",
            starts_at=datetime(2026, 1, 25, 14, 30, tzinfo=UTC),
            ends_at=datetime(2026, 1, 25, 15, 30, tzinfo=UTC),
        )

    def test_project_selector_requires_same_project_membership(self):
        self.assertEqual(list(meetings_for_project(project=self.project, user=self.member)), [self.meeting])
        with self.assertRaises(PermissionDenied):
            list(meetings_for_project(project=self.project, user=self.outsider))

    def test_selectors_hide_cancelled_rows_and_protect_detail(self):
        self.meeting.cancelled_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.meeting.save(update_fields=("cancelled_at", "updated_at"))

        self.assertFalse(
            meetings_for_project(
                project=self.project,
                user=self.member,
                include_cancelled=False,
            ).exists()
        )
        self.assertEqual(
            meeting_for_member(meeting_id=self.meeting.pk, user=self.member),
            self.meeting,
        )
        with self.assertRaises(PermissionDenied):
            meeting_for_member(meeting_id=self.meeting.pk, user=self.outsider)

    def test_meeting_scopes_keep_archived_evidence_discoverable(self):
        now = timezone.now()
        archived = Meeting.objects.create(
            project=self.project,
            organiser=self.member,
            title="Archived retrospective",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            archived_at=now,
        )

        active_ids = set(
            meetings_for_project(
                project=self.project,
                user=self.member,
                scope="active",
            ).values_list("id", flat=True)
        )
        archived_ids = set(
            meetings_for_project(
                project=self.project,
                user=self.member,
                scope="archived",
            ).values_list("id", flat=True)
        )
        all_ids = set(
            meetings_for_project(
                project=self.project,
                user=self.member,
                scope="all",
            ).values_list("id", flat=True)
        )

        self.assertEqual(active_ids, {self.meeting.id})
        self.assertEqual(archived_ids, {archived.id})
        self.assertEqual(all_ids, {self.meeting.id, archived.id})
        self.assertEqual(
            meeting_for_member(meeting_id=archived.id, user=self.member),
            archived,
        )

    def test_unknown_meeting_scope_is_rejected(self):
        with self.assertRaises(ValidationError) as raised:
            meetings_for_project(
                project=self.project,
                user=self.member,
                scope="deleted",
            )

        self.assertIn("scope", raised.exception.message_dict)

    def test_attendance_counts_include_zero_categories(self):
        MeetingAttendance.objects.create(
            meeting=self.meeting,
            user=self.member,
            response=MeetingAttendance.Response.ACCEPTED,
        )

        counts = attendance_counts(meeting=self.meeting, user=self.member)

        self.assertEqual(counts, {"pending": 0, "accepted": 1, "declined": 0})

    def test_management_policy_accepts_organiser_and_rejects_non_member(self):
        self.assertTrue(can_manage_meeting(user=self.member, meeting=self.meeting))
        self.assertFalse(can_manage_meeting(user=self.outsider, meeting=self.meeting))
        self.assertIsNotNone(require_meeting_manager(user=self.member, meeting=self.meeting))
        with self.assertRaises(PermissionDenied):
            require_meeting_manager(user=self.outsider, meeting=self.meeting)

    @patch("integrations.nager_date.get_australian_public_holidays")
    def test_holiday_advisory_uses_sydney_calendar_date(self, get_holidays):
        get_holidays.return_value = PublicHolidayResult(
            (PublicHoliday(datetime(2026, 1, 26).date(), "Australia Day", "Australia Day"),),
            "cache",
            True,
        )

        advisory = meeting_holiday_advisory(meeting=self.meeting)

        self.assertTrue(advisory.is_public_holiday)
        self.assertEqual(advisory.holiday_name, "Australia Day")
        get_holidays.assert_called_once_with(2026)

    @patch("integrations.nager_date.get_australian_public_holidays")
    def test_unavailable_holiday_api_returns_advisory_not_exception(self, get_holidays):
        get_holidays.return_value = PublicHolidayResult((), "unavailable", False)

        advisory = meeting_holiday_advisory(meeting=self.meeting)

        self.assertFalse(advisory.available)
        self.assertIsNone(advisory.is_public_holiday)
        self.assertIn("unavailable", advisory.message.lower())

    @patch("integrations.nager_date.get_australian_public_holidays")
    def test_non_holiday_advisory_is_distinct_from_unavailable(self, get_holidays):
        get_holidays.return_value = PublicHolidayResult((), "live", True)

        advisory = meeting_holiday_advisory(meeting=self.meeting)

        self.assertTrue(advisory.available)
        self.assertFalse(advisory.is_public_holiday)
        self.assertIn("no australian public holiday", advisory.message.lower())
