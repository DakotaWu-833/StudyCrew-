"""Tool transport contracts use stub streams and never contact a model."""
import asyncio
import json
import time
from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase, override_settings

from integrations import rag_agent
from integrations.rag_model import ProviderUnavailable


class StubResponse:
    def __init__(self, payload, *, status=200, headers=None, blocks=None):
        self.status_code = status
        self.headers = headers or {}
        self.blocks = blocks if blocks is not None else [json.dumps(payload).encode("utf-8")]
        self.read = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_raw(self):
        self.read = True
        for block in self.blocks:
            yield block


class StubClient:
    def __init__(self, response):
        self.stream = Mock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@override_settings(RAG_PROVIDER="ollama", RAG_BASE_URL="http://127.0.0.1:11434", RAG_MODEL="test-model",
                   RAG_API_KEY="", RAG_TIMEOUT_SECONDS=15)
class AgentProviderTests(SimpleTestCase):
    messages = [{"role": "system", "content": "Use project tools."}, {"role": "user", "content": "Find the review."}]
    tools = [{"type": "function", "function": {
        "name": "search_project_sources", "description": "Search this project's documents.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }}]

    def transport(self, payload, **kwargs):
        response = StubResponse(payload, **kwargs)
        client = StubClient(response)
        return client, response, patch("integrations.rag_agent.httpx.AsyncClient", return_value=client)

    @staticmethod
    def ollama_call(arguments=None, **kwargs):
        return {"function": {"name": "search_project_sources", "arguments": {"query": "review"} if arguments is None else arguments}, **kwargs}

    @staticmethod
    def compatible_call(arguments='{"query":"review"}', **kwargs):
        return {"id": "call_abc-123", "type": "function",
                "function": {"name": "search_project_sources", "arguments": arguments}, **kwargs}

    def configured_compatible(self):
        return override_settings(RAG_PROVIDER="compatible", RAG_BASE_URL="https://model.example/v1", RAG_API_KEY="server-secret")

    def test_ollama_calls_return_dict_arguments_and_missing_id_for_orchestrator(self):
        _, _, mocked = self.transport({"done": True, "message": {"content": "", "tool_calls": [self.ollama_call()]}})
        with mocked:
            result = rag_agent.agent_chat(self.messages, self.tools)
        self.assertEqual(result, {"content": "", "tool_calls": [
            {"id": "", "name": "search_project_sources", "arguments": {"query": "review"}},
        ]})

    def test_ollama_tool_history_uses_object_arguments_and_tool_name(self):
        client, _, mocked = self.transport({"done": True, "message": {"content": "Review required [S1]."}})
        history = self.messages + [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "local_1", "name": "search_project_sources", "arguments": {"query": "安全 review"}},
            ]},
            {"role": "tool", "content": '{"sources":["S1"]}', "tool_call_id": "local_1", "tool_name": "search_project_sources"},
        ]
        with mocked as factory:
            result = rag_agent.agent_chat(history, self.tools, timeout=2.5)
        self.assertEqual(result["content"], "Review required [S1].")
        self.assertEqual(client.stream.call_args.args, ("POST", "http://127.0.0.1:11434/api/chat"))
        payload = client.stream.call_args.kwargs["json"]
        self.assertEqual(payload["tools"], self.tools)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][-2]["tool_calls"], [{"function": {
            "name": "search_project_sources", "arguments": {"query": "安全 review"},
        }}])
        self.assertEqual(payload["messages"][-1], {"role": "tool", "content": '{"sources":["S1"]}', "tool_name": "search_project_sources"})
        self.assertEqual(factory.call_args.kwargs["timeout"], 2.5)
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertEqual(client.stream.call_args.kwargs["headers"]["Accept-Encoding"], "identity")

    def test_compatible_calls_preserve_id_and_decode_arguments(self):
        client, _, mocked = self.transport({"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [self.compatible_call()],
        }}]})
        with self.configured_compatible(), mocked:
            result = rag_agent.agent_chat(self.messages, self.tools)
        self.assertEqual(result, {"content": "", "tool_calls": [
            {"id": "call_abc-123", "name": "search_project_sources", "arguments": {"query": "review"}},
        ]})
        self.assertEqual(client.stream.call_args.args[1], "https://model.example/v1/chat/completions")
        self.assertEqual(client.stream.call_args.kwargs["headers"]["Authorization"], "Bearer server-secret")
        self.assertEqual(client.stream.call_args.kwargs["json"]["tool_choice"], "auto")
        self.assertNotIn("server-secret", json.dumps(client.stream.call_args.kwargs["json"]))

    def test_compatible_tool_history_serializes_arguments_and_links_result_to_id(self):
        client, _, mocked = self.transport({"choices": [{"message": {"content": "Review required [S1].", "tool_calls": None}}]})
        history = self.messages + [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_abc-123", "name": "search_project_sources", "arguments": {"query": "安全 review"}}]},
            {"role": "tool", "content": "Found S1.", "tool_call_id": "call_abc-123", "tool_name": "search_project_sources"},
        ]
        with self.configured_compatible(), mocked:
            self.assertEqual(rag_agent.agent_chat(history, self.tools)["tool_calls"], [])
        payload = client.stream.call_args.kwargs["json"]
        call = payload["messages"][-2]["tool_calls"][0]
        self.assertEqual(call["id"], "call_abc-123")
        self.assertEqual(call["type"], "function")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"query": "安全 review"})
        self.assertEqual(payload["messages"][-1], {"role": "tool", "content": "Found S1.", "tool_call_id": "call_abc-123"})

    def test_compatible_requires_safe_unique_call_ids(self):
        calls = [self.compatible_call(id=value) for value in (None, "", "unsafe\nID", "a" * 129, "has space", "/path")]
        missing = self.compatible_call()
        del missing["id"]
        responses = [[call] for call in calls] + [[missing], [self.compatible_call(), self.compatible_call()]]
        for tool_calls in responses:
            _, _, mocked = self.transport({"choices": [{"message": {"content": "", "tool_calls": tool_calls}}]})
            with self.subTest(calls=tool_calls), self.configured_compatible(), mocked, self.assertRaises(ProviderUnavailable):
                rag_agent.agent_chat(self.messages, self.tools)

    def test_calls_have_bounded_object_arguments_for_both_providers(self):
        invalid = ('[]', 'null', '"text"', '{"bad":NaN}', '{"query":"' + "x" * 8200 + '"}', '{invalid')
        for arguments in invalid:
            _, _, mocked = self.transport({"choices": [{"message": {"tool_calls": [self.compatible_call(arguments)]}}]})
            with self.subTest(provider="compatible", arguments=arguments[:20]), self.configured_compatible(), mocked, self.assertRaises(ProviderUnavailable):
                rag_agent.agent_chat(self.messages, self.tools)
        for arguments in ([], "{}", None, {"query": "x" * 8200}, {"bad": float("nan")}):
            call = {"function": {"name": "search_project_sources", "arguments": arguments}}
            _, _, mocked = self.transport({"done": True, "message": {"tool_calls": [call]}})
            with self.subTest(provider="ollama", arguments=str(arguments)[:20]), mocked, self.assertRaises(ProviderUnavailable):
                rag_agent.agent_chat(self.messages, self.tools)

    def test_argument_limit_uses_utf8_bytes(self):
        call = self.ollama_call({"query": "安" * 3000})
        _, _, mocked = self.transport({"done": True, "message": {"tool_calls": [call]}})
        with mocked, self.assertRaises(ProviderUnavailable):
            rag_agent.agent_chat(self.messages, self.tools)

    def test_invalid_response_structures_and_incomplete_content_are_rejected(self):
        responses = [[], {}, {"done": False, "message": {"content": "Partial"}},
                     {"done": True, "message": []}, {"done": True, "message": {"role": "tool", "content": "Result"}},
                     {"done": True, "message": {"content": []}}, {"done": True, "message": {"content": "x" * 8001}},
                     {"done": True, "message": {"content": " "}},
                     {"done": True, "message": {"tool_calls": [None]}},
                     {"done": True, "message": {"tool_calls": [self.ollama_call()] * 7}},
                     {"done": True, "message": {"tool_calls": [self.ollama_call(type="other")]}},
                     {"done": True, "message": {"tool_calls": [{"function": {"name": "bad name", "arguments": {}}}]}}]
        for result in responses:
            _, _, mocked = self.transport(result)
            with self.subTest(result=str(result)[:80]), mocked, self.assertRaises(ProviderUnavailable):
                rag_agent.agent_chat(self.messages, self.tools)
        for choice in ({"finish_reason": "length", "message": {"content": "Partial"}}, {"message": None}):
            _, _, mocked = self.transport({"choices": [choice]})
            with self.configured_compatible(), mocked, self.assertRaises(ProviderUnavailable):
                rag_agent.agent_chat(self.messages, self.tools)

    def test_unknown_tool_is_returned_as_data_for_application_allowlist(self):
        _, _, mocked = self.transport({"done": True, "message": {"tool_calls": [
            {"function": {"name": "unknown_tool", "arguments": {}}},
        ]}})
        with mocked:
            result = rag_agent.agent_chat(self.messages, self.tools)
        self.assertEqual(result["tool_calls"][0]["name"], "unknown_tool")

    def test_disabled_configuration_and_invalid_deadlines_never_open_network(self):
        with override_settings(RAG_PROVIDER="disabled"), patch("integrations.rag_agent.httpx.AsyncClient") as client, self.assertRaises(ProviderUnavailable):
            rag_agent.agent_chat(self.messages, self.tools)
        client.assert_not_called()
        with patch("integrations.rag_agent.httpx.AsyncClient") as client:
            for timeout in (0, -1, float("nan"), float("inf"), True, "1"):
                with self.subTest(timeout=timeout), self.assertRaises(ProviderUnavailable):
                    rag_agent.agent_chat(self.messages, self.tools, timeout=timeout)
            client.assert_not_called()

    def test_timeout_is_capped_at_server_configuration_and_no_tools_are_optional(self):
        _, _, mocked = self.transport({"done": True, "message": {"content": "Finished."}})
        with mocked as factory:
            rag_agent.agent_chat(self.messages, [], timeout=100)
        self.assertEqual(factory.call_args.kwargs["timeout"], 15)

    def test_malformed_messages_and_tool_schemas_are_safe_before_network(self):
        invalid = [([], self.tools), ([{"role": "invalid", "content": "secret"}], self.tools),
                   ([{"role": "user", "content": 123}], self.tools), (self.messages, [{"type": "other"}]),
                   (self.messages, [{"type": "function", "function": {"name": "bad name", "description": "", "parameters": {}}}])]
        with patch("integrations.rag_agent.httpx.AsyncClient") as client:
            for messages, tools in invalid:
                with self.subTest(messages=messages), self.assertRaises(ProviderUnavailable) as error:
                    rag_agent.agent_chat(messages, tools)
                self.assertNotIn("secret", str(error.exception))
            client.assert_not_called()

    def test_http_failures_and_redirects_do_not_read_or_expose_upstream_secrets(self):
        for status in (302, 400, 500):
            _, response, mocked = self.transport({"error": "server-secret upstream detail"}, status=status)
            with self.subTest(status=status), mocked, self.assertRaises(ProviderUnavailable) as error:
                rag_agent.agent_chat(self.messages, self.tools)
            self.assertFalse(response.read)
            self.assertNotIn("server-secret", str(error.exception))
        with patch("integrations.rag_agent.httpx.AsyncClient", side_effect=httpx.ReadTimeout("server-secret")), self.assertRaises(ProviderUnavailable) as error:
            rag_agent.agent_chat(self.messages, self.tools)
        self.assertNotIn("server-secret", str(error.exception))

    def test_compressed_and_oversized_bodies_are_rejected(self):
        _, response, mocked = self.transport({}, headers={"Content-Encoding": "gzip"})
        with mocked, self.assertRaises(ProviderUnavailable):
            rag_agent.agent_chat(self.messages, self.tools)
        self.assertFalse(response.read)
        _, _, mocked = self.transport({}, blocks=[b"x" * 40000, b"x" * 40000])
        with mocked, self.assertRaises(ProviderUnavailable):
            rag_agent.agent_chat(self.messages, self.tools)
        _, _, mocked = self.transport({}, blocks=[b"invalid-json server-secret"])
        with mocked, self.assertRaises(ProviderUnavailable) as error:
            rag_agent.agent_chat(self.messages, self.tools)
        self.assertNotIn("server-secret", str(error.exception))

    def test_stalled_stream_obeys_fractional_total_deadline(self):
        class StalledResponse(StubResponse):
            cancelled = False

            async def aiter_raw(self):
                try:
                    yield b"{"
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True

        response = StalledResponse({})
        started = time.monotonic()
        with patch("integrations.rag_agent.httpx.AsyncClient", return_value=StubClient(response)), self.assertRaises(ProviderUnavailable):
            rag_agent.agent_chat(self.messages, self.tools, timeout=0.05)
        self.assertTrue(response.cancelled)
        self.assertLess(time.monotonic() - started, 1)
