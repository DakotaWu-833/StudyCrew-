from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from accounts.models import User
from api.tests.base import APIDomainTestCase
from campus.models import Course, ProjectCourse, Term
from operations.models import UserBlock
from projects.models import Project, ProjectMembership
from projects.services import create_project
from recruiting.models import Application, Recruitment
from recruiting.recommendations import recommendations


class RecommendationTests(APIDomainTestCase):
    def card(self, **changes):
        project = changes.pop("project", None) or create_project(actor=self.owner, name="Private recommendation project")
        now = timezone.now()
        return Recruitment.objects.create(owner=self.owner, project=project, title="Open study team", university="Example University",
            course=changes.pop("course", "COMP1001"), term="Semester 2", description="Public opening description",
            skills=changes.pop("skills", ["Python"]), languages=changes.pop("languages", ["English"]),
            cooperation=changes.pop("cooperation", "hybrid"), capacity=2, expires_at=now + timedelta(days=30),
            published_at=now, consent_at=now, **changes)

    def suggestions(self, user=None, **overrides):
        return recommendations(user=user or self.outsider, overrides=overrides)

    def profile(self, **changes):
        for field, value in changes.items():
            setattr(self.outsider.profile, field, value)
        self.outsider.profile.save()

    def test_matches_current_profile_with_exact_factual_reasons_and_no_scores(self):
        card = self.card()
        self.profile(course_code="COMP 1001", skills=["python"], communication_languages=["english"], collaboration_preference="online")
        page = self.suggestions()
        row = page["results"][0]
        self.assertEqual(row["id"], card.pk)
        self.assertEqual([reason["kind"] for reason in row["match_reasons"]], ["course", "skills", "languages", "cooperation"])
        self.assertIn("self-reported", row["match_reasons"][0]["text"])
        self.assertNotIn("score", row)
        self.assertNotIn("rank", row)

    def test_unicode_width_casefold_whole_tokens_and_chinese_match(self):
        self.card(skills=["Ｐｙｔｈｏｎ", "中文写作", "Straße"], languages=["中文"])
        self.profile(skills=["python", "中文写作", "STRASSE"], communication_languages=["中文"])
        self.assertEqual(self.suggestions()["results"][0]["match_reasons"][0]["values"], ["Ｐｙｔｈｏｎ", "中文写作", "Straße"])
        self.profile(skills=["Py", "写作"], communication_languages=[])
        self.assertEqual(self.suggestions()["count"], 0)

    def test_empty_optional_profile_explains_missing_fields_without_random_matches(self):
        self.card()
        page = self.suggestions()
        self.assertEqual(page["results"], [])
        self.assertEqual(page["preferences"]["missing_fields"], ["course", "skills", "languages", "working style"])
        self.assertEqual(page["eligible_count"], 1)

    def test_temporary_preferences_do_not_change_profile_and_override_one_field_only(self):
        self.card()
        self.profile(skills=["Writing"], communication_languages=["English"])
        result = self.suggestions(skill="Python")
        self.assertEqual(result["preferences"]["skills"], ["Python"])
        self.assertEqual(result["preferences"]["languages"], ["English"])
        self.outsider.profile.refresh_from_db()
        self.assertEqual(self.outsider.profile.skills, ["Writing"])

    def test_owned_course_requires_same_university_and_does_not_read_other_users_courses(self):
        self.card(course="数据科学")
        Course.objects.create(owner=self.outsider, university="Other University", code="数据科学", name="Private course title")
        Course.objects.create(owner=self.owner, university="Example University", code="数据科学", name="Publisher private course")
        self.assertEqual(self.suggestions()["count"], 0)
        Course.objects.create(owner=self.outsider, university="Example University", code="数据科学", name="Own course")
        result = self.suggestions()
        self.assertEqual(result["count"], 1)
        self.assertNotIn("Publisher private course", str(result))

    def test_active_project_course_links_are_used_but_removed_or_archived_links_are_not(self):
        course = Course.objects.create(owner=self.owner, university="Example University", code="COMP1001", name="Course")
        term = Term.objects.create(owner=self.owner, university="Example University", year=2026, name="Semester 2")
        ProjectCourse.objects.create(project=self.project, course=course, term=term)
        membership = ProjectMembership.objects.create(project=self.project, user=self.outsider)
        self.card()
        self.assertEqual(self.suggestions()["count"], 1)
        membership.removed_at = timezone.now(); membership.save()
        self.assertEqual(self.suggestions()["count"], 0)
        membership.removed_at = None; membership.save()
        term.archived_at = timezone.now(); term.save()
        self.assertEqual(self.suggestions()["count"], 0)

    def test_excludes_own_member_applied_and_capacity_full_cards(self):
        eligible = self.card()
        own = create_project(actor=self.outsider, name="Own private project")
        own_card = self.card(project=own); own_card.owner = self.outsider; own_card.save()
        member = self.card(project=self.project)
        ProjectMembership.objects.create(project=self.project, user=self.outsider)
        applied = self.card(); Application.objects.create(recruitment=applied, applicant=self.outsider, message="Old application", status="withdrawn")
        full = self.card()
        Application.objects.create(recruitment=full, applicant=self.member, message="Member", status="approved")
        full.capacity = 1; full.save()
        page = self.suggestions(skill="Python")
        self.assertEqual([row["id"] for row in page["results"]], [eligible.pk])
        self.assertEqual(page["eligible_count"], 1)
        self.assertNotIn(member.pk, [row["id"] for row in page["results"]])

    def test_expiry_hidden_closed_archived_and_current_manager_eligibility(self):
        eligible = self.card()
        for field, value in [("expires_at", timezone.now() - timedelta(seconds=1)), ("hidden_at", timezone.now()), ("status", "closed")]:
            card = self.card(); Recruitment.objects.filter(pk=card.pk).update(**{field: value})
        archived = self.card(); archived.project.archived_at = timezone.now(); archived.project.save()
        unmanaged = self.card(); ProjectMembership.objects.filter(project=unmanaged.project, user=self.owner).update(removed_at=timezone.now())
        self.assertEqual([row["id"] for row in self.suggestions(skill="Python")["results"]], [eligible.pk])

    def test_blocking_both_directions_and_suspended_publisher_remove_recommendations(self):
        self.card()
        for first, second in [(self.owner, self.outsider), (self.outsider, self.owner)]:
            block = UserBlock.objects.create(user=first, blocked=second)
            self.assertEqual(self.suggestions(skill="Python")["count"], 0)
            block.delete()
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(self.suggestions(skill="Python")["count"], 0)

    def test_private_project_profiles_emails_application_messages_are_not_in_response(self):
        card = self.card()
        self.owner.profile.biography = "Private profile biography"; self.owner.profile.skills = ["Secret skill"]; self.owner.profile.save()
        Application.objects.create(recruitment=card, applicant=self.member, message="Other applicant private message")
        result = str(self.suggestions(skill="Python"))
        for secret in [self.owner.email, self.member.email, self.project.name, str(card.project_id), "Private profile biography", "Secret skill", "Other applicant private message"]:
            self.assertNotIn(secret, result)
        self.assertNotIn("project", self.suggestions(skill="Python")["results"][0])

    def test_closed_current_user_and_updated_profile_override_stale_loaded_identity(self):
        self.card()
        self.profile(skills=["Writing"])
        User.objects.filter(pk=self.outsider.pk).update(closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): self.suggestions(skill="Python")
        User.objects.filter(pk=self.outsider.pk).update(closed_at=None)
        self.outsider.profile.__class__.objects.filter(pk=self.outsider.pk).update(skills=["Python"])
        self.assertEqual(self.suggestions()["count"], 1)

    def test_course_priority_and_recent_ties_are_deterministic_without_scoring(self):
        course = self.card(course="COMP1001", skills=[], languages=[])
        skill = self.card(course="OTHER", languages=[])
        recent_skill = self.card(course="OTHER", languages=[])
        self.profile(course_code="COMP1001", skills=["Python"])
        self.assertEqual([row["id"] for row in self.suggestions()["results"]], [course.pk, recent_skill.pk, skill.pk])

    def test_bound_candidate_window_is_reported_and_pagination_is_disjoint(self):
        for _ in range(23): self.card()
        with patch("recruiting.recommendations.CANDIDATE_WINDOW", 22):
            first = self.suggestions(skill="Python")
            second = recommendations(user=self.outsider, overrides={"skill": "Python"}, page=2)
        self.assertTrue(first["limited"])
        self.assertEqual(first["candidate_window"], 22)
        self.assertEqual(first["eligible_count"], 23)
        self.assertEqual(first["count"], 22)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(len(second["results"]), 2)
        self.assertFalse({row["id"] for row in first["results"]} & {row["id"] for row in second["results"]})
        for value in ["no", 0, -1]:
            with self.assertRaises(ValidationError): recommendations(user=self.outsider, overrides={}, page=value)

    def test_api_requires_mfa_validates_preferences_and_prevents_shared_caching(self):
        self.card()
        url = "/api/v1/recruiting/recommendations/"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.authenticate(self.outsider)
        response = self.client.get(url, {"skill": "Python"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        for params in [{"skill": "x" * 51}, {"course": "x" * 61}, {"cooperation": "wrong"}, {"page": "-2"}]:
            self.assertEqual(self.client.get(url, params).status_code, 400)
