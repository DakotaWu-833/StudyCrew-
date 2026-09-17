from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from meetings.models import Meeting, MeetingAttendance
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
