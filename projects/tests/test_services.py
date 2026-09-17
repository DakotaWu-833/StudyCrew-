import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from activity.models import ActivityEvent, Notification
from projects.exceptions import (
    DuplicateInvitation,
    ExistingMember,
    InvalidRole,
    InvitationExpired,
    InvitationUnavailable,
    MembershipNotFound,
    SoleOwnerViolation,
)
from projects.models import Project, ProjectInvitation, ProjectMembership
from projects.policies import is_project_member, is_project_owner
from projects.selectors import (
    memberships_for_project,
    pending_invitations_for_user,
    invitation_for_token,
    project_for_user,
    projects_for_user,
)
from projects.services import (
    accept_invitation,
    archive_project,
    cancel_invitation,
    change_member_role,
    create_project,
    decline_invitation,
    invite_member,
    remove_member,
    transfer_ownership,
    update_project,
)
from tasks.models import Task, TaskAssignment


class ProjectCreationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="creator@example.com",
            password="StrongPass!123",
            display_name="Creator",
        )

    def test_create_project_is_one_atomic_owner_and_event_write(self):
        project = create_project(
            actor=self.user,
            name="  Study Crew  ",
            description="  Shared work  ",
        )
        self.assertEqual(project.name, "Study Crew")
        self.assertEqual(project.description, "Shared work")
        membership = ProjectMembership.objects.get(project=project, user=self.user)
        self.assertEqual(membership.role, ProjectMembership.Role.OWNER)
        event = ActivityEvent.objects.get(project=project)
        self.assertEqual(event.event_type, ActivityEvent.Type.PROJECT_CREATED)
        self.assertEqual(event.target_id, project.id)

    def test_create_project_rolls_back_when_evidence_write_fails(self):
        with patch("projects.services.record_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                create_project(actor=self.user, name="Rolled back")
        self.assertFalse(Project.objects.filter(name="Rolled back").exists())
        self.assertEqual(ProjectMembership.objects.count(), 0)


class ProjectWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="owner@example.com",
            password="StrongPass!123",
            display_name="Owner",
        )
        self.invitee = user_model.objects.create_user(
            email="invitee@example.com",
            password="StrongPass!123",
            display_name="Invitee",
        )
        self.other = user_model.objects.create_user(
            email="other@example.com",
            password="StrongPass!123",
            display_name="Other",
        )
        self.outsider = user_model.objects.create_user(
            email="outsider@example.com",
            password="StrongPass!123",
            display_name="Outsider",
        )
        self.project = create_project(actor=self.owner, name="Main project")

    def add_member(self, user, role=ProjectMembership.Role.MEMBER):
        return ProjectMembership.objects.create(
            project=self.project,
            user=user,
            role=role,
        )

    def test_owner_can_update_project_and_noop_creates_no_extra_event(self):
        updated = update_project(
            project=self.project,
            actor=self.owner,
            data={"name": "  Revised project  ", "description": " New scope "},
        )
        self.assertEqual(updated.name, "Revised project")
        self.assertEqual(updated.description, "New scope")
        event = ActivityEvent.objects.get(
            project=self.project,
            event_type=ActivityEvent.Type.PROJECT_UPDATED,
        )
        self.assertEqual(event.metadata["changed_fields"], ["description", "name"])
        before = ActivityEvent.objects.count()
        update_project(project=updated, actor=self.owner, data={"name": updated.name})
        self.assertEqual(ActivityEvent.objects.count(), before)

    def test_non_owner_cannot_update_or_archive_project(self):
        self.add_member(self.other)
        with self.assertRaises(PermissionDenied):
            update_project(
                project=self.project,
                actor=self.other,
                data={"name": "Not authorised"},
            )
        with self.assertRaises(PermissionDenied):
            archive_project(project=self.project, actor=self.other)

    def test_project_update_rolls_back_when_event_write_fails(self):
        original_name = self.project.name
        with patch("projects.services.record_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                update_project(
                    project=self.project,
                    actor=self.owner,
                    data={"name": "Should roll back"},
                )
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, original_name)

    def test_archive_is_soft_audited_and_idempotent(self):
        archived = archive_project(project=self.project, actor=self.owner)
        self.assertIsNotNone(archived.archived_at)
        self.assertTrue(ProjectMembership.objects.filter(project=self.project).exists())
        self.assertTrue(
            ActivityEvent.objects.filter(
                project=self.project,
                event_type=ActivityEvent.Type.PROJECT_ARCHIVED,
            ).exists()
        )
        before = ActivityEvent.objects.count()
        archive_project(project=archived, actor=self.owner)
        self.assertEqual(ActivityEvent.objects.count(), before)
        with self.assertRaises(ValidationError):
            update_project(
                project=archived,
                actor=self.owner,
                data={"name": "Cannot edit archived"},
            )

    def test_archive_cancels_pending_invitations_at_the_same_time(self):
        first = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        second = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.other.email,
        )
        archived_at = timezone.now()

        archive_project(project=self.project, actor=self.owner, at=archived_at)

        for invitation in (first.invitation, second.invitation):
            invitation.refresh_from_db()
            self.assertEqual(invitation.status, ProjectInvitation.Status.CANCELLED)
            self.assertEqual(invitation.responded_at, archived_at)
        self.assertEqual(
            ActivityEvent.objects.filter(
                project=self.project,
                event_type=ActivityEvent.Type.PROJECT_ARCHIVED,
            ).count(),
            1,
        )
        self.assertFalse(
            ActivityEvent.objects.filter(
                project=self.project,
                event_type=ActivityEvent.Type.INVITATION_CANCELLED,
            ).exists()
        )

    def test_archive_rolls_back_invitation_cancellation_when_audit_write_fails(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )

        with patch("projects.services.record_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                archive_project(project=self.project, actor=self.owner)

        self.project.refresh_from_db()
        dispatch.invitation.refresh_from_db()
        self.assertIsNone(self.project.archived_at)
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.PENDING)
        self.assertIsNone(dispatch.invitation.responded_at)

    def test_archived_project_is_read_only_for_owner_workflows(self):
        membership = self.add_member(self.invitee)
        archive_project(project=self.project, actor=self.owner)
        before_events = ActivityEvent.objects.count()

        operations = {
            "update project": lambda: update_project(
                project=self.project,
                actor=self.owner,
                data={"name": "Changed after archive"},
            ),
            "invite member": lambda: invite_member(
                actor=self.owner,
                project=self.project,
                invited_email=self.other.email,
            ),
            "change role": lambda: change_member_role(
                actor=self.owner,
                project=self.project,
                member=self.invitee,
                role=ProjectMembership.Role.FACILITATOR,
            ),
            "remove member": lambda: remove_member(
                actor=self.owner,
                project=self.project,
                member=self.invitee,
            ),
            "transfer ownership": lambda: transfer_ownership(
                actor=self.owner,
                project=self.project,
                new_owner=self.invitee,
            ),
        }
        for label, operation in operations.items():
            with self.subTest(operation=label):
                with self.assertRaisesMessage(ValidationError, "read-only"):
                    operation()

        membership.refresh_from_db()
        self.assertEqual(membership.role, ProjectMembership.Role.MEMBER)
        self.assertIsNone(membership.removed_at)
        self.assertFalse(
            ProjectInvitation.objects.filter(
                project=self.project,
                invited_email=self.other.email,
            ).exists()
        )
        self.assertEqual(ActivityEvent.objects.count(), before_events)

    def test_pending_selector_excludes_invitations_for_archived_projects(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        Project.objects.filter(pk=self.project.pk).update(archived_at=timezone.now())

        self.assertEqual(list(pending_invitations_for_user(self.invitee)), [])
        dispatch.invitation.refresh_from_db()
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.PENDING)

    def test_pending_invitation_cannot_be_resolved_after_project_is_archived(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        Project.objects.filter(pk=self.project.pk).update(archived_at=timezone.now())

        invitation_operations = {
            "accept": lambda: accept_invitation(
                actor=self.invitee,
                raw_token=dispatch.token,
            ),
            "decline": lambda: decline_invitation(
                actor=self.invitee,
                raw_token=dispatch.token,
            ),
            "cancel": lambda: cancel_invitation(
                actor=self.owner,
                invitation=dispatch.invitation,
            ),
        }
        for label, operation in invitation_operations.items():
            with self.subTest(operation=label):
                with self.assertRaisesMessage(InvitationUnavailable, "read-only"):
                    operation()

        dispatch.invitation.refresh_from_db()
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.PENDING)
        self.assertFalse(
            ProjectMembership.objects.filter(project=self.project, user=self.invitee).exists()
        )

    def test_invitation_is_normalised_hashed_seven_days_and_notified(self):
        at = timezone.now()
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=" INVITEE@EXAMPLE.COM ",
            at=at,
        )
        invitation = dispatch.invitation
        self.assertEqual(invitation.invited_email, "invitee@example.com")
        self.assertEqual(invitation.expires_at, at + timedelta(days=7))
        self.assertNotEqual(invitation.token_hash, dispatch.token)
        self.assertEqual(
            invitation.token_hash,
            hashlib.sha256(dispatch.token.encode("utf-8")).hexdigest(),
        )
        notification = Notification.objects.get(recipient=self.invitee)
        self.assertEqual(notification.notification_type, Notification.Type.INVITATION)
        self.assertEqual(notification.source_event.target_id, invitation.id)

    def test_inviting_unregistered_email_still_succeeds_without_notification(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email="new@example.com",
        )
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.PENDING)
        self.assertFalse(Notification.objects.filter(project=self.project).exists())

    def test_duplicate_pending_invitation_is_rejected(self):
        invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        with self.assertRaises(DuplicateInvitation):
            invite_member(
                actor=self.owner,
                project=self.project,
                invited_email=self.invitee.email.upper(),
            )

    def test_owner_cannot_invite_an_active_member(self):
        self.add_member(self.invitee)
        with self.assertRaises(ExistingMember):
            invite_member(
                actor=self.owner,
                project=self.project,
                invited_email=self.invitee.email,
            )

    def test_non_owner_cannot_invite(self):
        self.add_member(self.other)
        with self.assertRaises(PermissionDenied):
            invite_member(
                actor=self.other,
                project=self.project,
                invited_email=self.invitee.email,
            )

    def test_non_member_and_inactive_user_cannot_initiate_project_writes(self):
        with self.assertRaises(PermissionDenied):
            invite_member(
                actor=self.outsider,
                project=self.project,
                invited_email=self.invitee.email,
            )
        self.owner.is_active = False
        self.owner.save(update_fields=("is_active", "updated_at"))
        with self.assertRaises(PermissionDenied):
            invite_member(
                actor=self.owner,
                project=self.project,
                invited_email=self.invitee.email,
            )

    def test_empty_invitation_email_is_rejected(self):
        with self.assertRaises(ValidationError):
            invite_member(actor=self.owner, project=self.project, invited_email="  ")

    def test_expired_pending_invitation_is_replaced(self):
        first = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        ProjectInvitation.objects.filter(pk=first.invitation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        second = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        first.invitation.refresh_from_db()
        self.assertEqual(first.invitation.status, ProjectInvitation.Status.EXPIRED)
        self.assertNotEqual(first.invitation.id, second.invitation.id)

    def test_accept_invitation_creates_one_membership_and_event(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        membership = accept_invitation(actor=self.invitee, raw_token=dispatch.token)
        dispatch.invitation.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.role, ProjectMembership.Role.MEMBER)
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.ACCEPTED)
        self.assertEqual(
            ActivityEvent.objects.filter(
                project=self.project,
                event_type=ActivityEvent.Type.MEMBER_JOINED,
                target_id=membership.id,
            ).count(),
            1,
        )
        with self.assertRaises(InvitationUnavailable):
            accept_invitation(actor=self.invitee, raw_token=dispatch.token)
        self.assertEqual(
            ProjectMembership.objects.filter(project=self.project, user=self.invitee).count(),
            1,
        )

    def test_wrong_user_cannot_resolve_invitation(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        with self.assertRaises(PermissionDenied):
            accept_invitation(actor=self.other, raw_token=dispatch.token)
        dispatch.invitation.refresh_from_db()
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.PENDING)

    def test_missing_invitation_token_does_not_reveal_details(self):
        from projects.exceptions import InvitationNotFound

        with self.assertRaises(InvitationNotFound):
            accept_invitation(actor=self.invitee, raw_token="")
        with self.assertRaises(InvitationNotFound):
            accept_invitation(actor=self.invitee, raw_token="unknown-token")

    def test_expired_invitation_is_persisted_as_expired(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        expired_at = timezone.now() - timedelta(seconds=1)
        ProjectInvitation.objects.filter(pk=dispatch.invitation.pk).update(expires_at=expired_at)
        with self.assertRaises(InvitationExpired):
            accept_invitation(
                actor=self.invitee,
                raw_token=dispatch.token,
                at=timezone.now(),
            )
        dispatch.invitation.refresh_from_db()
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.EXPIRED)
        self.assertFalse(
            ProjectMembership.objects.filter(project=self.project, user=self.invitee).exists()
        )

    def test_declining_does_not_create_membership(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        invitation = decline_invitation(actor=self.invitee, raw_token=dispatch.token)
        self.assertEqual(invitation.status, ProjectInvitation.Status.DECLINED)
        self.assertFalse(
            ProjectMembership.objects.filter(project=self.project, user=self.invitee).exists()
        )
        self.assertTrue(
            ActivityEvent.objects.filter(
                project=self.project,
                event_type=ActivityEvent.Type.INVITATION_DECLINED,
            ).exists()
        )
        with self.assertRaises(InvitationUnavailable):
            decline_invitation(actor=self.invitee, raw_token=dispatch.token)

    def test_declining_an_expired_invitation_persists_expiry(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        ProjectInvitation.objects.filter(pk=dispatch.invitation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(InvitationExpired):
            decline_invitation(actor=self.invitee, raw_token=dispatch.token)
        dispatch.invitation.refresh_from_db()
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.EXPIRED)

    def test_owner_can_cancel_only_a_pending_invitation(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        invitation = cancel_invitation(actor=self.owner, invitation=dispatch.invitation)
        self.assertEqual(invitation.status, ProjectInvitation.Status.CANCELLED)
        self.assertTrue(
            ActivityEvent.objects.filter(
                project=self.project,
                event_type=ActivityEvent.Type.INVITATION_CANCELLED,
                target_id=invitation.id,
            ).exists()
        )
        with self.assertRaises(InvitationUnavailable):
            cancel_invitation(actor=self.owner, invitation=invitation)

    def test_acceptance_rolls_back_if_event_recording_fails(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        with patch("projects.services.record_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                accept_invitation(actor=self.invitee, raw_token=dispatch.token)
        dispatch.invitation.refresh_from_db()
        self.assertEqual(dispatch.invitation.status, ProjectInvitation.Status.PENDING)
        self.assertFalse(
            ProjectMembership.objects.filter(project=self.project, user=self.invitee).exists()
        )

    def test_removed_user_can_rejoin_without_duplicate_membership(self):
        original = self.add_member(self.invitee)
        remove_member(actor=self.owner, project=self.project, member=self.invitee)
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        reactivated = accept_invitation(actor=self.invitee, raw_token=dispatch.token)
        self.assertEqual(reactivated.id, original.id)
        self.assertTrue(reactivated.is_active)
        self.assertEqual(
            ProjectMembership.objects.filter(project=self.project, user=self.invitee).count(),
            1,
        )

    def test_owner_can_change_member_and_facilitator_roles(self):
        membership = self.add_member(self.invitee)
        changed = change_member_role(
            actor=self.owner,
            project=self.project,
            member=self.invitee,
            role=ProjectMembership.Role.FACILITATOR,
        )
        self.assertEqual(changed.id, membership.id)
        self.assertEqual(changed.role, ProjectMembership.Role.FACILITATOR)
        with self.assertRaises(InvalidRole):
            change_member_role(
                actor=self.owner,
                project=self.project,
                member=self.invitee,
                role=ProjectMembership.Role.OWNER,
            )

    def test_role_change_noop_has_no_extra_event_and_missing_member_is_rejected(self):
        membership = self.add_member(self.invitee)
        before = ActivityEvent.objects.count()
        unchanged = change_member_role(
            actor=self.owner,
            project=self.project,
            member=self.invitee,
            role=ProjectMembership.Role.MEMBER,
        )
        self.assertEqual(unchanged.id, membership.id)
        self.assertEqual(ActivityEvent.objects.count(), before)
        with self.assertRaises(MembershipNotFound):
            change_member_role(
                actor=self.owner,
                project=self.project,
                member=self.other,
                role=ProjectMembership.Role.FACILITATOR,
            )

    def test_removing_missing_member_is_rejected(self):
        with self.assertRaises(MembershipNotFound):
            remove_member(actor=self.owner, project=self.project, member=self.other)

    def test_sole_owner_cannot_be_demoted_or_removed(self):
        with self.assertRaises(SoleOwnerViolation):
            change_member_role(
                actor=self.owner,
                project=self.project,
                member=self.owner,
                role=ProjectMembership.Role.MEMBER,
            )
        with self.assertRaises(SoleOwnerViolation):
            remove_member(actor=self.owner, project=self.project, member=self.owner)

    def test_removal_revokes_access_immediately(self):
        self.add_member(self.invitee)
        task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Reassign after removal",
        )
        TaskAssignment.objects.create(
            task=task,
            user=self.invitee,
            assigned_by=self.owner,
        )
        remove_member(actor=self.owner, project=self.project, member=self.invitee)
        self.assertFalse(is_project_member(self.invitee, self.project))
        self.assertFalse(TaskAssignment.objects.filter(task=task, user=self.invitee).exists())
        event = ActivityEvent.objects.get(
            project=self.project,
            event_type=ActivityEvent.Type.MEMBER_REMOVED,
        )
        self.assertEqual(event.metadata["removed_assignment_count"], 1)
        with self.assertRaises(PermissionDenied):
            memberships_for_project(user=self.invitee, project=self.project).count()

    def test_removal_rolls_back_membership_and_assignments_if_event_recording_fails(self):
        membership = self.add_member(self.invitee)
        task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Keep assignment when removal fails",
        )
        assignment = TaskAssignment.objects.create(
            task=task,
            user=self.invitee,
            assigned_by=self.owner,
        )

        with patch("projects.services.record_event", side_effect=RuntimeError("event failed")):
            with self.assertRaises(RuntimeError):
                remove_member(actor=self.owner, project=self.project, member=self.invitee)

        membership.refresh_from_db()
        self.assertIsNone(membership.removed_at)
        self.assertTrue(TaskAssignment.objects.filter(pk=assignment.pk).exists())

    def test_removal_clears_assignments_only_in_the_removed_project(self):
        self.add_member(self.invitee)
        other_project = Project.objects.create(name="Other assignment project", created_by=self.owner)
        ProjectMembership.objects.create(
            project=other_project,
            user=self.owner,
            role=ProjectMembership.Role.OWNER,
        )
        ProjectMembership.objects.create(project=other_project, user=self.invitee)
        removed_task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Remove this assignment",
        )
        retained_task = Task.objects.create(
            project=other_project,
            created_by=self.owner,
            title="Retain this assignment",
        )
        removed_assignment = TaskAssignment.objects.create(
            task=removed_task,
            user=self.invitee,
            assigned_by=self.owner,
        )
        retained_assignment = TaskAssignment.objects.create(
            task=retained_task,
            user=self.invitee,
            assigned_by=self.owner,
        )

        remove_member(actor=self.owner, project=self.project, member=self.invitee)

        self.assertFalse(TaskAssignment.objects.filter(pk=removed_assignment.pk).exists())
        self.assertTrue(TaskAssignment.objects.filter(pk=retained_assignment.pk).exists())
        event = ActivityEvent.objects.get(
            project=self.project,
            event_type=ActivityEvent.Type.MEMBER_REMOVED,
        )
        self.assertEqual(event.metadata["removed_assignment_count"], 1)

    def test_transfer_ownership_is_atomic_and_preserves_one_owner(self):
        self.add_member(self.invitee, ProjectMembership.Role.FACILITATOR)
        previous, incoming = transfer_ownership(
            actor=self.owner,
            project=self.project,
            new_owner=self.invitee,
        )
        self.assertEqual(previous.role, ProjectMembership.Role.FACILITATOR)
        self.assertEqual(incoming.role, ProjectMembership.Role.OWNER)
        self.assertEqual(
            ProjectMembership.objects.owners().filter(project=self.project).count(),
            1,
        )
        self.assertFalse(is_project_owner(self.owner, self.project))
        self.assertTrue(is_project_owner(self.invitee, self.project))
        with self.assertRaises(PermissionDenied):
            invite_member(
                actor=self.owner,
                project=self.project,
                invited_email=self.other.email,
            )

    def test_transfer_requires_active_member_in_same_project(self):
        other_project = create_project(actor=self.other, name="Other project")
        self.assertTrue(is_project_owner(self.other, other_project))
        with self.assertRaises(MembershipNotFound):
            transfer_ownership(
                actor=self.owner,
                project=self.project,
                new_owner=self.other,
            )

    def test_transfer_rejects_current_owner_and_invalid_demoted_role(self):
        with self.assertRaises(SoleOwnerViolation):
            transfer_ownership(
                actor=self.owner,
                project=self.project,
                new_owner=self.owner,
            )
        self.add_member(self.invitee)
        with self.assertRaises(InvalidRole):
            transfer_ownership(
                actor=self.owner,
                project=self.project,
                new_owner=self.invitee,
                previous_owner_role=ProjectMembership.Role.OWNER,
            )

    def test_selectors_do_not_leak_cross_project_data(self):
        other_project = create_project(actor=self.other, name="Other project")
        self.assertEqual(list(projects_for_user(self.owner)), [self.project])
        self.assertEqual(list(projects_for_user(self.other)), [other_project])
        with self.assertRaises(Project.DoesNotExist):
            project_for_user(user=self.outsider, project_id=self.project.id)

    def test_pending_invitation_selector_matches_only_recipient(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.invitee.email,
        )
        self.assertEqual(list(pending_invitations_for_user(self.invitee)), [dispatch.invitation])
        self.assertEqual(list(pending_invitations_for_user(self.other)), [])
        self.assertEqual(list(pending_invitations_for_user(AnonymousUser())), [])
        self.assertEqual(invitation_for_token(dispatch.token), dispatch.invitation)

    def test_selector_options_include_archived_and_removed_only_when_requested(self):
        membership = self.add_member(self.invitee)
        membership.removed_at = timezone.now()
        membership.save(update_fields=("removed_at",))
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=("archived_at", "updated_at"))
        self.assertEqual(list(projects_for_user(self.owner)), [])
        self.assertEqual(
            list(projects_for_user(self.owner, include_archived=True)),
            [self.project],
        )
        visible = memberships_for_project(
            user=self.owner,
            project=self.project,
            include_removed=True,
        )
        self.assertIn(membership, visible)
