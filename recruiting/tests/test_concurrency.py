from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time
from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections, connections
from django.test import TransactionTestCase
from django.utils import timezone
from accounts.models import User
from projects.models import ProjectMembership
from projects.services import create_project
from recruiting import services
from recruiting.models import Application


class RecruitmentConcurrencyTests(TransactionTestCase):
    def test_two_simultaneous_approvals_cannot_overfill_one_place(self):
        owner = User.objects.create_user(email="owner-concurrent@example.com", password="Example!Password42", display_name="Owner")
        applicants = [User.objects.create_user(email=f"applicant-{n}@example.com", password="Example!Password42", display_name=f"Applicant {n}") for n in range(2)]
        project = create_project(actor=owner, name="Concurrent admissions")
        card = services.publish(actor=owner, data={"project": project.pk, "title": "One place", "university": "Example University", "course": "CS101", "term": "Term 1", "description": "One remaining role", "capacity": 1, "expires_at": timezone.now() + timedelta(days=5), "publish_consent": True})
        applications = [services.apply(actor=user, listing_id=card.pk, message="Please consider me") for user in applicants]
        barrier = threading.Barrier(2)

        def approve(application_id):
            close_old_connections(); barrier.wait()
            try:
                for attempt in range(50):
                    try:
                        actor = User.objects.get(pk=owner.pk)
                        services.decide(actor=actor, application_id=application_id, decision="approve")
                        return "approved"
                    except ValidationError:
                        return "full"
                    except OperationalError:
                        # Shared in-memory SQLite reports a table lock immediately;
                        # retry the whole transaction rather than a partial write.
                        close_old_connections(); time.sleep(0.02)
                raise AssertionError("Admission lock did not become available")
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(approve, [row.pk for row in applications]))
        self.assertCountEqual(outcomes, ["approved", "full"])
        self.assertEqual(Application.objects.filter(recruitment=card, status="approved").count(), 1)
        self.assertEqual(ProjectMembership.objects.active().filter(project=project).count(), 2)

