"""Embedding transport validation and deadlines without a real model service."""

import asyncio
import json
import math
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
import httpx

from integrations import rag_embeddings
from integrations.rag_model import ProviderUnavailable


class StubResponse:
    def __init__(self, blocks, *, status=200, headers=None):
        self.blocks, self.status_code = blocks, status
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


@override_settings(RAG_PROVIDER="ollama", RAG_BASE_URL="http://127.0.0.1:11434",
                   RAG_MODEL="test-chat", RAG_API_KEY="", RAG_TIMEOUT_SECONDS=15,
                   RAG_EMBEDDING_MODEL="test-embed", RAG_EMBEDDING_DIMENSIONS=3)
class EmbeddingProviderTests(SimpleTestCase):
    def transport(self, result, *, status=200, headers=None, blocks=None):
        response = StubResponse(blocks if blocks is not None else [json.dumps(result).encode()], status=status, headers=headers)
        client = StubClient(response)
        return client, patch("integrations.rag_embeddings.httpx.AsyncClient", return_value=client)

    def test_vectors_are_normalized_and_native_ollama_request_is_bounded(self):
        client, mocked = self.transport({"embeddings": [[3, 4, 0], [0, 0, 2]]})
        with mocked as factory:
            vectors = rag_embeddings.embed(["First excerpt", "Second excerpt"], timeout=4)
        self.assertEqual(vectors, [[0.6, 0.8, 0.0], [0.0, 0.0, 1.0]])
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertEqual(factory.call_args.kwargs["timeout"], 4)
        self.assertEqual(client.stream.call_args.args, ("POST", "http://127.0.0.1:11434/api/embed"))
        payload = client.stream.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "test-embed")
        self.assertFalse(payload["truncate"])
        self.assertEqual(payload["keep_alive"], "5m")
        self.assertEqual(payload["dimensions"], 3)

    def test_missing_disabled_and_unsupported_embedding_provider_never_contacts_network(self):
        for settings in ({"RAG_PROVIDER": "disabled"}, {"RAG_PROVIDER": "compatible"}, {"RAG_EMBEDDING_MODEL": ""}):
            with self.subTest(settings=settings), override_settings(**settings), patch("integrations.rag_embeddings.httpx.AsyncClient") as client:
                with self.assertRaises(ProviderUnavailable):
                    rag_embeddings.embed(["Excerpt"])
                client.assert_not_called()

    def test_input_batch_and_dimension_bounds_are_validated_before_network(self):
        invalid_inputs = ([], ["x"] * 17, [""], [123], ["x" * 2001], "not-a-list")
        with patch("integrations.rag_embeddings.httpx.AsyncClient") as client:
            for texts in invalid_inputs:
                with self.subTest(texts=texts), self.assertRaises(ProviderUnavailable):
                    rag_embeddings.embed(texts)
            for dimension in (0, 4097, True, "1024"):
                with self.subTest(dimension=dimension), override_settings(RAG_EMBEDDING_DIMENSIONS=dimension), self.assertRaises(ProviderUnavailable):
                    rag_embeddings.embed(["Excerpt"])
            client.assert_not_called()

    def test_response_vectors_reject_wrong_shape_nonfinite_bool_and_zero(self):
        invalid = ({}, {"embeddings": []}, {"embeddings": [[1, 0]]},
                   {"embeddings": [[1, 0, 0], [1, 0, 0]]},
                   {"embeddings": [[True, 0, 1]]}, {"embeddings": [["1", 0, 0]]},
                   {"embeddings": [[float("nan"), 0, 1]]},
                   {"embeddings": [[float("inf"), 0, 1]]}, {"embeddings": [[0, 0, 0]]})
        for result in invalid:
            _, mocked = self.transport(result)
            with self.subTest(result=result), mocked, self.assertRaises(ProviderUnavailable):
                rag_embeddings.embed(["Excerpt"])

    def test_numeric_normalization_handles_large_finite_coordinates(self):
        _, mocked = self.transport({"embeddings": [[1e308, 1e308, 0]]})
        with mocked:
            vector = rag_embeddings.embed(["Excerpt"])[0]
        self.assertTrue(all(math.isfinite(value) for value in vector))
        self.assertAlmostEqual(sum(value * value for value in vector), 1)

    def test_upstream_failures_hide_credentials_and_response_details(self):
        for status in (401, 500):
            _, mocked = self.transport({"error": "server-secret"}, status=status)
            with self.subTest(status=status), mocked, self.assertRaises(ProviderUnavailable) as error:
                rag_embeddings.embed(["Excerpt"])
            self.assertNotIn("server-secret", str(error.exception))

    def test_invalid_json_and_compressed_or_oversized_responses_are_safe_failures(self):
        responses = ({"blocks": [b"not-json server-secret"]},
                     {"headers": {"Content-Encoding": "gzip"}},
                     {"blocks": [b"x" * (1024 * 1024 + 1), b"x" * (1024 * 1024)]})
        for values in responses:
            _, mocked = self.transport({}, **values)
            with self.subTest(values=list(values)), mocked, self.assertRaises(ProviderUnavailable) as error:
                rag_embeddings.embed(["Excerpt"])
            self.assertNotIn("server-secret", str(error.exception))

    def test_network_timeout_is_safe_and_requested_budget_must_be_finite(self):
        with patch("integrations.rag_embeddings.httpx.AsyncClient", side_effect=httpx.ReadTimeout("server-secret")):
            with self.assertRaises(ProviderUnavailable) as error:
                rag_embeddings.embed(["Excerpt"])
        self.assertNotIn("server-secret", str(error.exception))
        with patch("integrations.rag_embeddings.httpx.AsyncClient") as client:
            for timeout in (0, -1, True, float("nan"), float("inf"), "15"):
                with self.subTest(timeout=timeout), self.assertRaises(ProviderUnavailable):
                    rag_embeddings.embed(["Excerpt"], timeout=timeout)
            client.assert_not_called()

    def test_stalled_stream_is_cancelled_by_total_embedding_deadline(self):
        class StalledResponse(StubResponse):
            cancelled = False

            async def aiter_raw(self):
                try:
                    yield b"{"
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True
        response = StalledResponse([])
        client = StubClient(response)
        with patch("integrations.rag_embeddings.httpx.AsyncClient", return_value=client), self.assertRaises(ProviderUnavailable):
            rag_embeddings.embed(["Excerpt"], timeout=0.05)
        self.assertTrue(response.cancelled)

