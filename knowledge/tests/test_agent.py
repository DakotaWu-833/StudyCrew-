"""Project assistant tools, read-only drafts, evidence, and session boundaries."""

from datetime import timedelta
import json
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.tests.base import APIDomainTestCase
from coordination.models import MeetingRecord
from documents_store import services as file_services
from documents_store.models import ProjectDocument
from knowledge import agent, providers
from meetings.models import Meeting
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment


def tool_turn(name, arguments, call_id="call-1"):
    return {"content": "", "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}]}


def final_turn(content):
    return {"content": content, "tool_calls": []}


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    OPERATIONS_RATE_LIMITS=False,
    PROJECT_FILES_REQUIRE_SCAN=False,
    PROJECT_FILES_CLAMSCAN="",
    RAG_PROVIDER="disabled",
    RAG_MODEL="",
    RAG_API_KEY="",
)
class ProjectAssistantTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        setting = override_settings(MEDIA_ROOT=directory.name)
        setting.enable()
        self.addCleanup(setting.disable)

    def configured(self):
        return override_settings(RAG_PROVIDER="ollama", RAG_BASE_URL="http://127.0.0.1:11434", RAG_MODEL="test-model")

    def upload(self, text="Nebulawork report requires a security review.", *, project=None, document=None):
        return file_services.upload(
            actor=self.owner, project_id=(project or self.project).pk,
            document_id=document.pk if document else None,
            values={"expected_revision": document.revision} if document else {"title": "Report requirements"},
            upload=SimpleUploadedFile("requirements.txt", text.encode("utf-8"), content_type="text/plain"),
        )

    def record(self, minutes="Nebulawork meeting requires a security review.", *, project=None):
        now = timezone.now()
        meeting = Meeting.objects.create(
            project=project or self.project, organiser=self.owner, title="Report planning",
            starts_at=now - timedelta(hours=2), ends_at=now - timedelta(hours=1),
        )
        return MeetingRecord.objects.create(meeting=meeting, minutes=minutes, decisions="", version=1)

    def task(self, *, project=None, status="todo", **values):
        if status == "done":
            values.setdefault("completed_at", timezone.now())
        if status == "blocked":
            values.setdefault("blocker_note", "Awaiting security review")
        return Task.objects.create(
            project=project or self.project, created_by=self.owner,
            title=values.pop("title", "Review Nebulawork report"),
            description=values.pop("description", "Check the report requirements."),
            status=status, **values,
        )

    def assist(self, question="Help plan the Nebulawork security review", user=None):
        return agent.run(user or self.member, self.project.pk, question)

    def url(self):
        return f"/api/v1/knowledge/projects/{self.project.pk}/assistant/"

    def run_turns(self, turns):
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=turns) as chat:
            result = self.assist()
        return result, chat

    def snapshot(self):
        return list(Task.objects.order_by("id").values()), list(TaskAssignment.objects.order_by("id").values())

    def assert_private(self, result):
        payload = json.dumps(result, default=str)
        for forbidden in ("storage_key", "private-project-files", "_fingerprint", "server-secret"):
            self.assertNotIn(forbidden, payload)

    def test_complete_tool_loop_returns_evidence_and_drafts_without_creating_tasks(self):
        document = self.upload()
        task = self.task()
        before = self.snapshot()
        turns = [
            tool_turn("search_project_sources", {"query": "Nebulawork", "max_sources": 1}, "search-1"),
            tool_turn("list_project_tasks", {"status": "open"}, "tasks-1"),
            tool_turn("propose_tasks", {"tasks": [{"title": "Complete the security review", "description": "Review the report against its requirements.", "source_citations": ["S1", "S2"]}]}, "draft-1"),
            final_turn("Review the requirements [S1] and the current review task [S2]."),
        ]
        result, chat = self.run_turns(turns)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["answer"], turns[-1]["content"])
        self.assertEqual(chat.call_count, 4)
        self.assertEqual([step["tool"] for step in result["steps"]], ["search_project_sources", "list_project_tasks", "propose_tasks"])
        self.assertTrue(all(step["summary"] and step["result_count"] == 1 for step in result["steps"]))
        self.assertEqual(result["drafts"][0]["source_citations"], ["S1", "S2"])
        self.assertEqual([(source["kind"], source["source_id"]) for source in result["sources"]], [("file", str(document.pk)), ("task", str(task.pk))])
        self.assertEqual(self.snapshot(), before)
        self.assert_private(result)

    def test_meeting_tool_evidence_retains_record_version_and_citation(self):
        record = self.record()
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}),
            final_turn("The meeting calls for a security review [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sources"][0]["source_id"], str(record.pk))
        self.assertEqual(result["sources"][0]["kind"], "meeting")
        self.assertEqual(result["sources"][0]["version"], 1)

    def test_repeated_retrieval_reuses_citation_without_duplicate_source(self):
        self.upload()
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "call-1"),
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "call-2"),
            final_turn("The requirements call for a security review [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([source["citation"] for source in result["sources"]], ["S1"])

    def test_task_tool_excludes_other_projects_and_archived_tasks(self):
        other = Project.objects.create(name="Private project", created_by=self.owner)
        ProjectMembership.objects.create(project=other, user=self.owner, role="owner")
        self.task(project=other, title="Cross-project secret")
        self.task(title="Archived secret", archived_at=timezone.now())
        current = self.task()
        result, _ = self.run_turns([
            tool_turn("list_project_tasks", {"status": "all"}),
            final_turn("The current task requires a report review [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([source["source_id"] for source in result["sources"]], [str(current.pk)])
        self.assertIsNone(result["sources"][0]["version"])
        self.assertNotIn("secret", json.dumps(result))

    def test_task_tool_open_and_blocked_filters_are_real_database_filters(self):
        todo = self.task(title="Open report task")
        blocked = self.task(status="blocked", title="Blocked review task")
        self.task(status="done", title="Completed report task")
        for status, expected in (("open", {str(todo.pk), str(blocked.pk)}), ("blocked", {str(blocked.pk)})):
            with self.subTest(status=status):
                result, _ = self.run_turns([
                    tool_turn("list_project_tasks", {"status": status}),
                    final_turn("The listed task needs attention [S1]."),
                ])
                self.assertEqual(result["status"], "completed")
                self.assertEqual({source["source_id"] for source in result["sources"]}, expected)

    def test_document_tool_never_reads_other_project_content(self):
        other = Project.objects.create(name="Private project", created_by=self.owner)
        ProjectMembership.objects.create(project=other, user=self.owner, role="owner")
        self.upload("Nebulawork PRIVATE99999 revenue", project=other)
        current = self.upload()
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}),
            final_turn("A security review is required [S1]."),
        ])
        self.assertEqual(result["sources"][0]["source_id"], str(current.pk))
        self.assertNotIn("PRIVATE99999", json.dumps(result))

    def test_disabled_model_returns_explicit_unavailable_without_provider_call(self):
        with patch("knowledge.agent.providers.agent_chat") as chat:
            result = self.assist()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["drafts"], [])
        chat.assert_not_called()

    def test_provider_failure_has_safe_status_and_never_creates_tasks(self):
        self.task()
        before = self.snapshot()
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=providers.ProviderUnavailable("server-secret")):
            result = self.assist()
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["drafts"], [])
        self.assertEqual(self.snapshot(), before)
        self.assert_private(result)

    def test_no_matching_evidence_does_not_accept_model_claims(self):
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Quasarwhimsy"}),
            final_turn("There are no matching sources."),
        ])
        self.assertEqual(result["status"], "no_evidence")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["sources"], [])

    def test_missing_or_invented_final_citations_withhold_answer(self):
        self.upload()
        for content in ("Review the report.", "Review the report [S99].", "Review it [S1] with invented support [S99]."):
            with self.subTest(content=content):
                result, _ = self.run_turns([
                    tool_turn("search_project_sources", {"query": "Nebulawork"}), final_turn(content), final_turn(content),
                ])
                self.assertEqual(result["status"], "invalid_response")
                self.assertIsNone(result["answer"])
                self.assertEqual(result["drafts"], [])

    def test_one_citation_correction_uses_existing_sources_and_retains_turn_budget(self):
        self.upload()
        result, chat = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}),
            final_turn("An independent review is required."),
            final_turn("An independent review is required [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(chat.call_count, 3)
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(len(result["sources"]), 1)
        correction = chat.call_args.args[0][-1]
        self.assertIn("[S1]", correction["content"])
        self.assertEqual(correction["role"], "user")

    def test_citation_correction_cannot_run_additional_tools(self):
        self.upload()
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}),
            final_turn("An independent review is required."),
            tool_turn("list_project_tasks", {}, "unexpected-1"),
        ])
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual(len(result["steps"]), 1)
        self.assertIsNone(result["answer"])

    def test_invalid_citations_on_fourth_turn_do_not_extend_model_limit(self):
        self.upload()
        result, chat = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "one"),
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "two"),
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "three"),
            final_turn("An independent review is required."),
        ])
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual(chat.call_count, 4)

    def test_unknown_tool_is_rejected_without_any_write(self):
        before = self.snapshot()
        result, _ = self.run_turns([tool_turn("delete_project_tasks", {})])
        self.assertEqual(result["status"], "invalid_response")
        self.assertIsNone(result["answer"])
        self.assertEqual(self.snapshot(), before)

    def test_malformed_model_envelopes_and_tool_names_fail_closed(self):
        invalid = (
            None, {"content": 123, "tool_calls": []}, {"content": "", "tool_calls": None},
            {"content": "", "tool_calls": [{"id": "call-1", "name": [], "arguments": {}}]},
            {"content": "", "tool_calls": [{"id": 0, "name": "list_project_tasks", "arguments": {}}]},
            {"content": "", "tool_calls": [{"id": None, "name": "list_project_tasks", "arguments": {}}]},
            {"content": "", "tool_calls": [{"id": "call-1", "name": "list_project_tasks", "arguments": []}]},
            {"content": "", "tool_calls": [{"id": "call-1", "name": "list_project_tasks", "arguments": {}, "extra": "untrusted"}]},
        )
        for response in invalid:
            with self.subTest(response=response):
                result, _ = self.run_turns([response])
                self.assertEqual(result["status"], "invalid_response")
                self.assertIsNone(result["answer"])
                self.assertEqual(result["drafts"], [])

    def test_reused_tool_call_id_is_rejected(self):
        self.task()
        result, _ = self.run_turns([
            tool_turn("list_project_tasks", {}, "reused-1"),
            tool_turn("list_project_tasks", {}, "reused-1"),
        ])
        self.assertEqual(result["status"], "invalid_response")
        self.assertIsNone(result["answer"])

    def test_ollama_missing_call_id_gets_unique_local_identifier(self):
        self.task()
        result, _ = self.run_turns([
            tool_turn("list_project_tasks", {}, ""),
            tool_turn("list_project_tasks", {}, ""),
            final_turn("Review the report task [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["steps"]), 2)
        self.assertEqual(len(result["sources"]), 1)

    def test_tool_arguments_cannot_override_project_or_accept_unknown_fields(self):
        invalid = (
            ("search_project_sources", {"query": "Nebulawork", "project_id": str(self.project.pk)}),
            ("list_project_tasks", {"status": "all", "project_id": str(self.project.pk)}),
            ("list_project_tasks", {"status": "invalid"}),
            ("search_project_sources", {"query": 123}),
            ("search_project_sources", {"query": "Nebulawork", "max_sources": True}),
            ("search_project_sources", {"query": "Nebulawork", "max_sources": 7}),
        )
        for name, arguments in invalid:
            with self.subTest(name=name, arguments=arguments):
                result, _ = self.run_turns([tool_turn(name, arguments)])
                self.assertEqual(result["status"], "invalid_response")
                self.assertIsNone(result["answer"])
                self.assertEqual(result["drafts"], [])

    def test_invalid_task_drafts_are_rejected_without_database_changes(self):
        self.upload()
        invalid = (
            {"title": "Review report", "description": "Follow the requirements", "source_citations": ["S99"]},
            {"title": "Review report", "description": "Follow the requirements", "source_citations": []},
            {"title": "a", "description": "Follow the requirements", "source_citations": ["S1"]},
            {"title": "Review report", "description": "x" * 2001, "source_citations": ["S1"]},
            {"title": "Review report", "description": "Follow requirements", "source_citations": ["S1"], "assignee_id": str(self.member.pk)},
        )
        before = self.snapshot()
        for draft in invalid:
            with self.subTest(draft=draft):
                result, _ = self.run_turns([
                    tool_turn("search_project_sources", {"query": "Nebulawork"}, "source-1"),
                    tool_turn("propose_tasks", {"tasks": [draft]}, "draft-1"),
                ])
                self.assertEqual(result["status"], "invalid_response")
                self.assertEqual(result["drafts"], [])
                self.assertEqual(self.snapshot(), before)

    def test_more_than_five_drafts_is_rejected(self):
        self.upload()
        drafts = [{"title": f"Review report {index}", "description": "Follow requirements", "source_citations": ["S1"]} for index in range(6)]
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "source-1"),
            tool_turn("propose_tasks", {"tasks": drafts}, "draft-1"),
        ])
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual(result["drafts"], [])
        self.assertEqual(Task.objects.count(), 0)

    def test_existing_task_and_duplicate_drafts_are_omitted_without_writes(self):
        self.upload()
        self.task(title="Review the requirements")
        before = self.snapshot()
        drafts = [
            {"title": "review THE requirements", "description": "Existing task", "source_citations": ["S1"]},
            {"title": "Arrange an independent review", "description": "Suggested follow-up", "source_citations": ["S1"]},
            {"title": "ARRANGE AN independent review", "description": "Repeated follow-up", "source_citations": ["S1"]},
        ]
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "source-1"),
            tool_turn("propose_tasks", {"tasks": drafts}, "draft-1"),
            final_turn("An independent review is suggested by the requirements [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["drafts"]), 1)
        self.assertTrue(result["warnings"])
        self.assertEqual(self.snapshot(), before)

    def test_model_loop_is_limited_to_four_turns(self):
        self.upload()
        result, chat = self.run_turns([tool_turn("search_project_sources", {"query": "Nebulawork"}, f"call-{index}") for index in range(4)])
        self.assertEqual(result["status"], "limit_reached")
        self.assertEqual(chat.call_count, 4)
        self.assertEqual(chat.call_args.args[1], [])
        self.assertIsNone(result["answer"])
        self.assertEqual(result["drafts"], [])

    def test_final_model_turn_is_reserved_for_a_cited_answer(self):
        self.upload()
        requests = []

        def model(messages, tools, **kwargs):
            requests.append((list(messages), tools))
            if tools:
                return tool_turn("search_project_sources", {"query": "Nebulawork"}, f"read-{len(requests)}")
            return final_turn("An independent security review is required [S1].")

        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model):
            result = self.assist()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 4)
        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(requests[-1][1], [])
        self.assertIn("[S1]", requests[-1][0][-1]["content"])
        self.assertIn("final answer", requests[-1][0][-1]["content"])

    def test_successful_proposal_finishes_without_exposing_tools_again(self):
        self.upload()
        before = self.snapshot()
        requests = []

        def model(messages, tools, **kwargs):
            requests.append(tools)
            if len(requests) == 1:
                return tool_turn("search_project_sources", {"query": "Nebulawork"}, "read-1")
            if tools:
                return tool_turn("propose_tasks", {"tasks": [{"title": "Arrange a security review",
                    "description": "Review the stated requirements.", "source_citations": ["S1"]}]},
                    f"draft-{len(requests)}")
            return final_turn("Review the unsaved draft card based on the requirements [S1].")

        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model):
            result = self.assist()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[-1], [])
        self.assertEqual([step["tool"] for step in result["steps"]], ["search_project_sources", "propose_tasks"])
        self.assertEqual(len(result["drafts"]), 1)
        self.assertEqual(self.snapshot(), before)

    def test_provider_cannot_run_a_tool_after_proposals_enter_finalization(self):
        self.upload()
        result, chat = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "read-1"),
            tool_turn("propose_tasks", {"tasks": [{"title": "Arrange a security review",
                "description": "Review the requirements.", "source_citations": ["S1"]}]}, "draft-1"),
            tool_turn("list_project_tasks", {}, "unexpected-1"),
            final_turn("Review the requirements [S1]."),
        ])
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual(chat.call_count, 3)
        self.assertEqual(chat.call_args.args[1], [])
        self.assertEqual(len(result["steps"]), 2)
        self.assertIsNone(result["answer"])
        self.assertEqual(result["drafts"], [])

    def test_a_second_proposal_in_the_same_tool_batch_is_not_executed(self):
        self.upload()
        draft = {"tasks": [{"title": "Arrange a security review", "description": "Review the requirements.",
                            "source_citations": ["S1"]}]}
        result, _ = self.run_turns([
            tool_turn("search_project_sources", {"query": "Nebulawork"}, "read-1"),
            {"content": "", "tool_calls": [
                tool_turn("propose_tasks", draft, "draft-1")["tool_calls"][0],
                tool_turn("propose_tasks", draft, "draft-2")["tool_calls"][0],
            ]},
        ])
        self.assertEqual(result["status"], "invalid_response")
        self.assertEqual([step["tool"] for step in result["steps"]], ["search_project_sources", "propose_tasks"])
        self.assertEqual(result["drafts"], [])

    def test_finalization_still_withholds_invented_citations_and_source_credentials(self):
        self.upload("Nebulawork password is BLUE-MOON-SECRET. The report needs a security review.")
        for text in ("Review the report [S99].", "Use BLUE-MOON-SECRET [S1]."):
            with self.subTest(answer=text):
                result, chat = self.run_turns([
                    tool_turn("search_project_sources", {"query": "Nebulawork"}, "read-1"),
                    tool_turn("propose_tasks", {"tasks": [{"title": "Arrange a security review",
                        "description": "Review the report requirements.", "source_citations": ["S1"]}]}, "draft-1"),
                    final_turn(text), final_turn(text),
                ])
                self.assertEqual(result["status"], "invalid_response")
                self.assertEqual(chat.call_args.args[1], [])
                self.assertIsNone(result["answer"])
                self.assertEqual(result["drafts"], [])

    def test_total_deadline_withholds_late_model_answer(self):
        self.task()
        clock = [0.0]
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("list_project_tasks", {}, "task-1")
            clock[0] = 23.0
            return final_turn("Review the report [S1].")
        with self.configured(), override_settings(RAG_AGENT_TIMEOUT_SECONDS=22), patch("knowledge.agent.time.monotonic", side_effect=lambda: clock[0]), patch("knowledge.agent.providers.agent_chat", side_effect=model) as chat:
            result = self.assist()
        self.assertEqual(result["status"], "limit_reached")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["drafts"], [])
        self.assertEqual(chat.call_count, 2)

    def test_read_tool_using_remaining_budget_stops_before_next_model_request(self):
        self.upload()
        clock = [0.0]
        original_corpus = agent.corpus
        def delayed_read(*args, **kwargs):
            result = original_corpus(*args, **kwargs)
            clock[0] = 23.0
            return result
        with self.configured(), override_settings(RAG_AGENT_TIMEOUT_SECONDS=22), patch("knowledge.agent.time.monotonic", side_effect=lambda: clock[0]), patch("knowledge.agent.corpus", side_effect=delayed_read), patch("knowledge.agent.providers.agent_chat", return_value=tool_turn("search_project_sources", {"query": "Nebulawork"})) as chat:
            result = self.assist()
        self.assertEqual(result["status"], "limit_reached")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["drafts"], [])
        self.assertEqual(chat.call_count, 1)

    def test_source_budget_reports_truncated_task_list(self):
        for index in range(22):
            self.task(title=f"Review report section {index}")
        result, _ = self.run_turns([
            tool_turn("list_project_tasks", {"status": "all"}),
            final_turn("Review the listed tasks [S1]."),
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["sources"]), 12)
        self.assertTrue(result["warnings"])
        self.assertEqual(result["steps"][0]["result_count"], 12)

    def test_model_cannot_run_more_than_six_tool_calls(self):
        calls = [tool_turn("list_project_tasks", {"status": "all"}, f"call-{index}")["tool_calls"][0] for index in range(7)]
        result, chat = self.run_turns([{"content": "", "tool_calls": calls}])
        self.assertEqual(result["status"], "limit_reached")
        self.assertLessEqual(len(result["steps"]), 6)
        self.assertEqual(chat.call_count, 1)
        self.assertIsNone(result["answer"])

    def test_outsider_and_removed_member_cannot_start_assistant(self):
        with self.configured(), patch("knowledge.agent.providers.agent_chat") as chat:
            with self.assertRaises(Http404):
                self.assist(user=self.outsider)
            ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
            with self.assertRaises(Http404):
                self.assist()
            chat.assert_not_called()

    def test_closed_account_is_checked_against_current_database(self):
        get_user_model().objects.filter(pk=self.member.pk).update(closed_at=timezone.now())
        with self.configured(), patch("knowledge.agent.providers.agent_chat") as chat:
            with self.assertRaises(Http404):
                self.assist()
            chat.assert_not_called()

    def test_membership_revocation_during_provider_withholds_result(self):
        self.upload()
        def revoke(*args, **kwargs):
            ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
            return final_turn("Review report [S1].")
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            return tool_turn("search_project_sources", {"query": "Nebulawork"}) if count == 1 else revoke()
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(Http404):
            self.assist()

    def test_revocation_during_provider_failure_still_withholds_evidence(self):
        self.upload()
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("search_project_sources", {"query": "Nebulawork"})
            ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
            raise providers.ProviderUnavailable("server-secret")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(Http404):
            self.assist()

    def test_account_disabled_during_provider_withholds_result(self):
        def disable(*args, **kwargs):
            get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
            return final_turn("No evidence")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=disable), self.assertRaises(Http404):
            self.assist()

    def test_file_replacement_during_model_call_requires_fresh_request(self):
        document = self.upload()
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("search_project_sources", {"query": "Nebulawork"})
            self.upload("Nebulawork changed security requirements", document=document)
            return final_turn("Review report [S1].")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(ValidationError):
            self.assist()

    def test_document_removal_during_model_call_requires_fresh_request(self):
        document = self.upload()
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("search_project_sources", {"query": "Nebulawork"})
            ProjectDocument.objects.filter(pk=document.pk).update(removed_at=timezone.now())
            return final_turn("Review report [S1].")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(ValidationError):
            self.assist()

    def test_task_edit_during_model_call_requires_fresh_request(self):
        task = self.task()
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("list_project_tasks", {"status": "all"})
            Task.objects.filter(pk=task.pk).update(description="Changed review requirements")
            return final_turn("Review report [S1].")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(ValidationError):
            self.assist()

    def test_meeting_edit_during_model_call_requires_fresh_request(self):
        record = self.record()
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("search_project_sources", {"query": "Nebulawork"})
            MeetingRecord.objects.filter(pk=record.pk).update(minutes="Nebulawork revised decision", version=2)
            return final_turn("Review report [S1].")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(ValidationError):
            self.assist()

    def test_archived_task_during_model_call_requires_fresh_request(self):
        task = self.task()
        count = 0
        def model(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return tool_turn("list_project_tasks", {"status": "all"})
            Task.objects.filter(pk=task.pk).update(archived_at=timezone.now())
            return final_turn("Review report [S1].")
        with self.configured(), patch("knowledge.agent.providers.agent_chat", side_effect=model), self.assertRaises(ValidationError):
            self.assist()

    def test_api_capabilities_and_result_are_private_not_cacheable(self):
        self.authenticate(self.member)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["available"])
        self.assertEqual(response.json()["max_steps"], 4)
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.post(self.url(), {"question": "Plan the report"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], "model_unavailable")
        self.assertIn("no-store", response["Cache-Control"])
        self.assert_private(response.json())

    def test_api_requires_completed_mfa_and_csrf(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        csrf = APIClient(enforce_csrf_checks=True)
        self.authenticate(self.member, client=csrf)
        self.assertEqual(csrf.post(self.url(), {"question": "Plan the report"}, format="json").status_code, 403)

    def test_api_rejects_outsider_before_model_call(self):
        self.authenticate(self.outsider)
        with patch("knowledge.agent.providers.agent_chat") as chat:
            self.assertEqual(self.client.get(self.url()).status_code, 404)
            self.assertEqual(self.client.post(self.url(), {"question": "Plan the report"}, format="json").status_code, 404)
            chat.assert_not_called()

    def test_api_strict_input_cannot_invoke_tools_or_select_another_project(self):
        self.authenticate(self.member)
        invalid = ({}, {"question": " "}, {"question": 123}, {"question": "x" * 1001},
                   {"question": "Plan the report", "project_id": str(self.project.pk)},
                   {"question": "Plan the report", "tools": []})
        with patch("knowledge.agent.providers.agent_chat") as chat:
            for payload in invalid:
                with self.subTest(payload=payload):
                    response = self.client.post(self.url(), payload, format="json")
                    self.assertEqual(response.status_code, 400, response.content)
            chat.assert_not_called()
