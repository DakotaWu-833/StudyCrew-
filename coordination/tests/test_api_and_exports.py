import json
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from drf_spectacular.generators import SchemaGenerator

from campus.models import Milestone, SubmissionPlan, TaskPlan
from meetings.models import Meeting
from projects.models import ProjectMembership
from tasks.models import Task, TaskAssignment

from coordination import selectors, services
from coordination.calendar import render_calendar
from coordination.models import CalendarSubscription, CoordinationEvent, MeetingRecord
from .test_coordination import CoordinationFixture


class CoordinationAPIBoundaryTests(CoordinationFixture):
    def test_calendar_json_export_and_subscription_management_are_operable(self):
        self.meeting()
        self.authenticate(self.owner)
        params = f"project={self.project.pk}&range_start=2026-10-01&range_end=2026-10-10"
        response = self.client.get(f"/api/v1/coordination/calendar/?{params}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["kind"], "meeting")
        response = self.client.get(f"/api/v1/coordination/calendar/export/?{params}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/calendar", response["Content-Type"])
        self.assertIn(b"BEGIN:VEVENT", response.content)
        created = self.client.post("/api/v1/coordination/subscriptions/", {"project": str(self.project.pk), "include_details": True}, format="json")
        self.assertEqual(created.status_code, 201)
        first = created.json()
        self.assertIn("feed_url", first)
        self.assertNotIn("token_hash", first)
        listed = self.client.get("/api/v1/coordination/subscriptions/").json()
        self.assertEqual(len(listed["subscriptions"]), 1)
        self.assertNotIn("feed_url", listed["subscriptions"][0])
        rotated = self.client.post(f"/api/v1/coordination/subscriptions/{first['id']}/rotate/", {}, format="json")
        self.assertEqual(rotated.status_code, 201)
        self.assertEqual(self.client.get(first["feed_url"]).status_code, 404)
        revoked = self.client.post(f"/api/v1/coordination/subscriptions/{rotated.json()['id']}/revoke/", {}, format="json")
        self.assertEqual(revoked.status_code, 200)
        self.assertIsNotNone(revoked.json()["revoked_at"])

    def test_availability_and_poll_creation_voting_cancellation_use_real_apis(self):
        self.authenticate(self.member)
        saved = self.client.put("/api/v1/coordination/availability/", {"project": str(self.project.pk), "time_zone": "UTC", "slots": [{"weekday": 0, "start_minute": 540, "end_minute": 600}]}, format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/coordination/availability/?project={self.project.pk}&week_start=2026-10-05").status_code, 200)
        start = self.now + timedelta(days=5)
        poll = self.client.post("/api/v1/coordination/polls/", {"project": str(self.project.pk), "title": "Choose a review time", "participants": [{"user_id": str(self.member.pk), "required": True}], "options": [{"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}, {"starts_at": (start + timedelta(days=1)).isoformat(), "ends_at": (start + timedelta(days=1, hours=1)).isoformat()}]}, format="json")
        self.assertEqual(poll.status_code, 201)
        pk = poll.json()["id"]
        option = poll.json()["options"][0]["id"]
        self.assertEqual(self.client.post(f"/api/v1/coordination/poll-options/{option}/vote/", {"response": "maybe"}, format="json").status_code, 200)
        cancelled = self.client.post(f"/api/v1/coordination/polls/{pk}/cancel/", {}, format="json")
        self.assertEqual(cancelled.status_code, 200)
        self.assertIsNotNone(cancelled.json()["closed_at"])
        self.assertIsNone(cancelled.json()["meeting_id"])
        self.assertEqual(self.client.post(f"/api/v1/coordination/poll-options/{option}/vote/", {"response": "yes"}, format="json").status_code, 400)

    def test_meeting_outcomes_attendance_action_and_confirmation_api_flow(self):
        meeting = self.meeting(past=True)
        self.authenticate(self.owner)
        prefix = f"/api/v1/coordination/meeting-records/{meeting.pk}"
        saved = self.client.put(f"{prefix}/", {"minutes": "Agreed on the next draft", "decisions": "Revise the introduction"}, format="json")
        self.assertEqual(saved.status_code, 200)
        version = saved.json()["version"]
        self.assertEqual(self.client.get(f"{prefix}/").status_code, 200)
        listed = self.client.get(f"/api/v1/coordination/meeting-records/?project={self.project.pk}")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        attendance = self.client.post(f"{prefix}/attendance/", {"user_id": str(self.member.pk), "attended": True, "note": "Present during the check-in"}, format="json")
        self.assertEqual(attendance.status_code, 200)
        action = self.client.post(f"{prefix}/actions/", {"title": "Revise introduction", "description": "Apply the agreed corrections", "assignee_ids": [str(self.member.pk)]}, format="json")
        self.assertEqual(action.status_code, 201)
        task_id = action.json()["actions"][0]["task_id"]
        self.assertTrue(TaskAssignment.objects.filter(task_id=task_id, user=self.member).exists())
        self.authenticate(self.member)
        confirmed = self.client.post(f"{prefix}/confirm/", {"version": version}, format="json")
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["confirmations"][0]["current"])
        self.assertEqual(self.client.post(f"{prefix}/attendance/", {"user_id": str(self.owner.pk), "attended": True, "note": "Not permitted"}, format="json").status_code, 403)

    def test_repeat_api_and_new_claim_review_revision_are_real_records(self):
        meeting = self.meeting()
        self.authenticate(self.owner)
        repeat = self.client.post(f"/api/v1/coordination/meeting-records/{meeting.pk}/repeat/", {"count": 2, "interval_days": 7, "time_zone": "Australia/Sydney"}, format="json")
        self.assertEqual(repeat.status_code, 201)
        self.assertEqual(Meeting.objects.filter(pk__in=repeat.json()["occurrence_ids"]).count(), 2)
        self.authenticate(self.member)
        claim = self.client.post("/api/v1/coordination/claims/", {"project": str(self.project.pk), "title": "Prepared the diagram", "statement": "I prepared and reviewed the architecture diagram."}, format="json")
        self.assertEqual(claim.status_code, 201)
        self.authenticate(self.owner)
        review = self.client.post(f"/api/v1/coordination/claims/{claim.json()['id']}/review/", {"outcome": "confirmed", "note": "Reviewed the delivered architecture diagram"}, format="json")
        self.assertEqual(review.status_code, 201)
        data = self.client.get(f"/api/v1/coordination/claims/?project={self.project.pk}&range_start=2026-10-01&range_end=2026-10-01")
        self.assertEqual(data.status_code, 200)
        self.assertEqual(data.json()["claims"][0]["status"], "team_confirmed")
        self.authenticate(self.member)
        self.assertEqual(self.client.post(f"/api/v1/coordination/claims/{claim.json()['id']}/withdraw/", {}, format="json").status_code, 200)

    def test_joint_attribution_api_requires_the_named_member(self):
        claim = services.create_claim(actor=self.owner, project=self.project, title="Joint research work", statement="We researched the scheduling requirements together.", contributor_ids=[self.member.pk])
        url = f"/api/v1/coordination/claims/{claim.pk}/respond/"
        self.authenticate(self.facilitator)
        self.assertEqual(self.client.post(url, {"response": "confirmed"}, format="json").status_code, 403)
        self.authenticate(self.member)
        self.assertEqual(self.client.post(url, {"response": "confirmed"}, format="json").status_code, 200)

    def test_schema_keeps_every_coordination_operation_and_real_request_contracts(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = {path: methods for path, methods in schema["paths"].items() if path.startswith("/api/v1/coordination/")}
        self.assertGreaterEqual(len(paths), 20)
        ids = [operation["operationId"] for methods in paths.values() for method, operation in methods.items() if method in {"get", "post", "put"}]
        self.assertEqual(len(ids), len(set(ids)))
        request = paths["/api/v1/coordination/polls/"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        self.assertIn("PollWrite", request["$ref"])
        self.assertIn("text/calendar", paths["/api/v1/coordination/calendar/export/"]["get"]["responses"]["200"]["content"])


class CoordinationEvidenceAndCalendarTests(CoordinationFixture):
    def test_complete_evidence_export_separates_sources_and_preserves_history(self):
        with patch("django.utils.timezone.now", return_value=self.now - timedelta(days=40)):
            original = services.create_claim(actor=self.member, project=self.project, title="Original work statement", statement="I implemented the original report layout and reviewed it.")
            services.review_claim(actor=self.owner, claim=original, outcome="changes_requested", note="Add the delivered result link")
        revised = services.create_claim(actor=self.member, project=self.project, title="Revised work statement", statement="I implemented the report layout and linked the delivered output.", artifact_url="https://example.com/output", supersedes=original, contributor_ids=[self.facilitator.pk])
        services.respond_claim(actor=self.facilitator, claim=revised, response="confirmed")
        services.review_claim(actor=self.owner, claim=revised, outcome="confirmed", note="The team reviewed the final output")
        record = services.save_meeting_record(actor=self.owner, meeting=self.meeting(past=True), minutes="Discussed the final report", decisions="Submit after a final review")
        services.confirm_minutes(actor=self.member, record=record, version=record.version)
        services.record_attendance(actor=self.owner, record=record, user_id=self.member.pk, attended=True, note="Present at the check-in")
        action = services.add_action(actor=self.owner, record=record, title="Final report review", description="Read the final report", due_at=None, assignee_ids=[self.member.pk])
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=self.now)
        snapshot = selectors.evidence_export_data(user=self.owner, project=self.project, range_start=date(2026, 10, 1), range_end=date(2026, 10, 1))
        statuses = {row["id"]: row["status"] for row in snapshot["claims"]}
        self.assertEqual(statuses[str(original.pk)], "superseded")
        self.assertEqual(statuses[str(revised.pk)], "team_confirmed")
        self.assertEqual(snapshot["claims"][0]["contributors"][0]["response"], "confirmed")
        former = next(row for row in snapshot["members"] if row["id"] == str(self.member.pk))
        self.assertFalse(former["active"])
        self.assertEqual(former["recorded_attendance"], 1)
        self.assertEqual(snapshot["meetings"][0]["actions"][0]["task_id"], str(action.task_id))
        self.assertTrue(snapshot["meetings"][0]["confirmations"][0]["current"])
        self.assertFalse(snapshot["truncated"])
        encoded = json.dumps(snapshot)
        self.assertNotIn(self.owner.email, encoded)
        self.assertNotIn(self.member.email, encoded)
        self.assertIn("not filtered", snapshot["claim_scope"])
        with self.assertRaises(PermissionDenied):
            selectors.evidence_export_data(user=self.member, project=self.project, range_start=date(2026, 10, 1), range_end=date(2026, 10, 1))

    def test_evidence_export_limits_raise_instead_of_silently_omitting_records(self):
        services.create_claim(actor=self.owner, project=self.project, title="First statement", statement="First retained statement in this project.")
        services.create_claim(actor=self.member, project=self.project, title="Second statement", statement="Second retained statement in this project.")
        limits = dict(selectors.EVIDENCE_EXPORT_LIMITS, claims=1)
        with patch("coordination.selectors.EVIDENCE_EXPORT_LIMITS", limits), self.assertRaises(ValidationError):
            selectors.evidence_export_data(user=self.owner, project=self.project, range_start=date(2026, 10, 1), range_end=date(2026, 10, 1))

    def test_evidence_meeting_range_keeps_corrections_and_excludes_other_dates(self):
        record = services.save_meeting_record(actor=self.owner, meeting=self.meeting(past=True), minutes="First version", decisions="First decision")
        services.save_meeting_record(actor=self.owner, meeting=record.meeting, minutes="Corrected version", decisions="Corrected decision")
        services.record_attendance(actor=self.owner, record=record, user_id=self.member.pk, attended=False, note="Initial observation")
        services.record_attendance(actor=self.owner, record=record, user_id=self.member.pk, attended=True, note="Corrected after checking")
        outside = self.meeting()
        MeetingRecord.objects.create(meeting=outside, minutes="Outside the chosen meeting range")
        CoordinationEvent.objects.create(project=self.project, actor=self.owner, kind="test", object_id=record.id, metadata={"token": "private-secret-value", "email": self.owner.email})
        snapshot = selectors.evidence_export_data(user=self.owner, project=self.project, range_start=date(2026, 10, 1), range_end=date(2026, 10, 1))
        self.assertEqual(len(snapshot["meetings"]), 1)
        self.assertTrue(snapshot["meetings"][0]["attendance"][0]["attended"])
        metadata = [row["metadata"] for row in snapshot["coordination_events"]]
        self.assertTrue(any(row.get("minutes") == "First version" for row in metadata))
        self.assertTrue(any(row.get("from") is False and row.get("to") is True for row in metadata))
        self.assertNotIn("private-secret-value", json.dumps(snapshot))

    def test_calendar_includes_academic_deadlines_and_deduplicates_same_task_date(self):
        due = self.now + timedelta(days=2)
        task = Task.objects.create(project=self.project, created_by=self.owner, title="Prepare assignment", due_at=due)
        TaskAssignment.objects.create(task=task, user=self.member, assigned_by=self.owner)
        TaskPlan.objects.create(task=task, official_due_at=due + timedelta(days=1))
        SubmissionPlan.objects.create(project=self.project, internal_due_at=due + timedelta(days=2), official_due_at=due + timedelta(days=3))
        Milestone.objects.create(project=self.project, title="Rehearsal", due_at=due + timedelta(hours=3))
        result = selectors.calendar_events(user=self.member, range_start=date(2026, 10, 1), range_end=date(2026, 10, 8))
        self.assertEqual({row["kind"] for row in result["events"]}, {"task", "task_official", "submission_internal", "submission_official", "milestone"})
        self.assertTrue(all("deadline" in row["title"] for row in result["events"]))
        self.assertIn(b"SUMMARY:StudyCrew official submission deadline", render_calendar(result["events"], include_details=False))
        TaskPlan.objects.filter(task=task).update(official_due_at=due)
        result = selectors.calendar_events(user=self.member, range_start=date(2026, 10, 1), range_end=date(2026, 10, 8))
        self.assertNotIn("task_official", {row["kind"] for row in result["events"]})
        self.assertIn("official and internal", next(row["title"] for row in result["events"] if row["kind"] == "task"))
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=self.now)
        self.assertEqual(selectors.calendar_events(user=self.member, range_start=date(2026, 10, 1), range_end=date(2026, 10, 8))["events"], [])

    def test_calendar_uses_profile_date_across_utc_midnight(self):
        due = datetime(2026, 10, 1, 15, 30, tzinfo=datetime_timezone.utc)
        task = Task.objects.create(project=self.project, created_by=self.owner, title="After local midnight", due_at=due)
        TaskAssignment.objects.create(task=task, user=self.member, assigned_by=self.owner)
        self.member.profile.time_zone = "Australia/Sydney"
        self.member.profile.save(update_fields=("time_zone",))
        yesterday = selectors.calendar_events(user=self.member, range_start=date(2026, 10, 1), range_end=date(2026, 10, 1))
        today = selectors.calendar_events(user=self.member, range_start=date(2026, 10, 2), range_end=date(2026, 10, 2))
        self.assertEqual(yesterday["events"], [])
        self.assertEqual([row["id"] for row in today["events"]], [str(task.pk)])
