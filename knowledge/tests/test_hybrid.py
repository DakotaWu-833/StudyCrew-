"""Semantic retrieval uses synthetic vectors, portable JSON, and current excerpts."""

import hashlib
import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import override_settings
from django.utils import timezone

from api.tests.base import APIDomainTestCase
from integrations.rag_model import ProviderUnavailable
from knowledge import hybrid
from knowledge.models import EmbeddingCache
from knowledge.retrieval import rank as keyword_rank
from projects.models import Project, ProjectMembership


def source(identity, text, title="Assignment brief"):
    return {"kind": "file", "source_id": identity, "title": title, "version": 1,
            "page": None, "excerpt": text, "url": "/private/source/", "locator": "Version 1"}


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    RAG_PROVIDER="ollama", RAG_BASE_URL="http://127.0.0.1:11434", RAG_MODEL="test-chat",
    RAG_RETRIEVAL_MODE="hybrid", RAG_EMBEDDING_MODEL="test-embed", RAG_EMBEDDING_DIMENSIONS=3,
    RAG_EMBEDDING_BATCH_SIZE=16, RAG_EMBEDDING_REVISION="",
)
class HybridRetrievalTests(APIDomainTestCase):
    def retrieve(self, question, rows, limit=5, **kwargs):
        return hybrid.rank(question, rows, limit, self.project.pk, user=self.member, **kwargs)

    def semantic_fixture(self, texts, timeout=None):
        vectors = []
        for text in texts:
            if text.startswith("Instruct:") or "Friday" in text:
                vectors.append([1.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0])
        return vectors

    def test_semantic_synonym_returns_evidence_without_keyword_overlap(self):
        rows = [source("a", "Submission deadline Friday"), source("b", "Database indexing tutorial")]
        question = "When is hand-in due?"
        self.assertEqual(keyword_rank(question, rows, 5), [])
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture):
            selected, warnings = self.retrieve(question, rows)
        self.assertEqual([row["source_id"] for row in selected], ["a"])
        self.assertEqual(selected[0]["citation"], "S1")
        self.assertEqual(warnings, [])

    def test_reciprocal_rank_fusion_combines_keyword_and_semantic_order(self):
        rows = [source("lexical", "deadline " * 12, "Deadline references"),
                source("both", "The deadline is Friday"), source("semantic", "Team photographs")]
        self.assertEqual(keyword_rank("deadline", rows, 5)[0]["source_id"], "lexical")
        def embed(texts, timeout=None):
            return [[1, 0, 0] if text.startswith("Instruct:") or "Friday" in text else
                     [0.4, 1, 0] if "photographs" in text else [0.16, 1, 0] for text in texts]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=embed):
            selected, _ = self.retrieve("deadline", rows)
        self.assertEqual(selected[0]["source_id"], "both")

    def test_warm_cache_embeds_only_query_and_stores_no_source_text(self):
        rows = [source("a", "Submission deadline Friday PRIVATE-TEXT")]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture) as embed:
            self.retrieve("When is hand-in due?", rows)
            embed.reset_mock()
            selected, _ = self.retrieve("When is hand-in due?", rows)
        embed.assert_called_once()
        self.assertTrue(embed.call_args.args[0][0].startswith("Instruct:"))
        stored = list(EmbeddingCache.objects.values())
        self.assertEqual(len(stored), 1)
        self.assertNotIn("PRIVATE-TEXT", json.dumps(stored, default=str))
        self.assertNotIn("Submission deadline", json.dumps(stored, default=str))
        self.assertEqual(len(stored[0]["content_sha256"]), 64)
        self.assertTrue(selected)

    def test_changed_content_gets_new_vector_key_and_old_text_never_returns(self):
        first = [source("a", "Submission deadline Friday old draft")]
        updated = [source("a", "Submission deadline Friday new draft")]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture):
            self.retrieve("When is hand-in due?", first)
            selected, _ = self.retrieve("When is hand-in due?", updated)
        self.assertEqual(EmbeddingCache.objects.count(), 2)
        self.assertNotIn("old draft", json.dumps(selected))
        self.assertIn("new draft", json.dumps(selected))

    def test_cache_isolated_by_model_and_project(self):
        rows = [source("a", "Submission deadline Friday")]
        other = Project.objects.create(name="Other project", created_by=self.member)
        ProjectMembership.objects.create(project=other, user=self.member, role="owner")
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture):
            self.retrieve("When is hand-in due?", rows)
            with override_settings(RAG_EMBEDDING_MODEL="test-embed-v2"):
                self.retrieve("When is hand-in due?", rows)
            hybrid.rank("When is hand-in due?", rows, 5, other.pk, user=self.member)
        self.assertEqual(EmbeddingCache.objects.count(), 3)
        self.assertEqual(EmbeddingCache.objects.filter(project=self.project).count(), 2)
        self.assertEqual(EmbeddingCache.objects.filter(project=other).count(), 1)

    def test_corrupt_cached_vector_is_replaced_before_similarity(self):
        row = source("a", "Submission deadline Friday")
        digest = hashlib.sha256((row["title"] + "\n" + row["excerpt"]).encode()).hexdigest()
        entry = EmbeddingCache.objects.create(project=self.project, model=hybrid.cache_namespace("test-embed", 3), content_sha256=digest, vector=[0, 0, 0])
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture) as embed:
            selected, _ = self.retrieve("When is hand-in due?", [row])
        self.assertEqual(embed.call_count, 2)
        entry.refresh_from_db()
        self.assertEqual(entry.vector, [1, 0, 0])
        self.assertTrue(selected)

    def test_dimension_change_uses_new_namespace_and_reembeds_source(self):
        rows = [source("a", "Submission deadline Friday")]
        def dimension_vectors(texts, timeout=None):
            return [[1] + [0] * (settings.RAG_EMBEDDING_DIMENSIONS - 1) for _ in texts]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=dimension_vectors) as embed:
            self.retrieve("When is hand-in due?", rows)
            first_namespace = hybrid.cache_namespace("test-embed", 3)
            embed.reset_mock()
            with override_settings(RAG_EMBEDDING_DIMENSIONS=2):
                selected, warnings = self.retrieve("When is hand-in due?", rows)
                self.assertEqual(embed.call_count, 2)
                second_namespace = hybrid.cache_namespace("test-embed", 2)
                self.assertNotEqual(first_namespace, second_namespace)
                embed.reset_mock()
                self.retrieve("When is hand-in due?", rows)
                embed.assert_called_once()
        self.assertTrue(selected)
        self.assertEqual(warnings, [])
        self.assertEqual(EmbeddingCache.objects.count(), 2)
        self.assertEqual(set(EmbeddingCache.objects.values_list("model", flat=True)), {first_namespace, second_namespace})

    def test_model_revision_change_reembeds_even_when_tag_and_dimensions_match(self):
        rows = [source("a", "Submission deadline Friday")]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture) as embed:
            self.retrieve("When is hand-in due?", rows)
            # The default unpinned revision is a supported, separate namespace.
            default_namespace = hybrid.cache_namespace("test-embed", 3)
            self.assertTrue(default_namespace.startswith("sha256:"))
            embed.reset_mock()
            with override_settings(RAG_EMBEDDING_REVISION="a" * 64):
                selected, warnings = self.retrieve("When is hand-in due?", rows)
                self.assertEqual(embed.call_count, 2)
                pinned_namespace = hybrid.cache_namespace("test-embed", 3)
                self.assertNotEqual(default_namespace, pinned_namespace)
                embed.reset_mock()
                self.retrieve("When is hand-in due?", rows)
                embed.assert_called_once()
            embed.reset_mock()
            with override_settings(RAG_EMBEDDING_REVISION="b" * 64):
                self.retrieve("When is hand-in due?", rows)
                self.assertEqual(embed.call_count, 2)
                changed_namespace = hybrid.cache_namespace("test-embed", 3)
                self.assertNotEqual(pinned_namespace, changed_namespace)
        self.assertTrue(selected)
        self.assertEqual(warnings, [])
        self.assertEqual(EmbeddingCache.objects.count(), 3)
        self.assertEqual(set(EmbeddingCache.objects.values_list("model", flat=True)), {default_namespace, pinned_namespace, changed_namespace})

    def test_embedding_batch_size_is_bounded_and_duplicate_content_reused(self):
        rows = [source(str(index), "Submission deadline Friday " + str(index)) for index in range(3)]
        rows.append({**rows[0], "source_id": "same-content"})
        with override_settings(RAG_EMBEDDING_BATCH_SIZE=2), patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture) as embed:
            self.retrieve("When is hand-in due?", rows)
        self.assertEqual([len(call.args[0]) for call in embed.call_args_list], [2, 1, 1])
        self.assertEqual(EmbeddingCache.objects.count(), 3)

    def test_keyword_mode_skips_model_and_cache(self):
        rows = [source("a", "Submission deadline Friday")]
        with override_settings(RAG_RETRIEVAL_MODE="bm25"), patch("knowledge.hybrid.rag_embeddings.embed") as embed:
            selected, warnings = self.retrieve("deadline", rows)
        embed.assert_not_called()
        self.assertEqual(warnings, [])
        self.assertEqual(selected, keyword_rank("deadline", rows, 5))
        self.assertEqual(EmbeddingCache.objects.count(), 0)

    def test_provider_failure_falls_back_explicitly_to_keyword_evidence(self):
        rows = [source("a", "Submission deadline Friday")]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=ProviderUnavailable("server-secret")):
            selected, warnings = self.retrieve("deadline", rows)
        self.assertEqual(selected, keyword_rank("deadline", rows, 5))
        self.assertTrue(warnings)
        self.assertNotIn("server-secret", json.dumps(warnings))
        self.assertEqual(EmbeddingCache.objects.count(), 0)

    def test_disabled_provider_has_no_http_egress_and_keyword_fallback(self):
        rows = [source("a", "Submission deadline Friday")]
        with override_settings(RAG_PROVIDER="disabled"), patch("integrations.rag_embeddings.httpx.AsyncClient") as client:
            selected, warnings = self.retrieve("deadline", rows)
        client.assert_not_called()
        self.assertEqual(selected, keyword_rank("deadline", rows, 5))
        self.assertTrue(warnings)

    def test_invalid_model_vectors_never_poison_cache(self):
        row = source("a", "Submission deadline Friday")
        for vectors in ([[[True, 0, 1]]], [[[float("nan"), 0, 1]]], [[[0, 0, 0]]], [[[1, 0]]], [[]]):
            with self.subTest(vectors=vectors), patch("knowledge.hybrid.rag_embeddings.embed", side_effect=vectors):
                selected, warnings = self.retrieve("deadline", [row])
                self.assertEqual(selected, keyword_rank("deadline", [row], 5))
                self.assertTrue(warnings)
                self.assertEqual(EmbeddingCache.objects.count(), 0)

    def test_candidate_cap_warns_and_preserves_keyword_search_of_remaining_rows(self):
        rows = [source(str(index), "Submission deadline Friday " + str(index)) for index in range(200)]
        rows.append(source("tail", "Specialtail evidence appears here"))
        with patch("knowledge.hybrid.rag_embeddings.embed", return_value=[[1, 0, 0]]) as embed:
            # A deterministic per-batch response with the same number of vectors.
            embed.side_effect = lambda texts, timeout=None: [[0, 1, 0] if not text.startswith("Instruct:") else [1, 0, 0] for text in texts]
            selected, warnings = self.retrieve("Specialtail", rows)
        self.assertEqual([row["source_id"] for row in selected], ["tail"])
        self.assertTrue(warnings)
        self.assertEqual(EmbeddingCache.objects.count(), 200)
        self.assertTrue(all(len(call.args[0]) <= 16 for call in embed.call_args_list))

    def test_deadline_fallback_does_not_cache_late_response_or_call_query(self):
        row = source("a", "Submission deadline Friday")
        clock = [0.0]
        def late(texts, timeout=None):
            clock[0] = 9.0
            return [[1, 0, 0] for text in texts]
        with patch("knowledge.hybrid.time.monotonic", side_effect=lambda: clock[0]), patch("knowledge.hybrid.rag_embeddings.embed", side_effect=late) as embed:
            selected, warnings = self.retrieve("deadline", [row], timeout_seconds=8)
        self.assertEqual(embed.call_count, 1)
        self.assertEqual(EmbeddingCache.objects.count(), 0)
        self.assertEqual(selected, keyword_rank("deadline", [row], 5))
        self.assertTrue(warnings)

    def test_revoked_membership_before_embedding_has_no_egress(self):
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        with patch("knowledge.hybrid.rag_embeddings.embed") as embed, self.assertRaises(Http404):
            self.retrieve("deadline", [source("a", "Submission deadline Friday")])
        embed.assert_not_called()

    def test_account_revocation_during_embedding_prevents_cache_and_next_egress(self):
        def revoked(texts, timeout=None):
            get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
            return [[1, 0, 0] for text in texts]
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=revoked) as embed, self.assertRaises(Http404):
            self.retrieve("deadline", [source("a", "Submission deadline Friday")])
        self.assertEqual(embed.call_count, 1)
        self.assertEqual(EmbeddingCache.objects.count(), 0)

    def test_diverse_sources_and_final_citation_labels_are_preserved(self):
        rows = [source("one", "Submission deadline Friday " + str(index)) for index in range(4)]
        rows.append(source("two", "Submission deadline Friday second file"))
        with patch("knowledge.hybrid.rag_embeddings.embed", side_effect=self.semantic_fixture):
            selected, _ = self.retrieve("deadline", rows, limit=4)
        self.assertEqual(len(selected), 3)
        self.assertEqual([row["citation"] for row in selected], ["S1", "S2", "S3"])
        self.assertEqual(sum(row["source_id"] == "one" for row in selected), 2)

