from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from accounts.tests.helpers import VALID_PASSWORD
from meetings.models import Meeting
from operations.models import OutboundMessage
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   PUBLIC_BASE_URL="https://studycrew.example", MAIL_DAILY_LIMIT=1000,
                   OPERATIONS_RATE_LIMITS=False)
class OperationsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="owner@example.com", password=VALID_PASSWORD)
        cls.member = User.objects.create_user(email="member@example.com", password=VALID_PASSWORD)
        cls.outsider = User.objects.create_user(email="outsider@example.com", password=VALID_PASSWORD)
        cls.project = Project.objects.create(name="University team", created_by=cls.owner)
        ProjectMembership.objects.create(project=cls.project, user=cls.owner, role="owner")
        cls.membership = ProjectMembership.objects.create(project=cls.project, user=cls.member)
        cls.task = Task.objects.create(project=cls.project, title="Report section", created_by=cls.owner,
                                       due_at=timezone.now() + timedelta(hours=3))
        TaskAssignment.objects.create(task=cls.task, user=cls.member, assigned_by=cls.owner)
        cls.meeting = Meeting.objects.create(project=cls.project, title="Planning meeting", organiser=cls.owner,
                                             starts_at=timezone.now() + timedelta(hours=2), ends_at=timezone.now() + timedelta(hours=3))

    def moderator(self):
        from django.contrib.auth.models import Permission
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.owner.user_permissions.add(*Permission.objects.filter(codename__in=["manage_user_status", "moderate_reports"]))
        return self.owner

    def message(self, **values):
        return OutboundMessage.objects.create(user=self.member, project=self.project,
            recipient=self.member.email, subject="Task reminder", body="Team task detail",
            deduplication_key=f"test:{OutboundMessage.objects.count()}", category="task_due",
            target_type="task", target_id=self.task.pk, target_revision=self.task.due_at.isoformat(),
            **values)

    def signin(self, user=None, *, mfa=True, client=None):
        target = client or self.client
        target.force_login(user or self.member)
        if mfa:
            session = target.session
            session["mfa_verified_at"] = timezone.now().isoformat()
            session.save()
        return target
