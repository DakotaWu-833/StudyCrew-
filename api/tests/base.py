from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.session_security import MFA_VERIFIED_SESSION_KEY
from projects.models import Project, ProjectMembership


class APIDomainTestCase(TestCase):
    password = "Strong!Passphrase42"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(
            email="api-owner@example.com", password=cls.password, display_name="API Owner"
        )
        cls.member = User.objects.create_user(
            email="api-member@example.com", password=cls.password, display_name="API Member"
        )
        cls.outsider = User.objects.create_user(
            email="api-outsider@example.com", password=cls.password, display_name="API Outsider"
        )
        cls.project = Project.objects.create(name="API project", created_by=cls.owner)
        ProjectMembership.objects.create(
            project=cls.project, user=cls.owner, role=ProjectMembership.Role.OWNER
        )
        ProjectMembership.objects.create(project=cls.project, user=cls.member)

    def setUp(self):
        self.client = APIClient()

    def authenticate(self, user=None, *, client=None):
        user = user or self.owner
        client = client or self.client
        client.force_login(user)
        session = client.session
        session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat()
        session.save()
        return client
