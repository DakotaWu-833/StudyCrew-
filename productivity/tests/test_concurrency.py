"""Exercise concurrent real database writes, including SQLite lock retries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from time import monotonic, sleep

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections, connections
from django.test import TransactionTestCase
from django.utils import timezone

from projects.models import Project, ProjectMembership
from tasks.models import Task
from productivity import services
from productivity.models import RecurringOccurrence, TimeEntry


class ProductivityConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="concurrent-time@example.com", password="Strong!Passphrase42", display_name="Timer owner")
        self.projects = [Project.objects.create(name=f"Concurrent team {index}", created_by=self.user) for index in range(2)]
        for project in self.projects:
            ProjectMembership.objects.create(project=project, user=self.user, role="owner")
        self.tasks = [Task.objects.create(project=project, created_by=self.user, title="Concurrent reading task") for project in self.projects]

    def concurrent(self, action):
        barrier = Barrier(2)

        def run(index):
            close_old_connections()
            barrier.wait(timeout=5)
            deadline = monotonic() + 5
            try:
                while True:
                    try:
                        return action(index)
                    except OperationalError as error:
                        # In-memory SQLite signals SQLITE_LOCKED immediately;
                        # retry the whole transaction as the local worker does.
                        if "locked" not in str(error).lower() or monotonic() >= deadline:
                            raise
                        close_old_connections()
                        sleep(.02)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, index) for index in range(2)]
            return [future.result(timeout=10) for future in futures]

    def test_simultaneous_timer_starts_on_different_projects_allow_only_one(self):
        def action(index):
            actor = get_user_model().objects.get(pk=self.user.pk)
            try:
                services.start_timer(actor=actor, project_id=self.projects[index].id, task_id=self.tasks[index].id)
                return "started"
            except ValidationError:
                return "conflict"

        self.assertCountEqual(self.concurrent(action), ["started", "conflict"])
        self.assertEqual(TimeEntry.objects.filter(user=self.user, ended_at__isnull=True, cancelled_at__isnull=True).count(), 1)

    def test_simultaneous_workers_generate_one_occurrence_once(self):
        start = timezone.now() + timedelta(days=1)
        item = services.create_schedule(actor=self.user, project_id=self.projects[0].id, task_id=self.tasks[0].id,
            frequency="weekly", interval=1, timezone_name="UTC", start_local=start.replace(tzinfo=None, microsecond=0).isoformat(),
            until_date=date(start.year, start.month, start.day), occurrence_limit=1, lead_days=7)
        results = self.concurrent(lambda _: services.generate_due_recurring_tasks(now=timezone.now()))
        self.assertCountEqual(results, [1, 0])
        self.assertEqual(RecurringOccurrence.objects.filter(schedule_id=item["id"]).count(), 1)
