"""Model transport tests use stub HTTP streams and never contact a provider."""

import asyncio
import json
import time
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
import httpx

from integrations import rag_model


class StubResponse:
    def __init__(self, status, blocks, headers=None):
        self.status_code = status
        self.blocks = blocks
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_raw(self):
        for block in self.blocks:
            yield block


class StubClient:
    def __init__(self, response):
        self.stream = Mock(return_value=response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@override_settings(
    RAG_PROVIDER="ollama",
    RAG_BASE_URL="http://127.0.0.1:11434",
    RAG_MODEL="test-model",
    RAG_API_KEY="",
    RAG_TIMEOUT_SECONDS=15,
)
class ModelProviderTests(SimpleTestCase):
    sources = [{
        "citation": "S1", "title": "Project requirements", "locator": "Paragraph 1",
        "excerpt": "A security review is required.", "source_id": "private-id",
        "url": "/private/download/", "kind": "file", "version": 1, "page": None,
    }]

    def transport(self, payload, *, status=200, blocks=None, headers=None):
        body = json.dumps(payload).encode("utf-8")
        response = StubResponse(status, blocks if blocks is not None else [body], headers)
        client = StubClient(response)
        return client, patch("integrations.rag_model.httpx.AsyncClient", return_value=client)

    def test_disabled_provider_never_opens_http_client(self):
        with override_settings(RAG_PROVIDER="disabled"), patch("integrations.rag_model.httpx.AsyncClient") as client:
            with self.assertRaises(rag_model.ProviderUnavailable):
                rag_model.generate("Which review?", self.sources)
        client.assert_not_called()

    def test_invalid_configuration_is_rejected_before_network(self):
        invalid = (
            {"RAG_PROVIDER": "unknown"}, {"RAG_MODEL": ""},
            {"RAG_BASE_URL": "http://remote.example/v1"},
            {"RAG_BASE_URL": "https://user:secret@example.com/v1"},
            {"RAG_BASE_URL": "https://example.com/v1?api_key=secret"},
            {"RAG_BASE_URL": "https://example.com/v1#secret"},
            {"RAG_BASE_URL": "file:///tmp/model"},
            {"RAG_TIMEOUT_SECONDS": 0}, {"RAG_TIMEOUT_SECONDS": 21},
        )
        with patch("integrations.rag_model.httpx.AsyncClient") as client:
            for settings in invalid:
                with self.subTest(settings=settings), override_settings(**settings):
                    with self.assertRaises(rag_model.ProviderUnavailable):
                        rag_model.generate("Which review?", self.sources)
            client.assert_not_called()

    def test_ollama_response_and_request_are_bounded_and_private(self):
        client, mocked = self.transport({"done": True, "message": {"content": "Security review [S1]."}})
        with mocked as factory:
            self.assertEqual(rag_model.generate("Which review?", self.sources), "Security review [S1].")
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertEqual(factory.call_args.kwargs["timeout"], 15)
        method, url = client.stream.call_args.args
        self.assertEqual((method, url), ("POST", "http://127.0.0.1:11434/api/chat"))
        payload = client.stream.call_args.kwargs["json"]
        self.assertFalse(payload["stream"])
        supplied = json.loads(payload["messages"][-1]["content"])
        self.assertEqual(supplied["question"], "Which review?")
        self.assertEqual(supplied["sources"][0]["citation"], "S1")
        self.assertNotIn("private-id", json.dumps(payload))
        self.assertNotIn("/private/download/", json.dumps(payload))

    def test_compatible_transport_uses_chat_endpoint_and_server_credential(self):
        client, mocked = self.transport({"choices": [{"message": {"content": "Security review [S1]."}}]})
        with override_settings(RAG_PROVIDER="compatible", RAG_BASE_URL="https://model.example/v1", RAG_API_KEY="server-secret"), mocked:
            self.assertEqual(rag_model.generate("Which review?", self.sources), "Security review [S1].")
        self.assertEqual(client.stream.call_args.args[1], "https://model.example/v1/chat/completions")
        self.assertEqual(client.stream.call_args.kwargs["headers"]["Authorization"], "Bearer server-secret")
        self.assertNotIn("server-secret", json.dumps(client.stream.call_args.kwargs["json"]))

    def test_upstream_http_failure_has_no_response_body_or_secret(self):
        _, mocked = self.transport({"error": "server-secret private upstream diagnostic"}, status=500)
        with mocked, self.assertRaises(rag_model.ProviderUnavailable) as error:
            rag_model.generate("Which review?", self.sources)
        self.assertNotIn("server-secret", str(error.exception))
        self.assertNotIn("upstream diagnostic", str(error.exception))

    def test_timeout_is_converted_into_safe_unavailable_error(self):
        with patch("integrations.rag_model.httpx.AsyncClient", side_effect=httpx.ReadTimeout("server-secret")):
            with self.assertRaises(rag_model.ProviderUnavailable) as error:
                rag_model.generate("Which review?", self.sources)
        self.assertNotIn("server-secret", str(error.exception))

    def test_invalid_incomplete_and_empty_model_results_are_rejected(self):
        for result in ({}, {"done": False, "message": {"content": "Partial answer"}},
                       {"done": True, "message": {"content": ""}},
                       {"done": True, "message": {"content": None}},
                       {"done": True, "message": {"content": "x" * 8001}}):
            _, mocked = self.transport(result)
            with self.subTest(result=result), mocked, self.assertRaises(rag_model.ProviderUnavailable):
                rag_model.generate("Which review?", self.sources)

    def test_response_byte_limit_rejects_oversized_stream(self):
        _, mocked = self.transport({}, blocks=[b"x" * 40_000, b"x" * 40_000])
        with mocked, self.assertRaises(rag_model.ProviderUnavailable):
            rag_model.generate("Which review?", self.sources)

    def test_malformed_json_is_a_safe_provider_failure(self):
        _, mocked = self.transport({}, blocks=[b"not-json server-secret"])
        with mocked, self.assertRaises(rag_model.ProviderUnavailable) as error:
            rag_model.generate("Which review?", self.sources)
        self.assertNotIn("server-secret", str(error.exception))

    def test_deeply_nested_json_is_a_safe_provider_failure(self):
        _, mocked = self.transport({}, blocks=[b"[" * 10000 + b"]" * 10000])
        with mocked, self.assertRaises(rag_model.ProviderUnavailable):
            rag_model.generate("Which review?", self.sources)

    def test_truncated_ollama_and_compatible_answers_are_withheld(self):
        _, mocked = self.transport({"done": True, "done_reason": "length", "message": {"content": "Partial answer [S1]."}})
        with mocked, self.assertRaises(rag_model.ProviderUnavailable):
            rag_model.generate("Which review?", self.sources)
        for choice in ({"finish_reason": "length", "message": {"content": "Partial answer [S1]."}}, None, 123):
            _, mocked = self.transport({"choices": [choice]})
            with self.subTest(choice=choice), override_settings(RAG_PROVIDER="compatible", RAG_BASE_URL="https://model.example/v1"), mocked, self.assertRaises(rag_model.ProviderUnavailable):
                rag_model.generate("Which review?", self.sources)

    def test_remaining_budget_is_fractional_capped_and_validated_before_network(self):
        for budget, expected in ((0.25, 0.25), (30, 15)):
            _, mocked = self.transport({"done": True, "message": {"content": "Review required [S1]."}})
            with self.subTest(budget=budget), mocked as factory:
                rag_model.generate("Which review?", self.sources, timeout=budget)
                self.assertEqual(factory.call_args.kwargs["timeout"], expected)
        with patch("integrations.rag_model.httpx.AsyncClient") as client:
            for invalid in (0, -1, True, float("nan"), float("inf"), "15"):
                with self.subTest(budget=invalid), self.assertRaises(rag_model.ProviderUnavailable):
                    rag_model.generate("Which review?", self.sources, timeout=invalid)
            client.assert_not_called()

    def test_compressed_response_is_rejected_without_decompression(self):
        _, mocked = self.transport({}, headers={"Content-Encoding": "gzip"})
        with mocked, self.assertRaises(rag_model.ProviderUnavailable):
            rag_model.generate("Which review?", self.sources)

    def test_stalled_stream_is_cancelled_at_total_request_deadline(self):
        class StalledResponse(StubResponse):
            cancelled = False

            async def aiter_raw(self):
                try:
                    yield b"{"
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True

        response = StalledResponse(200, [])
        client = StubClient(response)
        started = time.monotonic()
        with override_settings(RAG_TIMEOUT_SECONDS=1), patch("integrations.rag_model.httpx.AsyncClient", return_value=client):
            with self.assertRaises(rag_model.ProviderUnavailable):
                rag_model.generate("Which review?", self.sources)
        self.assertTrue(response.cancelled)
        self.assertLess(time.monotonic() - started, 3)

    def test_remaining_fractional_budget_cancels_stalled_stream(self):
        class StalledResponse(StubResponse):
            cancelled = False

            async def aiter_raw(self):
                try:
                    yield b"{"
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True

        response = StalledResponse(200, [])
        with patch("integrations.rag_model.httpx.AsyncClient", return_value=StubClient(response)), self.assertRaises(rag_model.ProviderUnavailable):
            rag_model.generate("Which review?", self.sources, timeout=0.05)
        self.assertTrue(response.cancelled)
