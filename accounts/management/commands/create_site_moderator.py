"""Create a least-privilege site moderator without exposing a password in history."""

from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "Create a non-superuser site moderator; the password is read from a hidden prompt."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Moderator email (not secret).")
        parser.add_argument("--display-name", help="Moderator display name (not secret).")

    def handle(self, *args, **options):
        User = get_user_model()
        email = (options.get("email") or input("Email: ")).strip().lower()
        display_name = (options.get("display_name") or input("Display name: ")).strip()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Enter a valid email address.") from exc
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("An account with that email already exists.")
        if not 2 <= len(display_name) <= 80:
            raise CommandError("Display name must contain between 2 and 80 characters.")

        password = getpass("Password: ")
        confirmation = getpass("Password (again): ")
        if password != confirmation:
            raise CommandError("Passwords do not match.")
        candidate = User(email=email)
        try:
            validate_password(password, user=candidate)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        permissions = Permission.objects.filter(
            content_type__app_label__in=("accounts", "tasks"),
            codename__in=("manage_user_status", "moderate_reports"),
        )
        if permissions.count() != 2:
            raise CommandError("Moderator permissions are unavailable; run migrations first.")
        group, _ = Group.objects.get_or_create(name="Site moderators")
        group.permissions.set(permissions)
        user = User.objects.create_user(
            email=email,
            password=password,
            display_name=display_name,
            is_staff=True,
        )
        user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"Created site moderator {user.email}."))
