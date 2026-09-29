from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from projects.models import Project, ProjectMembership
from projects.policies import (
    active_membership,
    is_authenticated_active,
    is_project_member,
    is_project_manager,
    is_project_owner,
    require_project_member,
    require_project_manager,
    require_project_owner,
)


class ProjectPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(
            email="policy-owner@example.com",
            password="Strong!Passphrase42",
            display_name="Policy Owner",
        )
        cls.member = User.objects.create_user(
            email="policy-member@example.com",
            password="Strong!Passphrase42",
            display_name="Policy Member",
        )
        cls.outsider = User.objects.create_user(
            email="policy-outsider@example.com",
            password="Strong!Passphrase42",
            display_name="Policy Outsider",
        )
        cls.inactive = User.objects.create_user(
            email="policy-inactive@example.com",
            password="Strong!Passphrase42",
            display_name="Inactive Member",
            is_active=False,
        )
        cls.project = Project.objects.create(name="Policy project", created_by=cls.owner)
        cls.owner_membership = ProjectMembership.objects.create(
            project=cls.project,
            user=cls.owner,
            role=ProjectMembership.Role.OWNER,
        )
        cls.member_membership = ProjectMembership.objects.create(
            project=cls.project,
            user=cls.member,
            role=ProjectMembership.Role.MEMBER,
        )
        cls.inactive_membership = ProjectMembership.objects.create(
            project=cls.project,
            user=cls.inactive,
            role=ProjectMembership.Role.MEMBER,
        )
        cls.facilitator = User.objects.create_user(
            email="policy-facilitator@example.com",
            password="Strong!Passphrase42",
            display_name="Policy Facilitator",
        )
        cls.facilitator_membership = ProjectMembership.objects.create(
            project=cls.project,
            user=cls.facilitator,
            role=ProjectMembership.Role.FACILITATOR,
        )

    def test_authentication_requires_authenticated_and_active_user(self):
        self.assertFalse(is_authenticated_active(AnonymousUser()))
        self.assertFalse(is_authenticated_active(self.inactive))
        self.assertTrue(is_authenticated_active(self.owner))

    def test_active_membership_hides_removed_and_inactive_accounts(self):
        self.assertEqual(active_membership(self.member, self.project), self.member_membership)
        self.assertIsNone(active_membership(self.inactive, self.project))

        self.member_membership.removed_at = timezone.now()
        self.member_membership.save(update_fields=("removed_at",))
        self.assertIsNone(active_membership(self.member, self.project))
        self.assertFalse(is_project_member(self.member, self.project))

    def test_member_and_owner_helpers_return_correct_roles(self):
        self.assertTrue(is_project_member(self.owner, self.project))
        self.assertTrue(is_project_owner(self.owner, self.project))
        self.assertFalse(is_project_owner(self.member, self.project))
        self.assertFalse(is_project_member(self.outsider, self.project))
        self.assertEqual(require_project_member(self.member, self.project), self.member_membership)
        self.assertEqual(require_project_owner(self.owner, self.project), self.owner_membership)

    def test_require_helpers_raise_for_missing_or_wrong_membership(self):
        with self.assertRaises(PermissionDenied):
            require_project_member(self.outsider, self.project)
        with self.assertRaises(PermissionDenied):
            require_project_owner(self.member, self.project)

    def test_project_manager_is_limited_to_active_owner_and_facilitator(self):
        self.assertTrue(is_project_manager(self.owner, self.project))
        self.assertTrue(is_project_manager(self.facilitator, self.project))
        self.assertFalse(is_project_manager(self.member, self.project))
        self.assertFalse(is_project_manager(self.outsider, self.project))
        self.assertEqual(
            require_project_manager(self.facilitator, self.project),
            self.facilitator_membership,
        )
        with self.assertRaises(PermissionDenied):
            require_project_manager(self.member, self.project)
