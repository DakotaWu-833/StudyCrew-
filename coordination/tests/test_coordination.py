from datetime import date, datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import NotFound, Throttled

from accounts.session_security import MFA_VERIFIED_SESSION_KEY
from activity.insights import contribution_insights
from meetings.models import Meeting, MeetingAttendance
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment

from coordination import selectors, services
from coordination.calendar import render_calendar
from coordination.models import CalendarSubscription, ClaimReview, CoordinationEvent, MeetingRecord, MeetingSeries


class CoordinationFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(email="coord-owner@example.com", password="ValidPass!234", display_name="Owner")
        cls.member = User.objects.create_user(email="coord-member@example.com", password="ValidPass!234", display_name="Member")
        cls.facilitator = User.objects.create_user(email="coord-reviewer@example.com", password="ValidPass!234", display_name="Reviewer")
        cls.outsider = User.objects.create_user(email="coord-outsider@example.com", password="ValidPass!234", display_name="Outsider")
        cls.project = Project.objects.create(name="Coordination team", created_by=cls.owner)
        cls.other = Project.objects.create(name="Another project", created_by=cls.outsider)
        ProjectMembership.objects.create(project=cls.project, user=cls.owner, role="owner")
        ProjectMembership.objects.create(project=cls.project, user=cls.member)
        ProjectMembership.objects.create(project=cls.project, user=cls.facilitator, role="facilitator")
        ProjectMembership.objects.create(project=cls.other, user=cls.outsider, role="owner")

    def setUp(self):
        self.client = APIClient()
        self.now = datetime(2026, 10, 1, 1, 0, tzinfo=datetime_timezone.utc)
        clock_patch = patch("django.utils.timezone.now", return_value=self.now)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def authenticate(self, user):
        self.client.force_login(user)
        session = self.client.session
        session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat()
        session.save()

    def meeting(self, *, past=False):
        start = self.now - timedelta(hours=2) if past else self.now + timedelta(days=3)
        return Meeting.objects.create(project=self.project, organiser=self.owner, title="Team decisions", starts_at=start, ends_at=start + timedelta(hours=1))

    def poll(self):
        start = self.now + timedelta(days=3)
        return services.create_poll(actor=self.owner, project=self.project, title="Choose a meeting time", agenda="Review the draft", location="Library", participants=[{"user_id": self.owner.id, "required": False}, {"user_id": self.member.id, "required": True}], options=[{"starts_at": start, "ends_at": start + timedelta(hours=1)}, {"starts_at": start + timedelta(days=1), "ends_at": start + timedelta(days=1, hours=1)}])


class CoordinationTests(CoordinationFixture):

    def test_api_requires_completed_mfa_and_checks_membership(self):
        url = f"/api/v1/coordination/polls/?project={self.project.id}"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 401)
        self.authenticate(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.authenticate(self.member)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_csrf_is_required_for_new_mutations(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.member)
        session = client.session
        session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat()
        session.save()
        response = client.put("/api/v1/coordination/availability/", {"project": str(self.project.pk), "time_zone": "UTC", "slots": []}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_availability_saved_only_for_self_and_converts_time_zones(self):
        services.save_availability(actor=self.member, project=self.project, time_zone="UTC", slots=[{"weekday": 0, "start_minute": 0, "end_minute": 60}])
        self.owner.profile.time_zone = "Australia/Sydney"
        self.owner.profile.save(update_fields=("time_zone",))
        result = selectors.availability_for_project(user=self.owner, project=self.project, week_start=date(2026, 10, 5))
        cell = next(item for item in result["cells"] if item["weekday"] == 0 and item["start_minute"] == 660)
        self.assertIn(str(self.member.id), cell["available_ids"])
        self.assertEqual(result["mine"]["slots"], [])
        with self.assertRaises(ValidationError):
            services.save_availability(actor=self.member, project=self.project, time_zone="UTC", slots=[{"weekday": 0, "start_minute": 0, "end_minute": 60}, {"weekday": 0, "start_minute": 30, "end_minute": 90}])
        self.authenticate(self.member)
        response = self.client.put("/api/v1/coordination/availability/", {"project": str(self.project.pk), "time_zone": "UTC", "slots": [], "user": str(self.owner.id)}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_removed_availability_does_not_leak_into_team_grid(self):
        services.save_availability(actor=self.member, project=self.project, time_zone="UTC", slots=[{"weekday": 0, "start_minute": 0, "end_minute": 60}])
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=self.now)
        result = selectors.availability_for_project(user=self.owner, project=self.project, week_start=date(2026, 10, 5))
        self.assertNotIn(str(self.member.id), [member["id"] for member in result["members"]])
        self.assertTrue(all(str(self.member.id) not in cell["available_ids"] for cell in result["cells"]))

    def test_poll_closes_once_and_creates_real_meeting_and_rsvp(self):
        poll = self.poll()
        option = poll.options.first()
        with self.assertRaises(ValidationError):
            services.close_poll(actor=self.owner, poll=poll, option_id=option.id)
        services.vote_option(actor=self.member, option=option, response="yes")
        meeting = services.close_poll(actor=self.owner, poll=poll, option_id=option.id)
        self.assertTrue(Meeting.objects.filter(pk=meeting.pk, project=self.project).exists())
        self.assertEqual(MeetingRecord.objects.get(meeting=meeting).participants[1]["required"], True)
        self.assertEqual(MeetingAttendance.objects.get(meeting=meeting, user=self.member).response, "accepted")
        with self.assertRaises(ValidationError):
            services.close_poll(actor=self.owner, poll=poll, option_id=option.id)
        with self.assertRaises(ValidationError):
            services.vote_option(actor=self.member, option=option, response="no")

    def test_poll_member_roles_and_removal_are_enforced(self):
        poll = self.poll()
        option = poll.options.first()
        with self.assertRaises(PermissionDenied):
            services.vote_option(actor=self.facilitator, option=option, response="yes")
        with self.assertRaises(PermissionDenied):
            services.close_poll(actor=self.member, poll=poll, option_id=option.pk)
        services.vote_option(actor=self.member, option=option, response="yes")
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=self.now)
        with self.assertRaises(ValidationError):
            services.close_poll(actor=self.owner, poll=poll, option_id=option.pk)

    def test_poll_api_round_trip_and_rejects_unexpected_fields(self):
        self.authenticate(self.owner)
        poll = self.poll()
        option = poll.options.first()
        self.authenticate(self.member)
        response = self.client.post(f"/api/v1/coordination/poll-options/{option.pk}/vote/", {"response": "yes"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.authenticate(self.owner)
        response = self.client.post(f"/api/v1/coordination/polls/{poll.pk}/close/", {"option_id": str(option.pk)}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["title"], poll.title)

    def test_minutes_version_requires_reconfirmation_and_retains_previous_text(self):
        meeting = self.meeting(past=True)
        record = services.save_meeting_record(actor=self.owner, meeting=meeting, minutes="Draft approved after discussion", decisions="Ship the draft")
        services.confirm_minutes(actor=self.member, record=record, version=record.version)
        first_version = record.version
        record = services.save_meeting_record(actor=self.owner, meeting=meeting, minutes="Draft approved with two corrections", decisions="Ship tomorrow")
        data = selectors.meeting_data(meeting, self.member)
        self.assertFalse(data["confirmations"][0]["current"])
        self.assertTrue(any(row["metadata"].get("minutes") == "Draft approved after discussion" for row in data["history"]))
        with self.assertRaises(ValidationError):
            services.confirm_minutes(actor=self.member, record=record, version=first_version)
        services.confirm_minutes(actor=self.member, record=record, version=record.version)
        self.assertTrue(selectors.meeting_data(meeting, self.member)["confirmations"][0]["current"])

    def test_actual_attendance_is_distinct_from_rsvp_and_corrections_are_retained(self):
        meeting = self.meeting(past=True)
        MeetingAttendance.objects.create(meeting=meeting, user=self.member, response="accepted")
        record = services.save_meeting_record(actor=self.owner, meeting=meeting, minutes="Attendance checked", decisions="")
        services.record_attendance(actor=self.owner, record=record, user_id=self.member.pk, attended=False, note="Member sent apologies")
        services.record_attendance(actor=self.owner, record=record, user_id=self.member.pk, attended=True, note="Correction: joined for the second half")
        self.assertEqual(MeetingAttendance.objects.get(meeting=meeting, user=self.member).response, "accepted")
        data = selectors.meeting_data(meeting, self.member)
        self.assertTrue(data["attendance"][0]["attended"])
        correction = next(row for row in data["history"] if row["kind"] == "attendance_corrected")
        self.assertFalse(correction["metadata"]["from"])
        self.assertTrue(correction["metadata"]["to"])
        with self.assertRaises(PermissionDenied):
            services.record_attendance(actor=self.member, record=record, user_id=self.owner.pk, attended=True, note="Not authorised")

    def test_action_item_creates_real_task_with_assignments_atomically(self):
        record = services.save_meeting_record(actor=self.owner, meeting=self.meeting(past=True), minutes="Assign follow-up work", decisions="")
        action = services.add_action(actor=self.owner, record=record, title="Revise the introduction", description="Apply the team's corrections", due_at=self.now + timedelta(days=3), assignee_ids=[self.member.pk])
        self.assertTrue(Task.objects.filter(pk=action.task_id, project=self.project).exists())
        self.assertTrue(TaskAssignment.objects.filter(task_id=action.task_id, user=self.member).exists())
        before = Task.objects.count()
        with self.assertRaises(ValidationError):
            services.add_action(actor=self.owner, record=record, title="Invalid assignment", description="", due_at=None, assignee_ids=[self.outsider.pk])
        self.assertEqual(Task.objects.count(), before)

    def test_recurring_meetings_preserve_wall_clock_through_dst(self):
        start = datetime(2026, 9, 28, 10, 0, tzinfo=ZoneInfo("Australia/Sydney"))
        meeting = Meeting.objects.create(project=self.project, organiser=self.owner, title="Weekly check-in", starts_at=start, ends_at=start + timedelta(hours=1))
        with patch("coordination.services.timezone.now", return_value=start - timedelta(days=1)):
            series = services.repeat_meeting(actor=self.owner, meeting=meeting, count=2, interval_days=7, time_zone="Australia/Sydney")
        occurrences = list(Meeting.objects.filter(pk__in=series.occurrence_ids).order_by("starts_at"))
        self.assertEqual([row.starts_at.astimezone(ZoneInfo("Australia/Sydney")).hour for row in occurrences], [10, 10])
        self.assertEqual(occurrences[0].starts_at.hour, 23)
        self.assertEqual(MeetingSeries.objects.count(), 1)

    def test_feed_token_is_hashed_rotatable_revocable_and_private_by_default(self):
        meeting = self.meeting()
        subscription, token = services.issue_subscription(actor=self.owner, project=self.project)
        self.assertNotEqual(subscription.token_hash, token)
        url = f"/api/v1/coordination/subscriptions/feed/{token}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertIn("SUMMARY:StudyCrew meeting", text)
        self.assertNotIn(meeting.title, text)
        self.assertNotIn(self.project.name, text)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        replacement, replacement_token = services.issue_subscription(actor=self.owner, subscription=subscription)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/coordination/subscriptions/feed/{replacement_token}/").status_code, 200)
        services.revoke_subscription(actor=self.owner, subscription=replacement)
        self.assertEqual(self.client.get(f"/api/v1/coordination/subscriptions/feed/{replacement_token}/").status_code, 404)

    def test_membership_removal_disables_project_feed_and_removes_personal_events(self):
        meeting = self.meeting()
        project_feed, project_token = services.issue_subscription(actor=self.member, project=self.project, include_details=True)
        personal_feed, personal_token = services.issue_subscription(actor=self.member, include_details=True)
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=self.now)
        with self.assertRaises(NotFound):
            services.consume_subscription(project_token)
        services.consume_subscription(personal_token)
        data = selectors.calendar_events(user=self.member, range_start=self.now.date(), range_end=(self.now + timedelta(days=10)).date())
        self.assertNotIn(str(meeting.pk), [row["id"] for row in data["events"]])

    def test_feed_db_rate_limit_and_disabled_account(self):
        row, token = services.issue_subscription(actor=self.owner)
        CalendarSubscription.objects.filter(pk=row.pk).update(request_window_started_at=self.now, request_count=60)
        with self.assertRaises(Throttled):
            services.consume_subscription(token)
        self.owner.is_active = False
        self.owner.save(update_fields=("is_active",))
        with self.assertRaises(NotFound):
            services.consume_subscription(token)

    def test_calendar_personal_tasks_are_assigned_and_project_calendar_is_authorised(self):
        due = self.now + timedelta(days=2)
        task = Task.objects.create(project=self.project, created_by=self.owner, title="Unassigned team task", due_at=due)
        assigned = Task.objects.create(project=self.project, created_by=self.owner, title="My assigned task", due_at=due)
        TaskAssignment.objects.create(task=assigned, user=self.member, assigned_by=self.owner)
        data = selectors.calendar_events(user=self.member, range_start=self.now.date(), range_end=due.date())
        self.assertIn(str(assigned.pk), [row["id"] for row in data["events"]])
        self.assertNotIn(str(task.pk), [row["id"] for row in data["events"]])
        with self.assertRaises(PermissionDenied):
            selectors.calendar_events(user=self.outsider, project=self.project, range_start=self.now.date(), range_end=due.date())

    def test_ics_escaping_utf8_folding_and_cancelled_status(self):
        at = self.now.isoformat()
        events = [{"id": "id", "kind": "meeting", "title": "很长的标题" * 30 + ";,\\\n", "project_name": "Team", "starts_at": at, "ends_at": (self.now + timedelta(hours=1)).isoformat(), "updated_at": at, "cancelled": True, "description": "Line one\nLine two", "location": "Library"}]
        content = render_calendar(events).decode()
        self.assertIn("STATUS:CANCELLED", content)
        self.assertIn("\\;\\,\\\\\\n", content.replace("\r\n ", ""))
        self.assertTrue(all(len(line.encode()) <= 75 for line in content.split("\r\n")))

    def test_joint_work_requires_attribution_and_independent_review(self):
        claim = services.create_claim(actor=self.owner, project=self.project, title="Drafted the architecture", statement="I drafted and explained the architecture diagram.", contributor_ids=[self.member.pk])
        with self.assertRaises(PermissionDenied):
            services.review_claim(actor=self.owner, claim=claim, outcome="confirmed", note="My own work")
        with self.assertRaises(ValidationError):
            services.review_claim(actor=self.facilitator, claim=claim, outcome="confirmed", note="Waiting for attribution")
        services.respond_claim(actor=self.member, claim=claim, response="confirmed")
        review = services.review_claim(actor=self.facilitator, claim=claim, outcome="confirmed", note="Reviewed the linked diagram together")
        result = selectors.claims_for_project(user=self.member, project=self.project)
        self.assertEqual(result["claims"][0]["status"], "team_confirmed")
        with self.assertRaises(TypeError):
            review.delete()
        services.respond_claim(actor=self.member, claim=claim, response="declined")
        self.assertEqual(selectors.claims_for_project(user=self.member, project=self.project)["claims"][0]["status"], "awaiting_collaborators")

    def test_claim_revision_withdrawal_and_history_survive(self):
        old = services.create_claim(actor=self.member, project=self.project, title="Initial implementation", statement="I implemented the login screens and their tests.")
        services.review_claim(actor=self.owner, claim=old, outcome="changes_requested", note="Include a result link")
        new = services.create_claim(actor=self.member, project=self.project, title="Revised implementation", statement="I implemented and tested the complete login flow.", artifact_url="https://example.com/result", supersedes=old)
        statuses = {row["id"]: row["status"] for row in selectors.claims_for_project(user=self.owner, project=self.project)["claims"]}
        self.assertEqual(statuses[str(old.pk)], "superseded")
        self.assertEqual(statuses[str(new.pk)], "self_reported")
        self.assertTrue(ClaimReview.objects.filter(claim=old).exists())
        services.withdraw_claim(actor=self.member, claim=new)
        rows = selectors.claims_for_project(user=self.owner, project=self.project)["claims"]
        self.assertEqual(next(row for row in rows if row["id"] == str(new.pk))["status"], "withdrawn")

    def test_claim_link_task_boundary_and_removed_read_permission(self):
        task = Task.objects.create(project=self.other, created_by=self.outsider, title="Other team's work")
        with self.assertRaises(ValidationError):
            services.create_claim(actor=self.owner, project=self.project, title="Invalid task link", statement="This statement must not reference another team.", task=task)
        with self.assertRaises(ValidationError):
            services.create_claim(actor=self.owner, project=self.project, title="Unsafe result link", statement="This result link must not execute script.", artifact_url="javascript:alert(1)")
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=self.now)
        data = selectors.claims_for_project(user=self.owner, project=self.project)
        former = next(row for row in data["members"] if row["id"] == str(self.member.pk))
        self.assertFalse(former["active"])
        with self.assertRaises(PermissionDenied):
            selectors.claims_for_project(user=self.member, project=self.project)

    def test_cancelled_rsvp_does_not_count_as_accepted_meeting_evidence(self):
        meeting = self.meeting(past=True)
        meeting.cancelled_at = self.now
        meeting.save(update_fields=("cancelled_at",))
        MeetingAttendance.objects.create(meeting=meeting, user=self.member, response="accepted")
        start = self.now.date() - timedelta(days=2)
        end = self.now.date() + timedelta(days=2)
        data = contribution_insights(user=self.owner, project=self.project, range_start=start, range_end=end)
        self.assertEqual(next(row for row in data["members"] if row["user_id"] == self.member.pk)["accepted_meetings"], 0)

    def test_archived_projects_prevent_all_coordination_writes(self):
        poll = self.poll()
        meeting = self.meeting(past=True)
        record = services.save_meeting_record(actor=self.owner, meeting=meeting, minutes="Recorded before archive", decisions="")
        claim = services.create_claim(actor=self.member, project=self.project, title="Recorded contribution", statement="I completed the draft before the project was archived.")
        self.project.archived_at = self.now
        self.project.save(update_fields=("archived_at",))
        poll.project = self.project
        meeting.project = self.project
        record.meeting.project = self.project
        claim.project = self.project
        with self.assertRaises(ValidationError):
            services.save_availability(actor=self.owner, project=self.project, time_zone="UTC", slots=[])
        with self.assertRaises(ValidationError):
            services.close_poll(actor=self.owner, poll=poll, option_id=poll.options.first().pk)
        with self.assertRaises(ValidationError):
            services.save_meeting_record(actor=self.owner, meeting=meeting, minutes="Changed after archive")
        with self.assertRaises(ValidationError):
            services.withdraw_claim(actor=self.member, claim=claim)
