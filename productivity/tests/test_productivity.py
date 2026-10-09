from datetime import datetime, date, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import SimpleTestCase
from django.utils import timezone

from api.tests.base import APIDomainTestCase
from campus.models import ChecklistItem, TaskPlan, TaskDependency
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment
from tasks.services import create_task
from productivity import services
from productivity.models import RecurringTask, RecurringOccurrence, TimeEntry

NOW = datetime(2026, 10, 2, 0, 0, tzinfo=dt_timezone.utc)


class RecurrenceCalendarTests(SimpleTestCase):
    def schedule(self, **changes):
        return RecurringTask(start_local="2027-01-31T17:00:00", timezone_name="Australia/Sydney", frequency="monthly", interval=1, occurrence_limit=12, until_date=date(2028, 1, 31), **changes)

    def test_month_end_returns_to_original_day_after_short_month(self):
        item = self.schedule()
        zone = ZoneInfo(item.timezone_name)
        dates = [services.occurrence_due(item, n).astimezone(zone).date() for n in range(3)]
        self.assertEqual(dates, [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)])

    def test_leap_year_monthly_schedule_clips_february(self):
        item = self.schedule()
        item.start_local = "2028-01-31T17:00:00"
        item.until_date = date(2028, 4, 30)
        self.assertEqual(services.occurrence_due(item, 1).astimezone(ZoneInfo(item.timezone_name)).day, 29)

    def test_weekly_keeps_wall_time_across_offset_change(self):
        item = self.schedule()
        item.frequency = "weekly"
        item.start_local = "2026-09-27T17:00:00"
        before, after = [services.occurrence_due(item, n) for n in (0, 1)]
        self.assertEqual((before.hour, after.hour), (7, 6))

    def test_dst_gap_moves_forward_and_repeat_uses_earlier_fold(self):
        zone = ZoneInfo("Australia/Sydney")
        gap = services.local_instant(datetime(2026, 10, 4, 2, 30), zone)
        repeat = services.local_instant(datetime(2027, 4, 4, 2, 30), zone)
        self.assertEqual(gap.astimezone(zone).hour, 3)
        self.assertEqual(gap.astimezone(zone).minute, 30)
        self.assertEqual(repeat.astimezone(zone).fold, 0)
        self.assertEqual(repeat.astimezone(zone).utcoffset(), timedelta(hours=11))

    def test_count_and_end_date_are_inclusive_limits(self):
        item = self.schedule()
        item.occurrence_limit = 2
        self.assertIsNone(services.occurrence_due(item, 2))
        item.occurrence_limit = 12
        item.until_date = date(2027, 2, 27)
        self.assertIsNone(services.occurrence_due(item, 1))


class ProductivityTests(APIDomainTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Workload follows joined_at, then the membership ID for exact ties.
        # Consecutive Windows timestamps can tie, so this fixture must declare
        # the joining chronology its workload assertions depend on.
        ProjectMembership.objects.filter(project=cls.project, user=cls.owner).update(joined_at=NOW - timedelta(days=2))
        ProjectMembership.objects.filter(project=cls.project, user=cls.member).update(joined_at=NOW - timedelta(days=1))

    def setUp(self):
        super().setUp()
        self.clock = patch("productivity.services.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.task = create_task(project=self.project, actor=self.owner, data={"title": "Weekly reading", "description": "Read chapter", "priority": "high"})
        self.plan = TaskPlan.objects.create(task=self.task, estimate_hours=Decimal("6"), acceptance="Notes complete", tags=["reading"], official_due_at=NOW + timedelta(days=1), review_state="approved")
        ChecklistItem.objects.create(task=self.task, text="Write summary", checked=True)
        TaskAssignment.objects.create(task=self.task, user=self.owner, assigned_by=self.owner)
        TaskAssignment.objects.create(task=self.task, user=self.member, assigned_by=self.owner)

    def schedule(self, **changes):
        data = {"actor": self.owner, "project_id": self.project.id, "task_id": self.task.id,
            "frequency": "weekly", "interval": 1, "timezone_name": "Australia/Sydney",
            "start_local": "2026-10-09T17:00:00", "until_date": date(2027, 10, 9), "occurrence_limit": 3, "lead_days": 7, **changes}
        return services.create_schedule(**data)

    def manual(self, **changes):
        return services.add_manual(actor=changes.pop("actor", self.owner), project_id=changes.pop("project_id", self.project.id), task_id=changes.pop("task_id", self.task.id),
            started_at=changes.pop("started_at", NOW - timedelta(hours=2)), minutes=changes.pop("minutes", 60), note=changes.pop("note", "Private notes"), **changes)

    def test_recurrence_snapshot_generates_real_task_reset_review_checklist_and_dependencies(self):
        predecessor = create_task(project=self.project, actor=self.owner, data={"title": "Previous task"})
        TaskDependency.objects.create(task=self.task, depends_on=predecessor)
        item = self.schedule()
        self.task.title = "Later edit should not change snapshot"
        self.task.save()
        due = NOW + timedelta(days=1)
        self.assertEqual(services.generate_due_recurring_tasks(now=due), 1)
        result = RecurringOccurrence.objects.get(schedule_id=item["id"]).task
        self.assertEqual(result.title, "Weekly reading")
        self.assertEqual(result.status, "todo")
        self.assertEqual(result.academic_plan.estimate_hours, Decimal("6"))
        self.assertEqual(result.academic_plan.review_state, "draft")
        self.assertIsNone(result.academic_plan.official_due_at)
        self.assertFalse(result.academic_checklist.get().checked)
        self.assertFalse(result.academic_dependencies.exists())
        self.assertEqual(result.assignments.count(), 2)

    def test_duplicate_generation_and_bounded_catch_up(self):
        self.schedule(occurrence_limit=2)
        at = NOW + timedelta(days=30)
        self.assertEqual(services.generate_due_recurring_tasks(now=at, limit=1), 1)
        self.assertEqual(services.generate_due_recurring_tasks(now=at), 1)
        self.assertEqual(services.generate_due_recurring_tasks(now=at), 0)
        self.assertEqual(RecurringOccurrence.objects.count(), 2)
        item = RecurringTask.objects.get()
        self.assertIsNotNone(item.stopped_at)
        self.assertEqual(item.stop_reason, "Schedule completed")

    def test_removed_assignee_not_carried_into_new_occurrence(self):
        self.schedule()
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=NOW)
        services.generate_due_recurring_tasks(now=NOW + timedelta(days=1))
        self.assertEqual(list(RecurringOccurrence.objects.get().task.assignments.values_list("user_id", flat=True)), [self.owner.id])

    def test_worker_stops_for_removed_inactive_or_closed_author_and_archive(self):
        for condition in ("removed", "inactive", "closed", "project", "task"):
            with self.subTest(condition=condition):
                RecurringTask.objects.all().delete()
                self.owner.is_active, self.owner.closed_at = True, None
                self.owner.save()
                self.project.archived_at = None
                self.project.save()
                self.task.archived_at = None
                self.task.save()
                ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=None)
                self.schedule()
                if condition == "removed":
                    ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=NOW)
                elif condition == "inactive":
                    self.owner.is_active = False
                    self.owner.save()
                elif condition == "closed":
                    self.owner.closed_at = NOW
                    self.owner.save()
                elif condition == "project":
                    self.project.archived_at = NOW
                    self.project.save()
                else:
                    self.task.archived_at = NOW
                    self.task.save()
                self.assertEqual(services.generate_due_recurring_tasks(now=NOW + timedelta(days=1)), 0)
                self.assertIsNotNone(RecurringTask.objects.get().stopped_at)

    def test_schedule_bounds_invalid_zones_and_duplicate_active_rejected(self):
        for changes in ({"until_date": date(2040, 1, 1)}, {"occurrence_limit": 521}, {"frequency": "daily"}, {"interval": 0}, {"lead_days": 31}, {"timezone_name": "invalid"}, {"start_local": "2026-10-09"}, {"start_local": "2026-10-09T17:00:00+11:00"}, {"start_local": "2020-01-01T17:00:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.schedule(**changes)
        self.schedule()
        with self.assertRaises(ValidationError):
            self.schedule()

    def test_schedule_stop_only_author_or_manager_and_is_idempotent(self):
        item = self.schedule()
        with self.assertRaises(PermissionDenied):
            services.stop_schedule(actor=self.member, project_id=self.project.id, task_id=self.task.id, schedule_id=item["id"])
        for _ in range(2):
            result = services.stop_schedule(actor=self.owner, project_id=self.project.id, task_id=self.task.id, schedule_id=item["id"])
            self.assertIsNotNone(result["stopped_at"])
        self.assertEqual(services.generate_due_recurring_tasks(now=NOW + timedelta(days=30)), 0)

    def test_timer_is_unique_across_projects_and_uses_actual_elapsed(self):
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        with self.assertRaises(ValidationError):
            services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        with patch("productivity.services.timezone.now", return_value=NOW + timedelta(minutes=25)):
            result = services.stop_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id, note="Worked on draft")
        self.assertEqual(result["seconds"], 1500)
        self.assertFalse(result["capped"])

    def test_database_prevents_two_active_timers_and_duplicate_occurrences(self):
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TimeEntry.objects.create(task=self.task, user=self.owner, started_at=NOW, source="timer")
        self.schedule()
        services.generate_due_recurring_tasks(now=NOW + timedelta(days=1))
        item = RecurringOccurrence.objects.get()
        other = create_task(project=self.project, actor=self.owner, data={"title": "Other duplicate task"})
        with self.assertRaises(IntegrityError), transaction.atomic():
            RecurringOccurrence.objects.create(schedule=item.schedule, index=item.index, task=other, due_at=item.due_at)

    def test_very_long_timer_caps_and_can_be_corrected(self):
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        with patch("productivity.services.timezone.now", return_value=NOW + timedelta(days=2)):
            result = services.stop_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        self.assertEqual(result["seconds"], 86400)
        self.assertTrue(result["capped"])

    def test_discard_running_timer_after_access_removed_does_not_leak_task(self):
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=NOW)
        timer = services.active_timer(actor=self.owner)
        self.assertFalse(timer["accessible"])
        self.assertIsNone(timer["title"])
        self.assertIsNone(timer["project_id"])
        with self.assertRaises(PermissionDenied):
            services.stop_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        self.assertTrue(services.discard_timer(actor=self.owner)["discarded"])
        self.assertIsNone(services.active_timer(actor=self.owner))

    def test_manual_records_require_past_nonoverlapping_bounded_work(self):
        self.manual()
        for changes in ({}, {"minutes": 0}, {"minutes": 1441}, {"started_at": NOW}, {"started_at": datetime(2026, 10, 1)}, {"note": "a" * 501}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.manual(**changes)
        self.assertEqual(TimeEntry.objects.count(), 1)

    def test_overlap_with_running_timer_rejected(self):
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        with patch("productivity.services.timezone.now", return_value=NOW + timedelta(hours=2)), self.assertRaises(ValidationError):
            self.manual(started_at=NOW + timedelta(minutes=1), minutes=30)

    def test_correction_requires_own_record_current_version_and_adjusts_totals(self):
        data = self.manual()
        entry = TimeEntry.objects.get(pk=data["id"])
        kwargs = {"actor": self.owner, "project_id": self.project.id, "task_id": self.task.id, "entry_id": entry.id,
            "expected_updated_at": entry.updated_at, "started_at": NOW - timedelta(hours=3), "minutes": 90, "note": "Corrected"}
        with self.assertRaises(Http404):
            services.correct_entry(**{**kwargs, "actor": self.member})
        with self.assertRaises(ValidationError):
            services.correct_entry(**{**kwargs, "expected_updated_at": NOW - timedelta(days=1)})
        result = services.correct_entry(**kwargs)
        self.assertEqual(result["seconds"], 5400)
        self.assertIsNotNone(result["corrected_at"])
        self.assertEqual(services.task_overview(actor=self.owner, project_id=self.project.id, task_id=self.task.id)["actual_seconds"], 5400)

    def test_discard_record_clears_note_and_excludes_totals(self):
        result = self.manual()
        services.delete_entry(actor=self.owner, project_id=self.project.id, task_id=self.task.id, entry_id=result["id"], expected_updated_at=result["updated_at"])
        entry = TimeEntry.objects.get()
        self.assertEqual(entry.note, "")
        self.assertIsNotNone(entry.cancelled_at)
        self.assertEqual(services.workload(actor=self.owner, project_id=self.project.id)["actual_seconds"], 0)

    def test_archived_project_and_task_block_new_time_but_allow_read(self):
        self.manual()
        self.project.archived_at = NOW
        self.project.save()
        with self.assertRaises(ValidationError):
            self.manual(started_at=NOW - timedelta(hours=4))
        overview = services.task_overview(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        self.assertTrue(overview["read_only"])
        self.assertEqual(overview["actual_seconds"], 3600)

    def test_fresh_closed_actor_rejected_for_all_mutations(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False, closed_at=NOW)
        for action in (lambda: self.schedule(), lambda: self.manual(), lambda: services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id), lambda: services.workload(actor=self.owner, project_id=self.project.id)):
            with self.assertRaises(PermissionDenied):
                action()

    def test_workload_equal_estimate_share_due_distribution_and_private_notes(self):
        self.task.due_at = NOW - timedelta(hours=1)
        self.task.save()
        self.manual(note="Personal sensitive note")
        data = services.workload(actor=self.member, project_id=self.project.id)
        self.assertEqual([row["user_id"] for row in data["members"]], [str(self.owner.id), str(self.member.id)])
        self.assertEqual([row["assigned_estimate_hours"] for row in data["members"]], ["3.00", "3.00"])
        self.assertEqual(data["members"][0]["due"]["overdue"], 1)
        self.assertEqual(data["members"][0]["actual_seconds"], 3600)
        self.assertNotIn("Personal sensitive note", str(data))
        other_overview = services.task_overview(actor=self.member, project_id=self.project.id, task_id=self.task.id)
        self.assertEqual(other_overview["entries"], [])
        self.assertEqual(other_overview["actual_seconds"], 3600)

    def test_workload_keeps_joining_order_instead_of_role_or_recorded_hours(self):
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(joined_at=NOW - timedelta(days=3))
        self.manual()
        data = services.workload(actor=self.member, project_id=self.project.id)
        self.assertEqual([row["user_id"] for row in data["members"]], [str(self.member.id), str(self.owner.id)])
        self.assertEqual([row["actual_seconds"] for row in data["members"]], [0, 3600])

    def test_unassigned_estimates_and_completed_running_time_exclusions(self):
        self.task.assignments.all().delete()
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        result = services.workload(actor=self.owner, project_id=self.project.id)
        self.assertEqual(result["unassigned"]["open_tasks"], 1)
        self.assertEqual(result["unassigned"]["estimate_hours"], "6.00")
        self.assertEqual(result["actual_seconds"], 0)
        self.task.status, self.task.completed_at = "done", NOW
        self.task.save()
        self.assertEqual(services.workload(actor=self.owner, project_id=self.project.id)["unassigned"]["open_tasks"], 0)

    def test_export_withholds_former_project_details_and_closure_stops_scrubs(self):
        self.manual()
        self.schedule()
        services.start_timer(actor=self.owner, project_id=self.project.id, task_id=self.task.id)
        ProjectMembership.objects.filter(project=self.project, user=self.owner).update(removed_at=NOW)
        data = services.personal_data(self.owner)
        self.assertTrue(data["time_entries"][0]["content_withheld"])
        self.assertEqual(data["time_entries"][0]["note"], "")
        services.close_user(self.owner)
        self.assertFalse(TimeEntry.objects.filter(user=self.owner, ended_at__isnull=True, cancelled_at__isnull=True).exists())
        self.assertEqual(set(TimeEntry.objects.values_list("note", flat=True)), {""})
        self.assertIsNotNone(RecurringTask.objects.get().stopped_at)
        self.assertEqual(RecurringTask.objects.get().snapshot, {})

    def test_api_cross_project_auth_datetime_offset_and_validation(self):
        self.authenticate(self.owner)
        prefix = f"/api/v1/productivity/projects/{self.project.id}/tasks/{self.task.id}/"
        response = self.client.post(prefix + "time/", {"started_at": "2026-10-01T10:00:00", "minutes": 60}, format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(prefix + "time/", {"started_at": "2026-10-01T10:00:00+10:00", "minutes": 60}, format="json")
        self.assertEqual(response.status_code, 201)
        self.authenticate(self.outsider)
        self.assertEqual(self.client.get(prefix).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/productivity/projects/{self.project.id}/workload/").status_code, 403)
        self.authenticate(self.owner)
        other = Project.objects.create(name="Different private project", created_by=self.owner)
        ProjectMembership.objects.create(project=other, user=self.owner, role="owner")
        self.assertEqual(self.client.get(f"/api/v1/productivity/projects/{other.id}/tasks/{self.task.id}/").status_code, 404)

    def test_task_time_pagination_and_invalid_page(self):
        for i in range(21):
            self.manual(started_at=NOW - timedelta(days=i + 1))
        result = services.task_overview(actor=self.owner, project_id=self.project.id, task_id=self.task.id, page=2)
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["pages"], 2)
        for page in (0, 3, "bad"):
            with self.assertRaises(ValidationError):
                services.task_overview(actor=self.owner, project_id=self.project.id, task_id=self.task.id, page=page)
