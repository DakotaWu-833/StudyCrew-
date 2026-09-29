from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from activity.models import Notification
from meetings.models import Meeting, MeetingAttendance
from meetings.services import (
    archive_meeting,
    cancel_meeting,
    create_meeting,
    set_rsvp,
    update_meeting,
)
from projects.models import Project, ProjectMembership


PASSWORD = "Correct-Horse-7-Battery!"


class MeetingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="owner@example.com", password=PASSWORD)
        cls.organiser = User.objects.create_user(email="organiser@example.com", password=PASSWORD)
        cls.facilitator = User.objects.create_user(email="facilitator@example.com", password=PASSWORD)
        cls.member = User.objects.create_user(email="member@example.com", password=PASSWORD)
        cls.outsider = User.objects.create_user(email="outsider@example.com", password=PASSWORD)

        cls.project = Project.objects.create(name="Alpha project", created_by=cls.owner)
        for user, role in (
            (cls.owner, ProjectMembership.Role.OWNER),
            (cls.organiser, ProjectMembership.Role.MEMBER),
            (cls.facilitator, ProjectMembership.Role.FACILITATOR),
            (cls.member, ProjectMembership.Role.MEMBER),
        ):
            ProjectMembership.objects.create(project=cls.project, user=user, role=role)

        cls.other_project = Project.objects.create(name="Other project", created_by=cls.outsider)
        ProjectMembership.objects.create(
            project=cls.other_project,
            user=cls.outsider,
            role=ProjectMembership.Role.OWNER,
        )

    def times(self):
        start = timezone.now() + timedelta(days=2)
        return start, start + timedelta(hours=1)

    def persisted_meeting(self):
        start, end = self.times()
        return Meeting.objects.create(
            project=self.project,
            organiser=self.organiser,
            title="Sprint planning",
            starts_at=start,
            ends_at=end,
        )

    def ended_meeting(self, *, title="Completed retrospective"):
        end = timezone.now() - timedelta(hours=1)
        return Meeting.objects.create(
            project=self.project,
            organiser=self.organiser,
            title=title,
            starts_at=end - timedelta(hours=1),
            ends_at=end,
        )

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_active_member_can_create_and_event_is_recorded(self, record_event, notify):
        start, end = self.times()

        meeting = create_meeting(
            actor=self.organiser,
            project=self.project,
            title="Sprint planning",
            starts_at=start,
            ends_at=end,
        )

        self.assertEqual(meeting.organiser, self.organiser)
        record_event.assert_called_once_with(
            meeting=meeting,
            actor=self.organiser,
            event_type="meeting_created",
            metadata={"title": "Sprint planning"},
        )
        notify.assert_called_once()

    def test_meeting_notifications_target_an_existing_workspace_route(self):
        start, end = self.times()

        meeting = create_meeting(
            actor=self.organiser,
            project=self.project,
            title="Navigable notification",
            starts_at=start,
            ends_at=end,
        )

        expected = f"/app/projects/{self.project.id}/meetings/"
        self.assertEqual(
            set(
                Notification.objects.filter(source_event__target_id=meeting.id).values_list(
                    "target_url", flat=True
                )
            ),
            {expected},
        )

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_non_member_cannot_create(self, _record_event):
        start, end = self.times()

        with self.assertRaises(PermissionDenied):
            create_meeting(
                actor=self.outsider,
                project=self.project,
                title="Forbidden",
                starts_at=start,
                ends_at=end,
            )

        self.assertFalse(Meeting.objects.filter(title="Forbidden").exists())

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_create_rejects_times_beyond_the_ten_year_boundary(self, record_event):
        reference = datetime(2028, 2, 29, 10, 0, tzinfo=UTC)
        horizon = datetime(2038, 2, 28, 10, 0, tzinfo=UTC)

        with patch("meetings.models.timezone.now", return_value=reference):
            with self.assertRaises(ValidationError) as raised:
                create_meeting(
                    actor=self.organiser,
                    project=self.project,
                    title="Too distant",
                    starts_at=horizon,
                    ends_at=horizon + timedelta(seconds=1),
                )

        self.assertIn("ends_at", raised.exception.message_dict)
        self.assertFalse(Meeting.objects.filter(title="Too distant").exists())
        record_event.assert_not_called()

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_meeting_text_is_trimmed_and_blank_title_is_rejected(
        self, _record_event, _notify
    ):
        start, end = self.times()

        with self.assertRaises(ValidationError):
            create_meeting(
                actor=self.organiser,
                project=self.project,
                title="   ",
                starts_at=start,
                ends_at=end,
            )

        meeting = create_meeting(
            actor=self.organiser,
            project=self.project,
            title="  Sprint review  ",
            starts_at=start,
            ends_at=end,
            location="  Library  ",
            agenda="  Review the draft  ",
        )
        self.assertEqual(meeting.title, "Sprint review")
        self.assertEqual(meeting.location, "Library")
        self.assertEqual(meeting.agenda, "Review the draft")

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_organiser_facilitator_and_owner_can_edit(self, _record_event, _notify):
        meeting = self.persisted_meeting()

        meeting = update_meeting(meeting=meeting, actor=self.organiser, title="Organiser edit")
        meeting = update_meeting(meeting=meeting, actor=self.facilitator, title="Facilitator edit")
        meeting = update_meeting(meeting=meeting, actor=self.owner, title="Owner edit")

        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "Owner edit")

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_regular_member_and_cross_project_owner_cannot_edit(self, _record_event):
        meeting = self.persisted_meeting()

        for actor in (self.member, self.outsider):
            with self.subTest(actor=actor.email), self.assertRaises(PermissionDenied):
                update_meeting(meeting=meeting, actor=actor, title="Forbidden edit")

        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "Sprint planning")

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_no_op_update_creates_no_event(self, record_event, notify):
        meeting = self.persisted_meeting()

        unchanged = update_meeting(
            meeting=meeting,
            actor=self.organiser,
            title=meeting.title,
        )

        self.assertEqual(unchanged.pk, meeting.pk)
        record_event.assert_not_called()
        notify.assert_not_called()

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_cancel_is_soft_and_preserves_attendance(self, _record_event, _notify):
        meeting = self.persisted_meeting()
        MeetingAttendance.objects.create(
            meeting=meeting,
            user=self.member,
            response=MeetingAttendance.Response.ACCEPTED,
        )

        cancelled = cancel_meeting(meeting=meeting, actor=self.facilitator)

        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(cancelled.attendances.count(), 1)
        self.assertTrue(Meeting.objects.filter(pk=meeting.pk).exists())

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_cancelled_meeting_can_be_archived_without_losing_attendance(
        self,
        record_event,
        _notify,
    ):
        meeting = self.persisted_meeting()
        attendance = MeetingAttendance.objects.create(
            meeting=meeting,
            user=self.member,
            response=MeetingAttendance.Response.ACCEPTED,
        )
        cancelled = cancel_meeting(meeting=meeting, actor=self.organiser)
        record_event.reset_mock()

        archived = archive_meeting(meeting=cancelled, actor=self.organiser)

        self.assertIsNotNone(archived.archived_at)
        self.assertTrue(MeetingAttendance.objects.filter(pk=attendance.pk).exists())
        record_event.assert_called_once_with(
            meeting=archived,
            actor=self.organiser,
            event_type="meeting_archived",
        )

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_ended_meeting_can_be_archived(self, record_event):
        meeting = self.ended_meeting()

        archived = archive_meeting(meeting=meeting, actor=self.owner)

        self.assertIsNotNone(archived.archived_at)
        self.assertEqual(archived.lifecycle_state, "archived")
        record_event.assert_called_once_with(
            meeting=archived,
            actor=self.owner,
            event_type="meeting_archived",
        )

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_future_uncancelled_meeting_cannot_be_archived(self, record_event):
        meeting = self.persisted_meeting()

        with self.assertRaises(ValidationError):
            archive_meeting(meeting=meeting, actor=self.owner)

        meeting.refresh_from_db()
        self.assertIsNone(meeting.archived_at)
        record_event.assert_not_called()

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_archive_is_idempotent_and_records_one_event(self, record_event):
        meeting = self.ended_meeting()

        first = archive_meeting(meeting=meeting, actor=self.organiser)
        second = archive_meeting(meeting=meeting, actor=self.organiser)

        self.assertEqual(first.archived_at, second.archived_at)
        record_event.assert_called_once_with(
            meeting=first,
            actor=self.organiser,
            event_type="meeting_archived",
        )

    @patch("meetings.services._record_meeting_event", side_effect=RuntimeError("audit failed"))
    def test_archive_rolls_back_when_audit_recording_fails(self, _record_event):
        meeting = self.ended_meeting()

        with self.assertRaises(RuntimeError):
            archive_meeting(meeting=meeting, actor=self.organiser)

        meeting.refresh_from_db()
        self.assertIsNone(meeting.archived_at)

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_archive_permissions_match_meeting_manager_policy(self, record_event):
        for index, actor in enumerate((self.organiser, self.facilitator, self.owner), start=1):
            meeting = self.ended_meeting(title=f"Manager archive {index}")
            with self.subTest(allowed_actor=actor.email):
                self.assertIsNotNone(
                    archive_meeting(meeting=meeting, actor=actor).archived_at
                )

        for index, actor in enumerate((self.member, self.outsider), start=1):
            meeting = self.ended_meeting(title=f"Forbidden archive {index}")
            with self.subTest(forbidden_actor=actor.email), self.assertRaises(PermissionDenied):
                archive_meeting(meeting=meeting, actor=actor)
            meeting.refresh_from_db()
            self.assertIsNone(meeting.archived_at)

        self.assertEqual(record_event.call_count, 3)

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_archived_meeting_rejects_all_writes(self, _record_event):
        meeting = archive_meeting(
            meeting=self.ended_meeting(),
            actor=self.organiser,
        )

        with self.assertRaises(ValidationError):
            update_meeting(meeting=meeting, actor=self.organiser, title="Rewritten history")
        with self.assertRaises(ValidationError):
            cancel_meeting(meeting=meeting, actor=self.owner)
        with self.assertRaises(ValidationError):
            set_rsvp(
                meeting=meeting,
                actor=self.member,
                response=MeetingAttendance.Response.ACCEPTED,
            )

        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "Completed retrospective")
        self.assertIsNone(meeting.cancelled_at)
        self.assertFalse(MeetingAttendance.objects.filter(meeting=meeting).exists())

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_ended_meeting_rejects_edit_cancel_and_rsvp(self, record_event):
        meeting = self.ended_meeting()

        with self.assertRaises(ValidationError):
            update_meeting(meeting=meeting, actor=self.organiser, title="Too late")
        with self.assertRaises(ValidationError):
            cancel_meeting(meeting=meeting, actor=self.owner)
        with self.assertRaises(ValidationError):
            set_rsvp(
                meeting=meeting,
                actor=self.member,
                response=MeetingAttendance.Response.ACCEPTED,
            )

        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "Completed retrospective")
        self.assertIsNone(meeting.cancelled_at)
        self.assertFalse(MeetingAttendance.objects.filter(meeting=meeting).exists())
        record_event.assert_not_called()

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_rsvp_upserts_single_row(self, record_event):
        meeting = self.persisted_meeting()

        first = set_rsvp(
            meeting=meeting,
            actor=self.member,
            response=MeetingAttendance.Response.ACCEPTED,
        )
        first_time = first.responded_at
        second = set_rsvp(
            meeting=meeting,
            actor=self.member,
            response=MeetingAttendance.Response.DECLINED,
            availability_note="  Class clash  ",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MeetingAttendance.objects.filter(meeting=meeting, user=self.member).count(), 1)
        self.assertEqual(second.response, MeetingAttendance.Response.DECLINED)
        self.assertEqual(second.availability_note, "Class clash")
        self.assertGreaterEqual(second.responded_at, first_time)
        self.assertEqual(record_event.call_count, 2)

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_non_member_cannot_rsvp_across_project_boundary(self, _record_event):
        meeting = self.persisted_meeting()

        with self.assertRaises(PermissionDenied):
            set_rsvp(
                meeting=meeting,
                actor=self.outsider,
                response=MeetingAttendance.Response.ACCEPTED,
            )

        self.assertFalse(
            MeetingAttendance.objects.filter(meeting=meeting, user=self.outsider).exists()
        )

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_cancelled_meeting_rejects_rsvp(self, _record_event, _notify):
        meeting = self.persisted_meeting()
        meeting = cancel_meeting(meeting=meeting, actor=self.owner)

        with self.assertRaises(ValidationError):
            set_rsvp(
                meeting=meeting,
                actor=self.member,
                response=MeetingAttendance.Response.ACCEPTED,
            )

        self.assertFalse(MeetingAttendance.objects.filter(meeting=meeting, user=self.member).exists())

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_cancelled_meeting_cannot_be_edited_or_cancelled_twice(
        self,
        _record_event,
        _notify,
    ):
        meeting = cancel_meeting(meeting=self.persisted_meeting(), actor=self.owner)

        with self.assertRaises(ValidationError):
            update_meeting(meeting=meeting, actor=self.owner, title="Too late")
        with self.assertRaises(ValidationError):
            cancel_meeting(meeting=meeting, actor=self.owner)

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_archived_project_keeps_meetings_as_read_only_history(
        self,
        record_event,
        notify,
    ):
        meeting = self.persisted_meeting()
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=("archived_at", "updated_at"))
        start, end = self.times()

        with self.assertRaises(ValidationError):
            create_meeting(
                actor=self.member,
                project=self.project,
                title="New work after archive",
                starts_at=start,
                ends_at=end,
            )
        with self.assertRaises(ValidationError):
            update_meeting(meeting=meeting, actor=self.organiser, title="Changed history")
        with self.assertRaises(ValidationError):
            cancel_meeting(meeting=meeting, actor=self.owner)
        with self.assertRaises(ValidationError):
            archive_meeting(meeting=meeting, actor=self.owner)
        with self.assertRaises(ValidationError):
            set_rsvp(
                meeting=meeting,
                actor=self.member,
                response=MeetingAttendance.Response.ACCEPTED,
            )

        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "Sprint planning")
        self.assertIsNone(meeting.cancelled_at)
        self.assertIsNone(meeting.archived_at)
        self.assertFalse(MeetingAttendance.objects.filter(meeting=meeting).exists())
        record_event.assert_not_called()
        notify.assert_not_called()

    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_invalid_rsvp_value_is_rejected(self, _record_event):
        meeting = self.persisted_meeting()

        with self.assertRaises(ValidationError):
            set_rsvp(meeting=meeting, actor=self.member, response="maybe")

    @patch("meetings.services._record_meeting_event", side_effect=RuntimeError("audit failed"))
    def test_audit_failure_rolls_back_creation(self, _record_event):
        start, end = self.times()

        with self.assertRaises(RuntimeError):
            create_meeting(
                actor=self.member,
                project=self.project,
                title="Must roll back",
                starts_at=start,
                ends_at=end,
            )

        self.assertFalse(Meeting.objects.filter(title="Must roll back").exists())

    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_aware_local_time_preserves_utc_instant(self, _record_event, _notify):
        sydney = ZoneInfo("Australia/Sydney")
        local_start = (timezone.now() + timedelta(days=30)).astimezone(sydney).replace(
            minute=30,
            second=0,
            microsecond=0,
        )

        meeting = create_meeting(
            actor=self.organiser,
            project=self.project,
            title="Timezone meeting",
            starts_at=local_start,
            ends_at=local_start + timedelta(hours=1),
        )
        meeting.refresh_from_db()

        self.assertEqual(meeting.starts_at.astimezone(UTC), local_start.astimezone(UTC))

    @patch(
        "integrations.nager_date.get_australian_public_holidays",
        side_effect=RuntimeError("provider is offline"),
    )
    @patch("meetings.services._notify_active_members")
    @patch("meetings.services._record_meeting_event", return_value=Mock())
    def test_holiday_provider_is_not_on_meeting_creation_path(
        self,
        _record_event,
        _notify,
        holiday_lookup,
    ):
        start, end = self.times()

        meeting = create_meeting(
            actor=self.member,
            project=self.project,
            title="Provider-independent meeting",
            starts_at=start,
            ends_at=end,
        )

        self.assertTrue(Meeting.objects.filter(pk=meeting.pk).exists())
        holiday_lookup.assert_not_called()
