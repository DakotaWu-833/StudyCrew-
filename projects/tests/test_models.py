from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from projects.models import ProjectInvitation, ProjectMembership
from projects.services import create_project


class ProjectModelConstraintTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="owner@example.com",
            password="StrongPass!123",
            display_name="Owner",
        )
        self.other = user_model.objects.create_user(
            email="other@example.com",
            password="StrongPass!123",
            display_name="Other",
        )
        self.project = create_project(actor=self.owner, name="Model project")

    def test_database_allows_only_one_active_owner(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectMembership.objects.create(
                    project=self.project,
                    user=self.other,
                    role=ProjectMembership.Role.OWNER,
                )

    def test_membership_pair_is_unique_even_after_soft_removal(self):
        membership = ProjectMembership.objects.create(
            project=self.project,
            user=self.other,
            removed_at=timezone.now(),
        )
        self.assertFalse(membership.is_active)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectMembership.objects.create(project=self.project, user=self.other)

    def test_invitation_normalises_email_before_save(self):
        invitation = ProjectInvitation.objects.create(
            project=self.project,
            invited_email="  PERSON@Example.COM ",
            invited_by=self.owner,
            token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.assertEqual(invitation.invited_email, "person@example.com")

    def test_pending_invitation_requires_future_expiry(self):
        invitation = ProjectInvitation(
            project=self.project,
            invited_email="person@example.com",
            invited_by=self.owner,
            token_hash="a" * 64,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(ValidationError):
            invitation.full_clean()

    def test_token_digest_must_be_sha256_hex(self):
        invitation = ProjectInvitation(
            project=self.project,
            invited_email="person@example.com",
            invited_by=self.owner,
            token_hash="not-a-digest",
            expires_at=timezone.now() + timedelta(days=7),
        )
        with self.assertRaises(ValidationError):
            invitation.full_clean()
