"""Bounded Ollama embedding transport without heavyweight inference dependencies."""

import asyncio
import json
import math

import httpx
from django.conf import settings

from .rag_model import ProviderUnavailable, configuration

MAX_BATCH = 16
MAX_DIMENSIONS = 4096
MAX_TEXT_CHARS = 2000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def dimensions():
    value = getattr(settings, "RAG_EMBEDDING_DIMENSIONS", 1024)
    if type(value) is not int or not 1 <= value <= MAX_DIMENSIONS:
        raise ProviderUnavailable("Configure a supported embedding dimension.")
    return value


def normalize(vector, expected):
    """Reject malformed/non-finite vectors and normalize without numeric overflow."""
    if not isinstance(vector, list) or len(vector) != expected:
        raise ValueError("Invalid embedding dimension")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise ValueError("Invalid embedding value")
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Non-finite embedding value")
    scale = max(abs(value) for value in values)
    if not scale:
        raise ValueError("Zero embedding")
    scaled = [value / scale for value in values]
    norm = math.sqrt(sum(value * value for value in scaled))
    return [value / norm for value in scaled]


def _reject_constant(value):
    raise ValueError("Non-finite embedding JSON")


def embed(texts, timeout=None):
    """Return finite unit vectors; a disabled/misconfigured provider fails safely."""
    try:
        config = configuration()
        model = getattr(settings, "RAG_EMBEDDING_MODEL", "").strip()
        if not config or config["provider"] != "ollama" or not model or len(model) > 160:
            raise ProviderUnavailable("An Ollama embedding model has not been configured.")
        expected = dimensions()
        if not isinstance(texts, list) or not 1 <= len(texts) <= MAX_BATCH:
            raise ValueError("Invalid embedding batch")
        if any(not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT_CHARS for value in texts):
            raise ValueError("Invalid embedding input")
        if timeout is None:
            timeout = config["timeout"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid remaining embedding deadline")
        timeout = min(timeout, config["timeout"], 20)
        payload = {"model": model, "input": texts, "truncate": False, "keep_alive": "5m", "dimensions": expected}
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        key = getattr(settings, "RAG_API_KEY", "")
        if key:
            headers["Authorization"] = "Bearer " + key

        async def request():
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", config["base"] + "/api/embed", json=payload, headers=headers) as response:
                    if response.status_code != 200 or response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise ProviderUnavailable("The embedding service could not complete the request.")
                    body = bytearray()
                    async for block in response.aiter_raw():
                        if len(body) + len(block) > MAX_RESPONSE_BYTES:
                            raise ProviderUnavailable("The embedding response exceeded its size limit.")
                        body.extend(block)
                    return body

        async def bounded_request():
            return await asyncio.wait_for(request(), timeout=timeout)

        body = asyncio.run(bounded_request())
        result = json.loads(body, parse_constant=_reject_constant)
        vectors = result.get("embeddings") if isinstance(result, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError("Invalid embedding result count")
        return [normalize(vector, expected) for vector in vectors]
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        raise ProviderUnavailable("The embedding service is unavailable. Keyword search remains available.") from None

