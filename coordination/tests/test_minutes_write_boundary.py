"""Current minutes write boundaries and the order of requested row locks.

SQLite behavior and query intent are exercised here, not PostgreSQL scheduling.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.test import override_settings

from coordination import services
from coordination.models import AttendanceRecord, CoordinationEvent, MeetingRecord, MinutesConfirmation
from coordination.tests.test_coordination import CoordinationFixture
from meetings.models import Meeting
from projects.models import Project, ProjectMembership


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MinutesWriteBoundaryTests(CoordinationFixture):
    def setUp(self):
        super().setUp()
        self.meeting_row = self.meeting(past=True)
        self.record = MeetingRecord.objects.create(meeting=self.meeting_row, minutes="Original minutes", version=1)
        self.record.meeting.project  # Deliberately retain a cached project for stale-object checks.

    def writes(self, actor=None):
        actor = actor or self.owner
        return (
            lambda: services.save_meeting_record(actor=actor, meeting=self.meeting_row, minutes="Revised minutes"),
            lambda: services.confirm_minutes(actor=actor, record=self.record, version=1),
            lambda: services.record_attendance(actor=actor, record=self.record, user_id=self.member.pk,
                attended=True, note="Observed at the meeting"),
        )

    def assert_no_changes(self):
        self.record.refresh_from_db()
        self.assertEqual(self.record.minutes, "Original minutes")
        self.assertEqual(self.record.version, 1)
        self.assertEqual(MinutesConfirmation.objects.count(), 0)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertEqual(CoordinationEvent.objects.count(), 0)

    def test_all_minutes_mutators_request_account_project_record_lock_order_only(self):
        original = QuerySet.select_for_update
        for write in self.writes():
            MeetingRecord.objects.filter(pk=self.record.pk).update(version=1)
            requested = []
            def capture(query, *args, **kwargs):
                requested.append((query.model, kwargs.get("of")))
                return original(query, *args, **kwargs)
            with patch.object(QuerySet, "select_for_update", capture):
                write()
            self.assertEqual([model for model, _ in requested[:3]], [get_user_model(), Project, MeetingRecord])
            self.assertTrue(all(scope == ("self",) for _, scope in requested[:3]))
            self.assertTrue(all(model in {MinutesConfirmation, AttendanceRecord} for model, _ in requested[3:]))
            self.assertNotIn(Meeting, [model for model, _ in requested])

    def test_save_refreshes_current_meeting_title_before_returning_record(self):
        Meeting.objects.filter(pk=self.meeting_row.pk).update(title="Current meeting title")
        record = services.save_meeting_record(actor=self.owner, meeting=self.meeting_row, minutes="Updated minutes")
        self.assertEqual(record.meeting.title, "Current meeting title")
        self.assertEqual(record.version, 2)

    def test_disabled_and_closed_accounts_are_reloaded_before_all_writes(self):
        for change in ({"is_active": False}, {"closed_at": self.now}):
            get_user_model().objects.filter(pk=self.owner.pk).update(**change)
            for write in self.writes():
                with self.subTest(change=change), self.assertRaises(PermissionDenied):
                    write()
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True, closed_at=None)
        self.assert_no_changes()

    def test_current_membership_and_project_archive_override_cached_objects(self):
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=self.now)
        for write in self.writes():
            with self.assertRaises(PermissionDenied):
                write()
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=None)
        Project.objects.filter(pk=self.project.pk).update(archived_at=self.now)
        for write in self.writes():
            with self.assertRaises(ValidationError):
                write()
        self.assert_no_changes()

    def test_cancelled_and_archived_current_meeting_is_read_only_for_all_mutators(self):
        for change in ({"cancelled_at": self.now}, {"archived_at": self.now}):
            Meeting.objects.filter(pk=self.meeting_row.pk).update(**change)
            for write in self.writes():
                with self.subTest(change=change), self.assertRaises(ValidationError):
                    write()
            Meeting.objects.filter(pk=self.meeting_row.pk).update(cancelled_at=None, archived_at=None)
        self.assert_no_changes()

    def test_current_meeting_start_time_overrides_stale_started_meeting(self):
        future = self.now + timedelta(days=1)
        Meeting.objects.filter(pk=self.meeting_row.pk).update(starts_at=future, ends_at=future + timedelta(hours=1))
        for write in (self.writes()[0], self.writes()[2]):
            with self.assertRaises(ValidationError):
                write()
        self.assert_no_changes()

    def test_current_organiser_permissions_override_cached_meeting_for_managed_writes(self):
        Meeting.objects.filter(pk=self.meeting_row.pk).update(organiser=self.member)
        self.meeting_row.refresh_from_db()
        self.record.meeting = self.meeting_row
        Meeting.objects.filter(pk=self.meeting_row.pk).update(organiser=self.owner)
        for write in (self.writes(self.member)[0], self.writes(self.member)[2]):
            with self.assertRaises(PermissionDenied):
                write()
        self.assert_no_changes()

    def test_stale_version_still_rejects_save_and_confirmation_without_events(self):
        MeetingRecord.objects.filter(pk=self.record.pk).update(version=2)
        with self.assertRaises(ValidationError):
            services.save_meeting_record(actor=self.owner, meeting=self.meeting_row, minutes="Stale replacement", expected_version=1)
        with self.assertRaises(ValidationError):
            services.confirm_minutes(actor=self.member, record=self.record, version=1)
        self.assertEqual(CoordinationEvent.objects.count(), 0)
        self.assertEqual(MinutesConfirmation.objects.count(), 0)

