from django.contrib.auth import get_user_model
from django.test import TestCase

from projects.models import Project, ProjectMembership


class TaskDomainTestCase(TestCase):
    password = "Strong!Passphrase42"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(
            email="owner@example.com",
            password=cls.password,
            display_name="Project Owner",
        )
        cls.member = User.objects.create_user(
            email="member@example.com",
            password=cls.password,
            display_name="Team Member",
        )
        cls.facilitator = User.objects.create_user(
            email="facilitator@example.com",
            password=cls.password,
            display_name="Team Facilitator",
        )
        cls.outsider = User.objects.create_user(
            email="outsider@example.com",
            password=cls.password,
            display_name="Outside User",
        )
        cls.project = Project.objects.create(name="StudyCrew", created_by=cls.owner)
        ProjectMembership.objects.create(
            project=cls.project,
            user=cls.owner,
            role=ProjectMembership.Role.OWNER,
        )
        ProjectMembership.objects.create(
            project=cls.project,
            user=cls.member,
            role=ProjectMembership.Role.MEMBER,
        )
        ProjectMembership.objects.create(
            project=cls.project,
            user=cls.facilitator,
            role=ProjectMembership.Role.FACILITATOR,
        )

    def make_task(self, **overrides):
        from tasks.models import Task

        values = {
            "project": self.project,
            "created_by": self.owner,
            "title": "Prepare project demonstration",
        }
        values.update(overrides)
        return Task.objects.create(**values)
