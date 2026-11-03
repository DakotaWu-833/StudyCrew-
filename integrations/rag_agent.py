"""Model-selected tool calls with bounded, server-owned transport.

This adapter returns data only. The application decides which calls may run.
Ollama's missing call IDs are returned as empty strings for the orchestrator to
assign; compatible services must provide usable call IDs for tool results.
"""
import asyncio
import json
import math
import re

import httpx
from django.conf import settings

from .rag_model import ProviderUnavailable, configuration


MAX_CALLS = 6
MAX_ARGUMENT_BYTES = 8 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_CONTENT_CHARS = 8000
CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def _name(value):
    if not isinstance(value, str) or not TOOL_NAME.fullmatch(value):
        raise ValueError("Invalid tool name")
    return value


def _call_id(value, *, required):
    if not required and value == "":
        return value
    if not isinstance(value, str) or not CALL_ID.fullmatch(value):
        raise ValueError("Invalid tool call ID")
    return value


def _reject_constant(value):
    raise ValueError("Non-finite JSON value")


def _arguments(value, *, encoded=False):
    if encoded:
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise ValueError("Invalid encoded tool arguments")
        value = json.loads(value, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be an object")
    encoded_value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded_value.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ValueError("Tool arguments are too large")
    return value, encoded_value


def _messages(messages, *, compatible):
    if not isinstance(messages, list) or not messages:
        raise ValueError("Messages must be a nonempty list")
    converted = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Invalid message")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Message content must be text")
        row = {"role": message["role"], "content": content}
        calls = message.get("tool_calls", [])
        if not isinstance(calls, list) or len(calls) > MAX_CALLS or (calls and message["role"] != "assistant"):
            raise ValueError("Invalid assistant tool calls")
        if calls:
            converted_calls = []
            seen = set()
            for call in calls:
                if not isinstance(call, dict):
                    raise ValueError("Invalid assistant tool call")
                name = _name(call.get("name"))
                identifier = _call_id(call.get("id", ""), required=compatible)
                if identifier and identifier in seen:
                    raise ValueError("Duplicate tool call ID")
                seen.add(identifier)
                arguments, encoded = _arguments(call.get("arguments"))
                if compatible:
                    converted_calls.append({"id": identifier, "type": "function",
                                            "function": {"name": name, "arguments": encoded}})
                else:
                    converted_calls.append({"function": {"name": name, "arguments": arguments}})
            row["tool_calls"] = converted_calls
        if message["role"] == "tool":
            if compatible:
                row["tool_call_id"] = _call_id(message.get("tool_call_id"), required=True)
            else:
                row["tool_name"] = _name(message.get("tool_name"))
        converted.append(row)
    return converted


def _tools(tools):
    if not isinstance(tools, list):
        raise ValueError("Tools must be a list")
    seen = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError("Invalid tool schema")
        function = tool.get("function")
        if not isinstance(function, dict):
            raise ValueError("Invalid tool function")
        name = _name(function.get("name"))
        if name in seen or not isinstance(function.get("description"), str) or not isinstance(function.get("parameters"), dict):
            raise ValueError("Invalid tool schema")
        seen.add(name)
    return tools


def _response(result, *, compatible):
    if not isinstance(result, dict):
        raise ValueError("Invalid model response")
    if compatible:
        choices = result.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError("Invalid model choices")
        if choices[0].get("finish_reason") not in {None, "stop", "tool_calls"}:
            raise ValueError("Incomplete model response")
        message = choices[0].get("message")
    else:
        if result.get("done") is not True or result.get("done_reason") == "length":
            raise ValueError("Incomplete model response")
        message = result.get("message")
    if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
        raise ValueError("Invalid assistant response")
    calls = message.get("tool_calls", [])
    if calls is None:
        calls = []
    if not isinstance(calls, list) or len(calls) > MAX_CALLS:
        raise ValueError("Invalid tool calls")
    content = message.get("content", "")
    if content is None and calls:
        content = ""
    if not isinstance(content, str) or len(content) > MAX_CONTENT_CHARS:
        raise ValueError("Invalid assistant content")
    canonical = []
    seen = set()
    for call in calls:
        if not isinstance(call, dict) or call.get("type", "function") != "function":
            raise ValueError("Invalid function call")
        function = call.get("function")
        if not isinstance(function, dict):
            raise ValueError("Invalid function")
        identifier = _call_id(call.get("id", ""), required=compatible)
        if identifier and identifier in seen:
            raise ValueError("Duplicate tool call ID")
        seen.add(identifier)
        arguments, _ = _arguments(function.get("arguments"), encoded=compatible)
        canonical.append({"id": identifier, "name": _name(function.get("name")), "arguments": arguments})
    if not content.strip() and not canonical:
        raise ValueError("Empty model response")
    return {"content": content.strip(), "tool_calls": canonical}


def agent_chat(messages, tools, timeout=None):
    """Return canonical assistant content and proposed calls without executing them."""
    config = configuration()
    if not config:
        raise ProviderUnavailable("A model has not been configured.")
    compatible = config["provider"] == "compatible"
    try:
        if timeout is None:
            timeout = config["timeout"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid remaining model deadline")
        timeout = min(timeout, config["timeout"])
        payload = {"model": config["model"], "messages": _messages(messages, compatible=compatible), "stream": False}
        declared_tools = _tools(tools)
        if declared_tools:
            payload["tools"] = declared_tools
        if compatible:
            endpoint = config["base"] + "/chat/completions"
            payload.update(temperature=0, max_tokens=900)
            if declared_tools:
                payload["tool_choice"] = "auto"
        else:
            endpoint = config["base"] + "/api/chat"
            payload["options"] = {"temperature": 0, "num_predict": settings.RAG_MAX_OUTPUT_TOKENS,
                                  "num_ctx": settings.RAG_NUM_CTX}
            payload["keep_alive"] = settings.RAG_KEEP_ALIVE
            if settings.RAG_DISABLE_THINKING:
                payload["think"] = False
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        key = config["key"]
        if key:
            headers["Authorization"] = "Bearer " + key

        async def request():
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                    if response.status_code != 200 or response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise ProviderUnavailable("The model service could not complete the tool request.")
                    body = bytearray()
                    async for block in response.aiter_raw():
                        if len(body) + len(block) > MAX_RESPONSE_BYTES:
                            raise ProviderUnavailable("The model response exceeded its size limit.")
                        body.extend(block)
                    return body

        async def bounded_request():
            return await asyncio.wait_for(request(), timeout=timeout)

        body = asyncio.run(bounded_request())
        return _response(json.loads(body, parse_constant=_reject_constant), compatible=compatible)
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise ProviderUnavailable("The model service is unavailable. Try again later.") from None
