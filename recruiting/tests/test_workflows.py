from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.utils import timezone
from rest_framework.test import APIClient

from api.tests.base import APIDomainTestCase
from accounts.models import User
from activity.models import ActivityEvent
from operations.models import OperationAudit, UserBlock
from projects.models import ProjectMembership
from projects.services import create_project
from recruiting import readiness, selectors, services
from recruiting.models import Application, Bookmark, Recruitment, RecruitmentReport


class RecruitmentTests(APIDomainTestCase):
    def data(self, **changes):
        return {"project": self.project.pk, "title": "Join our software team", "university": "Example University", "course": "COMP1001",
                "term": "2026 Semester 2", "description": "Looking for someone who enjoys careful testing.", "skills": ["Python", "Testing"],
                "languages": ["English"], "cooperation": "hybrid", "capacity": 2, "expires_at": timezone.now() + timedelta(days=30),
                "publish_consent": True, **changes}

    def card(self, **changes):
        return services.publish(actor=self.owner, data=self.data(**changes))

    def apply(self, card, actor=None):
        return services.apply(actor=actor or self.outsider, listing_id=card.pk, message="I can help with automated tests.")

    def fourth_user(self):
        return User.objects.create_user(email="fourth@example.com", password=self.password, display_name="Fourth Student")

    def moderator(self):
        user = self.fourth_user(); user.is_staff = True; user.save()
        user.user_permissions.add(*Permission.objects.filter(codename__in=["moderate_reports", "manage_user_status"]))
        return user

    def test_consent_is_required_and_no_implicit_profile_publishing(self):
        with self.assertRaises(ValidationError): services.publish(actor=self.owner, data=self.data(publish_consent=False))
        self.assertFalse(Recruitment.objects.exists())
        card = self.card(); self.assertIsNotNone(card.consent_at)
        self.owner.profile.biography = "This private biography must remain private"; self.owner.profile.save()
        text = str(selectors.detail(user=self.outsider, listing_id=card.pk))
        self.assertNotIn(self.owner.profile.biography, text)

    def test_private_project_content_and_email_never_appear_in_discovery(self):
        self.project.name = "Secret project name"; self.project.description = "Private internal details"; self.project.save()
        card = self.card()
        row = selectors.detail(user=self.outsider, listing_id=card.pk)
        self.assertEqual(row["owner"], {"id": self.owner.pk, "display_name": self.owner.profile.display_name})
        self.assertEqual(row["student_status"], "self_reported")
        for secret in [str(self.project.pk), self.project.name, self.project.description, self.owner.email, self.member.email]:
            self.assertNotIn(secret, str(row))
        self.assertNotIn("project", row)
        self.assertEqual(selectors.detail(user=self.owner, listing_id=card.pk)["project"], self.project.pk)

    def test_only_current_project_managers_can_publish(self):
        for user in [self.member, self.outsider]:
            with self.assertRaises(PermissionDenied): services.publish(actor=user, data=self.data())
        membership = ProjectMembership.objects.get(project=self.project, user=self.member)
        membership.role = "facilitator"; membership.save()
        card = services.publish(actor=self.member, data=self.data())
        self.assertEqual(card.owner_id, self.member.pk)

    def test_archived_project_cannot_publish(self):
        self.project.archived_at = timezone.now(); self.project.save()
        with self.assertRaises(ValidationError): self.card()

    def test_expiry_and_capacity_bounds(self):
        for changes in [{"expires_at": timezone.now() - timedelta(seconds=1)}, {"expires_at": timezone.now() + timedelta(days=91)}, {"capacity": 0}, {"capacity": 21}, {"capacity": True}]:
            with self.assertRaises(ValidationError): self.card(**changes)
        self.assertEqual(Recruitment.objects.count(), 0)

    def test_tag_validation_and_casefold_deduplication(self):
        card = self.card(skills=["Python", "python", " Testing "])
        self.assertEqual(card.skills, ["Python", "Testing"])
        with self.assertRaises(ValidationError): services.edit(actor=self.owner, listing_id=card.pk, data={"skills": ["x"] * 11, "expected_updated_at": card.updated_at})

    def test_duplicate_open_project_card_prevented_and_expired_card_can_be_replaced(self):
        card = self.card()
        with self.assertRaises(ValidationError): self.card()
        Recruitment.objects.filter(pk=card.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        newer = self.card()
        card.refresh_from_db(); self.assertEqual(card.status, "closed"); self.assertNotEqual(newer.pk, card.pk)

    def test_five_open_card_quota_is_enforced(self):
        self.card()
        for number in range(4):
            project = create_project(actor=self.owner, name=f"Recruitment project {number}")
            services.publish(actor=self.owner, data=self.data(project=project.pk))
        project = create_project(actor=self.owner, name="Sixth recruitment project")
        with self.assertRaises(ValidationError): services.publish(actor=self.owner, data=self.data(project=project.pk))

    def test_filtering_bookmarks_and_pagination(self):
        card = self.card()
        for query in [{"q": "software"}, {"university": "Example", "course": "comp1001", "skill": "python", "cooperation": "hybrid"}]:
            self.assertEqual(selectors.listings(user=self.outsider, params=query)["count"], 1)
        self.assertEqual(selectors.listings(user=self.outsider, params={"q": "nonexistent"})["count"], 0)
        services.bookmark(actor=self.outsider, listing_id=card.pk)
        services.bookmark(actor=self.outsider, listing_id=card.pk)
        self.assertEqual(Bookmark.objects.count(), 1)
        self.assertTrue(selectors.listings(user=self.outsider, params={"saved": "true"})["results"][0]["bookmarked"])
        services.bookmark(actor=self.outsider, listing_id=card.pk, save=False)
        self.assertEqual(selectors.listings(user=self.outsider, params={"saved": "true"})["count"], 0)
        for page in ["invalid", "0", "-1"]:
            with self.assertRaises(ValidationError): selectors.listings(user=self.outsider, params={"page": page})

    def test_unicode_skills_are_searchable_without_json_encoding_assumptions(self):
        self.card(skills=["中文写作", "Straße", "Django"])
        for skill in ["中文", "STRASSE", "django"]:
            self.assertEqual(selectors.listings(user=self.outsider, params={"skill": skill})["count"], 1)

    def test_api_optional_skill_language_and_style_fields_have_safe_defaults(self):
        self.authenticate(self.owner)
        payload = self.data(); payload.pop("skills"); payload.pop("languages"); payload.pop("cooperation")
        payload["project"] = str(self.project.pk); payload["expires_at"] = payload["expires_at"].isoformat()
        response = self.client.post("/api/v1/recruiting/listings/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["skills"], []); self.assertEqual(response.data["languages"], [])
        self.assertEqual(response.data["cooperation"], "hybrid")

    def test_apply_has_no_private_access_until_approval(self):
        card = self.card(); application = self.apply(card)
        self.assertEqual(application.status, "pending")
        self.assertFalse(ProjectMembership.objects.active().filter(project=self.project, user=self.outsider).exists())
        row = selectors.application_row(application, self.outsider)
        self.assertNotIn("joined_project", row)
        self.assertNotIn(self.owner.email, str(row))
        with self.assertRaises(ValidationError): self.apply(card)

    def test_owner_and_existing_member_cannot_apply(self):
        card = self.card()
        for user in [self.owner, self.member]:
            with self.assertRaises(ValidationError): self.apply(card, user)

    def test_only_publisher_can_read_and_decide_applications(self):
        card = self.card(); application = self.apply(card)
        for user in [self.member, self.outsider]:
            with self.assertRaises(Http404): selectors.applications(user=user, listing_id=card.pk)
            with self.assertRaises(Http404): services.decide(actor=user, application_id=application.pk, decision="approve")
        rows = selectors.applications(user=self.owner, listing_id=card.pk)
        self.assertEqual(rows["count"], 1)
        self.assertNotIn(self.outsider.email, str(rows))

    def test_approve_adds_one_member_and_is_idempotent(self):
        card = self.card(); application = self.apply(card)
        for _ in range(2): services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        self.assertEqual(ProjectMembership.objects.active().filter(project=self.project, user=self.outsider).count(), 1)
        self.assertEqual(ActivityEvent.objects.filter(project=self.project, event_type="member_joined").count(), 1)
        application.refresh_from_db()
        self.assertEqual(selectors.application_row(application, self.outsider)["joined_project"], self.project.pk)
        self.assertEqual(selectors.detail(user=self.outsider, listing_id=card.pk)["joined_project"], self.project.pk)

    def test_removed_member_can_be_readmitted_with_member_role(self):
        membership = ProjectMembership.objects.get(project=self.project, user=self.member)
        membership.removed_at = timezone.now(); membership.role = "facilitator"; membership.save()
        card = self.card(); application = self.apply(card, self.member)
        services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        membership.refresh_from_db(); self.assertIsNone(membership.removed_at); self.assertEqual(membership.role, "member")

    def test_capacity_prevents_second_admission(self):
        card = self.card(capacity=1); first = self.apply(card); second_user = self.fourth_user(); second = self.apply(card, second_user)
        services.decide(actor=self.owner, application_id=first.pk, decision="approve")
        with self.assertRaises(ValidationError): services.decide(actor=self.owner, application_id=second.pk, decision="approve")
        second.refresh_from_db(); self.assertEqual(second.status, "pending")
        self.assertFalse(ProjectMembership.objects.active().filter(project=self.project, user=second_user).exists())

    def test_existing_member_duplicate_admission_is_rejected_without_consuming_capacity(self):
        card = self.card(); application = self.apply(card)
        ProjectMembership.objects.create(project=self.project, user=self.outsider)
        with self.assertRaises(ValidationError): services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        application.refresh_from_db(); self.assertEqual(application.status, "pending")

    def test_rejection_and_withdrawal_are_terminal(self):
        card = self.card(); application = self.apply(card)
        services.decide(actor=self.owner, application_id=application.pk, decision="reject", reason="We need another skill")
        with self.assertRaises(ValidationError): services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        with self.assertRaises(ValidationError): services.withdraw(actor=self.outsider, application_id=application.pk)
        self.assertFalse(ProjectMembership.objects.active().filter(project=self.project, user=self.outsider).exists())

    def test_withdraw_own_only_and_still_works_after_expiry_and_block(self):
        card = self.card(); application = self.apply(card)
        with self.assertRaises(Http404): services.withdraw(actor=self.member, application_id=application.pk)
        Recruitment.objects.filter(pk=card.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        UserBlock.objects.create(user=self.owner, blocked=self.outsider)
        services.withdraw(actor=self.outsider, application_id=application.pk)
        services.withdraw(actor=self.outsider, application_id=application.pk)
        application.refresh_from_db(); self.assertEqual(application.status, "withdrawn")

    def test_expired_closed_and_archived_cards_cannot_admit(self):
        card = self.card(); application = self.apply(card)
        services.change_state(actor=self.owner, listing_id=card.pk)
        with self.assertRaises(ValidationError): services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        services.change_state(actor=self.owner, listing_id=card.pk, reopen=True)
        self.project.archived_at = timezone.now(); self.project.save()
        self.assertEqual(selectors.listings(user=self.outsider, params={})["count"], 0)
        with self.assertRaises(ValidationError): services.decide(actor=self.owner, application_id=application.pk, decision="approve")

    def test_publisher_lost_manager_role_card_is_unavailable(self):
        membership = ProjectMembership.objects.get(project=self.project, user=self.member); membership.role = "facilitator"; membership.save()
        card = services.publish(actor=self.member, data=self.data()); application = self.apply(card)
        membership.role = "member"; membership.save()
        self.assertEqual(selectors.listings(user=self.outsider, params={})["count"], 0)
        with self.assertRaises(PermissionDenied): services.decide(actor=self.member, application_id=application.pk, decision="approve")
        self.assertEqual(selectors.detail(user=self.member, listing_id=card.pk)["status"], "unavailable")
        services.change_state(actor=self.member, listing_id=card.pk)

    def test_blocks_work_in_both_directions_and_hide_applicants(self):
        card = self.card(); application = self.apply(card)
        UserBlock.objects.create(user=self.outsider, blocked=self.owner)
        self.assertEqual(selectors.listings(user=self.outsider, params={})["count"], 0)
        with self.assertRaises(Http404): selectors.detail(user=self.outsider, listing_id=card.pk)
        with self.assertRaises(Http404): self.apply(card)
        self.assertEqual(selectors.applications(user=self.owner, listing_id=card.pk)["count"], 0)
        with self.assertRaises(PermissionDenied): services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        self.assertIsNone(selectors.overview(user=self.outsider, params={})["applications"][0]["listing"])

    def test_unverified_inactive_or_closed_applicant_cannot_be_admitted(self):
        card = self.card(); application = self.apply(card)
        for changes in [{"email_verified_at": None}, {"is_active": False}, {"closed_at": timezone.now()}]:
            User.objects.filter(pk=self.outsider.pk).update(**changes)
            with self.assertRaises(PermissionDenied): services.decide(actor=self.owner, application_id=application.pk, decision="approve")
            User.objects.filter(pk=self.outsider.pk).update(is_active=True, email_verified_at=timezone.now(), closed_at=None)

    def test_inactive_unverified_publisher_is_not_discoverable(self):
        card = self.card()
        User.objects.filter(pk=self.owner.pk).update(email_verified_at=None)
        self.assertEqual(selectors.listings(user=self.outsider, params={})["count"], 0)
        with self.assertRaises(Http404): selectors.detail(user=self.outsider, listing_id=card.pk)

    def test_edit_requires_current_timestamp_and_cannot_change_project(self):
        card = self.card()
        with self.assertRaises(ValidationError): services.edit(actor=self.owner, listing_id=card.pk, data={"title": "New opening"})
        original = card.updated_at
        services.edit(actor=self.owner, listing_id=card.pk, data={"title": "New opening", "expected_updated_at": original})
        with self.assertRaises(ValidationError): services.edit(actor=self.owner, listing_id=card.pk, data={"title": "Lost update", "expected_updated_at": original})
        card.refresh_from_db()
        with self.assertRaises(ValidationError): services.edit(actor=self.owner, listing_id=card.pk, data={"project": self.project.pk, "expected_updated_at": card.updated_at})
        self.assertEqual(card.title, "New opening")

    def test_capacity_cannot_shrink_below_accepted_count_and_full_card_cannot_reopen(self):
        card = self.card(capacity=1); application = self.apply(card)
        services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        services.change_state(actor=self.owner, listing_id=card.pk)
        with self.assertRaises(ValidationError): services.change_state(actor=self.owner, listing_id=card.pk, reopen=True)
        card.refresh_from_db()
        with self.assertRaises(ValidationError): services.edit(actor=self.owner, listing_id=card.pk, data={"capacity": 0, "expected_updated_at": card.updated_at})

    def test_capacity_cannot_shrink_from_two_accepted_to_one(self):
        card = self.card(capacity=2)
        for user in [self.outsider, self.fourth_user()]:
            application = self.apply(card, user)
            services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        with self.assertRaises(ValidationError): services.edit(actor=self.owner, listing_id=card.pk, data={"capacity": 1, "expected_updated_at": card.updated_at})

    def test_reject_pending_application_after_owner_closed_recruitment(self):
        card = self.card(); application = self.apply(card)
        services.change_state(actor=self.owner, listing_id=card.pk)
        services.decide(actor=self.owner, application_id=application.pk, decision="reject", reason="Recruiting ended")
        application.refresh_from_db(); self.assertEqual(application.status, "rejected")

    def test_personal_history_pagination_does_not_expose_other_applicants(self):
        card = self.card()
        Application.objects.bulk_create([Application(recruitment=card, applicant=User.objects.create_user(email=f"candidate-{n}@example.com", password=self.password, display_name=f"Candidate {n}"), message="Applicant message") for n in range(23)])
        first = selectors.applications(user=self.owner, listing_id=card.pk)
        second = selectors.applications(user=self.owner, listing_id=card.pk, page=2)
        self.assertEqual(first["count"], 23); self.assertEqual(len(first["results"]), 20); self.assertEqual(len(second["results"]), 3)
        self.assertFalse(set(row["id"] for row in first["results"]) & set(row["id"] for row in second["results"]))

    def test_reports_are_idempotent_private_and_moderatable(self):
        card = self.card(); application = self.apply(card)
        report = services.report(actor=self.outsider, listing_id=card.pk, reason="misleading", details="This card impersonates official university verification.")
        self.assertEqual(services.report(actor=self.outsider, listing_id=card.pk, reason="spam", details="duplicate").pk, report.pk)
        with self.assertRaises(PermissionDenied): selectors.reports(user=self.owner)
        moderator = self.moderator()
        services.moderate(actor=moderator, report_id=report.pk, decision="hide", reason="Misleading identity claim confirmed")
        self.assertEqual(selectors.listings(user=self.outsider, params={})["count"], 0)
        application.refresh_from_db(); self.assertEqual(application.status, "cancelled")
        self.assertTrue(OperationAudit.objects.filter(action="recruitment_hide").exists())
        services.moderate(actor=moderator, report_id=report.pk, decision="restore", reason="Card information corrected")
        self.assertEqual(selectors.listings(user=self.outsider, params={})["count"], 1)

    def test_moderator_cannot_handle_own_report(self):
        card = self.card(); moderator = self.moderator()
        report = services.report(actor=moderator, listing_id=card.pk, reason="spam", details="Repeated posting")
        with self.assertRaises(PermissionDenied): services.moderate(actor=moderator, report_id=report.pk, decision="hide", reason="Cannot self review")

    def test_rate_limit_rejection_does_not_publish_or_admit(self):
        with patch("recruiting.services.consume_rate", return_value=False):
            with self.assertRaises(ValidationError): self.card()
        self.assertFalse(Recruitment.objects.exists())

    def test_account_export_contains_only_authored_content_and_closure_retires_market(self):
        card = self.card(); application = self.apply(card)
        services.bookmark(actor=self.outsider, listing_id=card.pk)
        owner_data = readiness.personal_data(self.owner)
        self.assertNotIn(application.message, str(owner_data))
        self.assertNotIn(self.outsider.email, str(owner_data))
        self.assertIn(application.message, str(readiness.personal_data(self.outsider)))
        readiness.close_account_records(self.owner, timezone.now())
        card.refresh_from_db(); application.refresh_from_db()
        self.assertEqual(card.status, "closed"); self.assertEqual(card.description, ""); self.assertEqual(application.status, "cancelled")
        readiness.close_account_records(self.outsider, timezone.now())
        application.refresh_from_db(); self.assertEqual(application.message, ""); self.assertFalse(Bookmark.objects.exists())

    def test_api_mfa_and_verified_email_required(self):
        self.assertEqual(self.client.get("/api/v1/recruiting/listings/").status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/v1/recruiting/listings/").status_code, 401)
        self.authenticate(self.owner)
        User.objects.filter(pk=self.owner.pk).update(email_verified_at=None)
        self.assertEqual(self.client.get("/api/v1/recruiting/listings/").status_code, 403)

    def test_api_end_to_end_publish_apply_approve_and_private_join(self):
        self.authenticate(self.owner)
        payload = self.data(); payload["project"] = str(self.project.pk); payload["expires_at"] = payload["expires_at"].isoformat()
        response = self.client.post("/api/v1/recruiting/listings/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data); card_id = response.data["id"]
        self.authenticate(self.outsider)
        response = self.client.post(f"/api/v1/recruiting/listings/{card_id}/apply/", {"message": "Happy to help"}, format="json")
        self.assertEqual(response.status_code, 201, response.data); app_id = response.data["id"]
        self.authenticate(self.owner)
        response = self.client.post(f"/api/v1/recruiting/applications/{app_id}/decision/", {"decision": "approve"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.authenticate(self.outsider)
        response = self.client.get("/api/v1/recruiting/overview/")
        self.assertEqual(str(response.data["applications"][0]["joined_project"]), str(self.project.pk))
        response = self.client.get(f"/api/v1/projects/{self.project.pk}/")
        self.assertEqual(response.status_code, 200)

    def test_api_csrf_is_enforced_for_browser_actions(self):
        client = APIClient(enforce_csrf_checks=True); self.authenticate(self.owner, client=client)
        response = client.post("/api/v1/recruiting/listings/", {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_removed_approved_user_no_longer_gets_private_project_link(self):
        card = self.card(); application = self.apply(card)
        services.decide(actor=self.owner, application_id=application.pk, decision="approve")
        ProjectMembership.objects.filter(project=self.project, user=self.outsider).update(removed_at=timezone.now())
        application.refresh_from_db()
        self.assertNotIn("joined_project", selectors.application_row(application, self.outsider))

