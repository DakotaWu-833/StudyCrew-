"""BM25 plus exact cosine similarity over current authorized project excerpts."""

from collections import Counter
import hashlib
import math
import time

from django.conf import settings
from django.db import DatabaseError

from integrations import rag_embeddings
from .models import EmbeddingCache
from .policies import require_project
from .retrieval import rank as keyword_rank

MAX_CANDIDATES = 200
MAX_TEXT_CHARS = 900
MIN_COSINE = 0.15
FUSION_CONSTANT = 60
FALLBACK_WARNING = "Semantic search is unavailable or reached its time limit. Results use keyword search."


def cache_namespace(model, dimensions):
    revision = getattr(settings, "RAG_EMBEDDING_REVISION", "")
    value = f"{model}\n{dimensions}\n{revision}".encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _text(row):
    return (row["title"] + "\n" + row["excerpt"])[:MAX_TEXT_CHARS]


def _key(row):
    return (row["kind"], row["source_id"], row.get("version"), row.get("page"), row["title"], row["excerpt"])


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise rag_embeddings.ProviderUnavailable("Embedding deadline reached")
    return value


def _embed(texts, deadline, user, project_id, check_current):
    if user is not None:
        require_project(user, project_id)
    if check_current:
        check_current()
    response = rag_embeddings.embed(texts, timeout=_remaining(deadline))
    if user is not None:
        require_project(user, project_id)
    if check_current:
        check_current()
    _remaining(deadline)
    return response


def rank(question, rows, limit, project_id, timeout_seconds=8, *, user=None, check_current=None):
    """Return source rows with fresh citation labels and explicit fallback warnings."""
    if user is not None:
        require_project(user, project_id)
    lexical = keyword_rank(question, rows, limit)
    if not rows or getattr(settings, "RAG_RETRIEVAL_MODE", "bm25") != "hybrid":
        return lexical, []
    warnings = []
    if len(rows) > MAX_CANDIDATES:
        warnings.append("Semantic search covered only the first 200 current excerpts; keyword search covered the remaining material.")
    try:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise rag_embeddings.ProviderUnavailable("Invalid embedding budget")
        deadline = time.monotonic() + timeout_seconds
        model = getattr(settings, "RAG_EMBEDDING_MODEL", "").strip()
        if not model or len(model) > 160:
            raise rag_embeddings.ProviderUnavailable("Embedding model not configured")
        expected = rag_embeddings.dimensions()
        namespace = cache_namespace(model, expected)
        batch_size = getattr(settings, "RAG_EMBEDDING_BATCH_SIZE", 16)
        if type(batch_size) is not int or not 1 <= batch_size <= rag_embeddings.MAX_BATCH:
            raise rag_embeddings.ProviderUnavailable("Invalid embedding batch size")
        candidates = rows[:MAX_CANDIDATES]
        texts = [_text(row) for row in candidates]
        hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        cached = {row.content_sha256: row for row in EmbeddingCache.objects.filter(project_id=project_id, model=namespace, content_sha256__in=hashes)}
        vectors = {}
        for digest, entry in cached.items():
            try:
                vectors[digest] = rag_embeddings.normalize(entry.vector, expected)
            except (ValueError, OverflowError):
                # A corrupt or dimension-obsolete cache entry is replaced from the model.
                continue
        missing = list(dict.fromkeys(digest for digest in hashes if digest not in vectors))
        text_by_hash = dict(zip(hashes, texts))
        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            result = _embed([text_by_hash[digest] for digest in batch], deadline, user, project_id, check_current)
            if len(result) != len(batch):
                raise rag_embeddings.ProviderUnavailable("Embedding result count mismatch")
            normalized = [rag_embeddings.normalize(vector, expected) for vector in result]
            _remaining(deadline)
            for digest, vector in zip(batch, normalized):
                EmbeddingCache.objects.update_or_create(project_id=project_id, model=namespace, content_sha256=digest, defaults={"vector": vector})
                vectors[digest] = vector
        query = "Instruct: Retrieve project evidence relevant to the question.\nQuery: " + question
        response = _embed([query], deadline, user, project_id, check_current)
        if len(response) != 1:
            raise rag_embeddings.ProviderUnavailable("Invalid query embedding")
        query_vector = rag_embeddings.normalize(response[0], expected)
        _remaining(deadline)
        semantic = []
        for index, digest in enumerate(hashes):
            cosine = sum(left * right for left, right in zip(query_vector, vectors[digest]))
            if cosine > MIN_COSINE:
                semantic.append((cosine, index))
        semantic.sort(key=lambda value: (-value[0], value[1]))
        lexical_all = keyword_rank(question, rows, len(rows))
        identities = {_key(row): index for index, row in enumerate(rows)}
        fused = Counter()
        for position, row in enumerate(lexical_all, 1):
            fused[identities[_key(row)]] += 1 / (FUSION_CONSTANT + position)
        for position, (_, index) in enumerate(semantic, 1):
            fused[index] += 1 / (FUSION_CONSTANT + position)
        counts = Counter()
        selected = []
        for index in sorted(fused, key=lambda index: (-fused[index], index)):
            row = rows[index]
            source = (row["kind"], row["source_id"])
            if counts[source] >= 2:
                continue
            counts[source] += 1
            selected.append({**row, "citation": f"S{len(selected) + 1}"})
            if len(selected) >= limit:
                break
        return selected, warnings
    except (rag_embeddings.ProviderUnavailable, DatabaseError, ValueError, TypeError, OverflowError):
        return lexical, warnings + [FALLBACK_WARNING]
