"""Real simultaneous writers serialize by task version and receipt identity."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections, connections
from django.test import TransactionTestCase

from activity.models import ActivityEvent
from offline_sync import services
from offline_sync.models import TaskSyncReceipt
from projects.models import Project, ProjectMembership
from tasks.models import Task
from tasks.services import update_task


class OfflineEditConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(email="offline-race@example.com", password="Strong!Passphrase42", display_name="Concurrent editor")
        self.project = Project.objects.create(name="Offline race team", created_by=self.actor)
        ProjectMembership.objects.create(project=self.project, user=self.actor, role="owner")
        self.task = Task.objects.create(project=self.project, created_by=self.actor, title="Original racing task")
        self.base = self.task.updated_at

    def concurrent(self, action):
        barrier = Barrier(2)

        def run(index):
            close_old_connections()
            barrier.wait(timeout=5)
            deadline = monotonic()+5
            try:
                while True:
                    try:
                        return action(index)
                    except OperationalError as error:
                        # SQLite's shared-memory SQLITE_LOCKED bypasses busy_timeout.
                        # Retry the whole rolled-back use case, never an inner write.
                        if "locked" not in str(error).lower() or monotonic() >= deadline:
                            raise
                        close_old_connections()
                        sleep(.02)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(run, index) for index in range(2)]
            return [item.result(timeout=10) for item in pending]

    def test_simultaneous_identical_offline_retries_apply_once(self):
        mutation = uuid4()
        def action(index):
            actor = get_user_model().objects.get(pk=self.actor.pk)
            _, duplicate = services.synchronize(actor=actor, task_id=self.task.pk, mutation_id=mutation, expected_updated_at=self.base, changes={"title": "Exactly once racing edit"})
            return duplicate
        self.assertCountEqual(self.concurrent(action), [False, True])
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)
        self.assertEqual(ActivityEvent.objects.filter(target_id=self.task.pk, event_type="task_updated").count(), 1)

    def test_simultaneous_distinct_offline_changes_allow_one_and_conflict_other(self):
        mutations = [uuid4(), uuid4()]
        def action(index):
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                services.synchronize(actor=actor, task_id=self.task.pk, mutation_id=mutations[index], expected_updated_at=self.base, changes={"title": f"Concurrent offline edit {index}"})
                return "applied"
            except services.EditConflict:
                return "conflict"
        self.assertCountEqual(self.concurrent(action), ["applied", "conflict"])
        self.assertEqual(TaskSyncReceipt.objects.count(), 1)
        self.assertEqual(ActivityEvent.objects.filter(target_id=self.task.pk, event_type="task_updated").count(), 1)
        self.task.refresh_from_db()
        self.assertIn(self.task.title, {"Concurrent offline edit 0", "Concurrent offline edit 1"})

    def test_simultaneous_online_and_offline_version_checked_edits_cannot_overwrite(self):
        mutation = uuid4()
        def action(index):
            actor = get_user_model().objects.get(pk=self.actor.pk)
            try:
                if index == 0:
                    loaded = Task.objects.get(pk=self.task.pk)
                    update_task(task=loaded, actor=actor, data={"title": "Winning online draft", "expected_updated_at": self.base})
                else:
                    services.synchronize(actor=actor, task_id=self.task.pk, mutation_id=mutation, expected_updated_at=self.base, changes={"title": "Winning offline draft"})
                return "applied"
            except (services.EditConflict, ValidationError):
                return "conflict"
        self.assertCountEqual(self.concurrent(action), ["applied", "conflict"])
        self.assertEqual(ActivityEvent.objects.filter(target_id=self.task.pk, event_type="task_updated").count(), 1)
        self.task.refresh_from_db()
        self.assertIn(self.task.title, {"Winning online draft", "Winning offline draft"})
        self.assertEqual(TaskSyncReceipt.objects.count(), int(self.task.title == "Winning offline draft"))
