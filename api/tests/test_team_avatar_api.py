"""Team avatars share profile images without broadening member access or query cost."""

from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from PIL import Image

from accounts.models import Profile, User
from api.serializers import MembershipSerializer, UserSummarySerializer
from api.tests.base import APIDomainTestCase
from projects.models import ProjectMembership


def avatar_upload(colour="#3157d5"):
    output = BytesIO()
    Image.new("RGB", (32, 32), colour).save(output, format="PNG")
    return SimpleUploadedFile("team-avatar.png", output.getvalue(), content_type="image/png")


class TeamAvatarAPITests(APIDomainTestCase):
    def roster(self):
        response = self.client.get("/api/v1/memberships/", {"project": str(self.project.pk)})
        self.assertEqual(response.status_code, 200, response.content)
        return {item["user"]["id"]: item["user"] for item in response.json()["results"]}

    def upload_avatar(self, colour="#3157d5"):
        response = self.client.post(
            "/api/v1/profile/avatar/", {"avatar": avatar_upload(colour)}, format="multipart"
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_uploaded_profile_image_is_exposed_in_teammate_roster(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.authenticate(self.owner)
            profile = self.upload_avatar()
            self.authenticate(self.member)
            team_member = self.roster()[str(self.owner.pk)]
            self.assertEqual(team_member["avatar_image_url"], profile["avatar_image_url"])
            self.assertEqual(team_member["avatar_version"], profile["updated_at"])
            self.assertEqual(team_member["avatar_url"], "")
            self.assertEqual(team_member["display_name"], "API Owner")
            self.assertEqual(
                set(team_member), {"id", "display_name", "avatar_image_url", "avatar_url", "avatar_version"}
            )
            self.assertNotIn("avatars/", team_member["avatar_image_url"])

    def test_replacement_changes_version_without_changing_private_endpoint(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.authenticate(self.owner)
            first_time = timezone.now() + timedelta(seconds=1)
            with patch("django.utils.timezone.now", return_value=first_time):
                first_profile = self.upload_avatar()
            first = self.roster()[str(self.owner.pk)]
            with patch("django.utils.timezone.now", return_value=first_time + timedelta(seconds=1)):
                second_profile = self.upload_avatar("#83d7c0")
            second = self.roster()[str(self.owner.pk)]
            self.assertEqual(first["avatar_image_url"], second["avatar_image_url"])
            self.assertEqual(first["avatar_version"], first_profile["updated_at"])
            self.assertEqual(second["avatar_version"], second_profile["updated_at"])
            self.assertGreater(parse_datetime(second["avatar_version"]), parse_datetime(first["avatar_version"]))

    def test_missing_avatar_returns_empty_sources_and_valid_version(self):
        self.authenticate(self.member)
        team_member = self.roster()[str(self.owner.pk)]
        self.assertEqual(team_member["avatar_image_url"], "")
        self.assertEqual(team_member["avatar_url"], "")
        self.assertIsNotNone(parse_datetime(team_member["avatar_version"]))

    def test_legacy_image_url_is_available_as_fallback(self):
        legacy_url = "https://images.example.com/profile.png"
        Profile.objects.filter(user=self.owner).update(avatar_url=legacy_url)
        self.authenticate(self.member)
        team_member = self.roster()[str(self.owner.pk)]
        self.assertEqual(team_member["avatar_image_url"], "")
        self.assertEqual(team_member["avatar_url"], legacy_url)

    def test_team_image_remains_private_to_active_project_members(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.authenticate(self.owner)
            self.upload_avatar()
            self.authenticate(self.member)
            avatar_url = self.roster()[str(self.owner.pk)]["avatar_image_url"]
            teammate_image = self.client.get(avatar_url)
            self.assertEqual(teammate_image.status_code, 200)
            self.assertEqual(teammate_image["Cache-Control"], "private, no-store")
            teammate_image.close()
            self.authenticate(self.outsider)
            self.assertEqual(self.client.get(avatar_url).status_code, 403)
            self.assertEqual(
                self.client.get("/api/v1/memberships/", {"project": str(self.project.pk)}).status_code, 403
            )
            ProjectMembership.objects.filter(project=self.project, user=self.member).update(
                removed_at=timezone.now()
            )
            self.authenticate(self.member)
            self.assertEqual(self.client.get(avatar_url).status_code, 403)

    def test_team_serializer_is_one_query_for_small_and_larger_rosters(self):
        for number in range(5):
            user = User.objects.create_user(
                email=f"team-member-{number}@example.com", password=self.password, display_name=f"Member {number}"
            )
            ProjectMembership.objects.create(project=self.project, user=user)
        for size in (1, 7):
            queryset = ProjectMembership.objects.filter(project=self.project).select_related(
                "user", "user__profile"
            ).order_by("id")[:size]
            with self.subTest(size=size), self.assertNumQueries(1):
                members = MembershipSerializer(queryset, many=True).data
            self.assertEqual(len(members), size)
            self.assertTrue(all("avatar_version" in member["user"] for member in members))

    def test_role_update_preserves_team_avatar_contract(self):
        membership = ProjectMembership.objects.get(project=self.project, user=self.member)
        self.authenticate(self.owner)
        response = self.client.patch(
            f"/api/v1/memberships/{membership.pk}/", {"role": "facilitator"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["role"], "facilitator")
        self.assertEqual(response.json()["user"]["avatar_image_url"], "")
        self.assertIn("avatar_version", response.json()["user"])
        rejected = self.client.patch(
            f"/api/v1/memberships/{membership.pk}/",
            {"role": "member", "user": {"avatar_url": "https://images.example.com/other.png"}},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)

    def test_general_user_summary_contract_is_unchanged(self):
        self.assertEqual(set(UserSummarySerializer(self.owner).data), {"id", "display_name"})
