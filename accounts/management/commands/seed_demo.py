"""Create a realistic, repeatable local demonstration workspace."""

import secrets
import string
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from meetings.models import MeetingAttendance
from meetings.services import create_meeting, set_rsvp
from projects.models import Project, ProjectMembership
from projects.services import accept_invitation, change_member_role, create_project, invite_member
from tasks.models import Task
from tasks.services import create_comment, create_task, replace_assignees, transition_task


DEMO_USERS = (
    ("owner@studycrew.local", "Alex Morgan", "COMP3609"),
    ("facilitator@studycrew.local", "Sam Lee", "COMP3609"),
    ("member@studycrew.local", "Jordan Patel", "COMP3609"),
    ("researcher@studycrew.local", "Taylor Nguyen", "COMP3609"),
)


def strong_random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    characters = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
        *(secrets.choice(alphabet) for _ in range(length - 4)),
    ]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


class Command(BaseCommand):
    help = "Create idempotent local demo data and print any generated passwords once."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Generate new random passwords for existing demo accounts.",
        )

    def handle(self, *args, **options):
        credentials: list[tuple[str, str]] = []
        users: dict[str, User] = {}
        for email, display_name, course_code in DEMO_USERS:
            user = User.objects.filter(email=email).first()
            if user is None:
                password = strong_random_password()
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    display_name=display_name,
                )
                credentials.append((email, password))
            elif options["reset_passwords"]:
                password = strong_random_password()
                user.set_password(password)
                user.save(update_fields=["password", "updated_at"])
                credentials.append((email, password))
            profile = user.profile
            changed = False
            if profile.display_name != display_name:
                profile.display_name = display_name
                changed = True
            if profile.course_code != course_code:
                profile.course_code = course_code
                changed = True
            if changed:
                profile.save()
            users[email] = user

        owner = users[DEMO_USERS[0][0]]
        project = Project.objects.filter(created_by=owner, name="COMP3609 Group Project").first()
        if project is None:
            project = create_project(
                actor=owner,
                name="COMP3609 Group Project",
                description="Plan, implement, test and deploy the StudyCrew assessment project.",
                due_at=timezone.now() + timedelta(days=42),
            )

        for email, _display_name, _course_code in DEMO_USERS[1:]:
            user = users[email]
            membership = ProjectMembership.objects.filter(
                project=project, user=user, removed_at__isnull=True
            ).first()
            if membership is None:
                dispatch = invite_member(actor=owner, project=project, invited_email=email)
                membership = accept_invitation(actor=user, raw_token=dispatch.token)
            if email == "facilitator@studycrew.local" and membership.role != ProjectMembership.Role.FACILITATOR:
                change_member_role(
                    actor=owner,
                    project=project,
                    member=user,
                    role=ProjectMembership.Role.FACILITATOR,
                )

        task_specs = (
            ("Confirm API contract", "Document REST resources and error responses.", "high", "done", [owner, users[DEMO_USERS[1][0]]]),
            ("Build responsive workspace", "Connect the React workspace to the secured API.", "urgent", "in_progress", [owner, users[DEMO_USERS[2][0]]]),
            ("Prepare deployment evidence", "Capture HTTPS, service restart and load-test evidence.", "medium", "todo", [users[DEMO_USERS[1][0]]]),
            ("Review security checklist", "Validate every Assignment 3 security control on EC2.", "high", "blocked", [users[DEMO_USERS[3][0]]]),
        )
        created_tasks: list[Task] = []
        for index, (title, description, priority, status, assignees) in enumerate(task_specs):
            task = Task.objects.filter(project=project, title=title, archived_at__isnull=True).first()
            if task is None:
                task = create_task(
                    project=project,
                    actor=owner,
                    data={
                        "title": title,
                        "description": description,
                        "priority": priority,
                        "due_at": timezone.now() + timedelta(days=7 + index * 4),
                    },
                )
                replace_assignees(task=task, actor=owner, assignee_ids=[user.id for user in assignees])
                transition_task(
                    task=task,
                    actor=owner,
                    status=status,
                    blocker_note="Waiting for the AWS Learner Lab session" if status == "blocked" else "",
                )
            created_tasks.append(task)

        discussion_task = created_tasks[1]
        if not discussion_task.comments.exists():
            create_comment(
                task=discussion_task,
                actor=users[DEMO_USERS[2][0]],
                body="The mobile task board is ready for accessibility review.",
            )
            create_comment(
                task=discussion_task,
                actor=owner,
                body="Great — please verify keyboard focus and the 360 px layout next.",
            )

        meeting = project.meetings.filter(title="Weekly implementation check-in").first()
        if meeting is None:
            starts_at = timezone.now() + timedelta(days=3)
            meeting = create_meeting(
                actor=owner,
                project=project,
                title="Weekly implementation check-in",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                location="Library collaboration room",
                agenda="Review the task board, blockers and test evidence.",
            )
            for user in users.values():
                set_rsvp(
                    meeting=meeting,
                    actor=user,
                    response=(
                        MeetingAttendance.Response.ACCEPTED
                        if user != users[DEMO_USERS[3][0]]
                        else MeetingAttendance.Response.PENDING
                    ),
                    availability_note="",
                )

        self.stdout.write(self.style.SUCCESS("Demo workspace is ready."))
        if credentials:
            self.stdout.write("Generated credentials (shown once; keep them out of source control):")
            for email, password in credentials:
                self.stdout.write(f"  {email}  {password}")
        else:
            self.stdout.write(
                "Existing passwords were preserved. Use --reset-passwords to generate replacements."
            )
