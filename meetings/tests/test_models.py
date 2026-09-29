from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from meetings.models import Meeting, MeetingAttendance, latest_allowed_meeting_datetime
from projects.models import Project


class MeetingModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="organiser@example.com",
            password="Correct-Horse-7-Battery!",
        )
        cls.project = Project.objects.create(name="Model project", created_by=cls.user)

    def meeting(self, **overrides):
        start = timezone.now() + timedelta(days=1)
        values = {
            "project": self.project,
            "organiser": self.user,
            "title": "Weekly planning",
            "starts_at": start,
            "ends_at": start + timedelta(hours=1),
        }
        values.update(overrides)
        return Meeting(**values)

    def test_full_clean_rejects_equal_start_and_end(self):
        instant = timezone.now() + timedelta(days=1)
        meeting = self.meeting(starts_at=instant, ends_at=instant)

        with self.assertRaises(ValidationError) as raised:
            meeting.full_clean()

        self.assertIn("ends_at", raised.exception.message_dict)

    def test_database_constraint_rejects_equal_start_and_end(self):
        instant = timezone.now() + timedelta(days=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Meeting.objects.create(
                    project=self.project,
                    organiser=self.user,
                    title="Invalid meeting",
                    starts_at=instant,
                    ends_at=instant,
                )

    def test_full_clean_rejects_naive_times(self):
        start = datetime(2026, 10, 20, 9, 0)
        meeting = self.meeting(starts_at=start, ends_at=start + timedelta(hours=1))

        with self.assertRaises(ValidationError) as raised:
            meeting.full_clean()

        self.assertIn("starts_at", raised.exception.message_dict)
        self.assertIn("ends_at", raised.exception.message_dict)

    def test_ten_calendar_year_horizon_clamps_leap_day_and_is_inclusive(self):
        reference = datetime(2028, 2, 29, 12, 30, tzinfo=UTC)
        expected_horizon = datetime(2038, 2, 28, 12, 30, tzinfo=UTC)

        with patch("meetings.models.timezone.now", return_value=reference):
            self.assertEqual(
                latest_allowed_meeting_datetime(),
                expected_horizon,
            )
            meeting = self.meeting(
                starts_at=expected_horizon - timedelta(hours=1),
                ends_at=expected_horizon,
            )
            meeting.full_clean()

            meeting.ends_at = expected_horizon + timedelta(microseconds=1)
            with self.assertRaises(ValidationError) as raised:
                meeting.full_clean()

        self.assertIn("ends_at", raised.exception.message_dict)

    def test_ten_year_horizon_rejects_a_start_beyond_the_boundary(self):
        reference = datetime(2027, 6, 15, 8, 0, tzinfo=UTC)
        beyond_horizon = reference.replace(year=2037) + timedelta(seconds=1)
        meeting = self.meeting(
            starts_at=beyond_horizon,
            ends_at=beyond_horizon + timedelta(hours=1),
        )

        with patch("meetings.models.timezone.now", return_value=reference):
            with self.assertRaises(ValidationError) as raised:
                meeting.full_clean()

        self.assertIn("starts_at", raised.exception.message_dict)
        self.assertIn("ends_at", raised.exception.message_dict)

    def test_soft_cancellation_state_and_labels_are_explicit(self):
        meeting = self.meeting(cancelled_at=timezone.now())
        meeting.full_clean()
        meeting.save()
        attendance = MeetingAttendance.objects.create(
            meeting=meeting,
            user=self.user,
            response=MeetingAttendance.Response.PENDING,
        )

        self.assertTrue(meeting.is_cancelled)
        self.assertEqual(str(meeting), "Weekly planning")
        self.assertIn(str(self.user.pk), str(attendance))

    def test_naive_cancellation_time_is_rejected(self):
        meeting = self.meeting(cancelled_at=datetime(2026, 10, 20, 10, 0))

        with self.assertRaises(ValidationError) as raised:
            meeting.full_clean()

        self.assertIn("cancelled_at", raised.exception.message_dict)

    def test_archive_time_requires_a_terminal_meeting(self):
        archive_time = timezone.now()
        meeting = self.meeting(archived_at=archive_time)

        with self.assertRaises(ValidationError) as raised:
            meeting.full_clean()

        self.assertIn("archived_at", raised.exception.message_dict)

    def test_database_archive_constraint_accepts_cancelled_or_ended_only(self):
        now = timezone.now()
        cancelled = self.meeting(
            title="Cancelled evidence",
            cancelled_at=now,
            archived_at=now,
        )
        cancelled.full_clean()
        cancelled.save()

        ended = self.meeting(
            title="Ended evidence",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            archived_at=now,
        )
        ended.full_clean()
        ended.save()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                future = self.meeting(title="Future evidence", archived_at=now)
                Meeting.objects.create(
                    project=future.project,
                    organiser=future.organiser,
                    title=future.title,
                    starts_at=future.starts_at,
                    ends_at=future.ends_at,
                    archived_at=future.archived_at,
                )

        self.assertEqual(cancelled.lifecycle_state, "archived")
        self.assertEqual(ended.lifecycle_state, "archived")

    def test_database_rejects_unknown_attendance_response(self):
        meeting = self.meeting()
        meeting.save()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MeetingAttendance.objects.create(
                    meeting=meeting,
                    user=self.user,
                    response="maybe",
                )
