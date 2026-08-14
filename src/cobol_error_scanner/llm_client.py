"""Shared chat-completion client for OpenAI and Ollama providers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

LLM_PROVIDERS = frozenset({"heuristic", "openai", "ollama"})
LLM_BACKEND_PROVIDERS = frozenset({"openai", "ollama"})

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def chat_completion(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    api_key_env: str = "OPENAI_API_KEY",
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    temperature: float = 0.2,
    timeout: float = 120.0,
) -> str | None:
    """Return assistant text, or None when the provider is unavailable."""
    if provider == "openai":
        return _chat_openai(
            model=model,
            messages=messages,
            api_key_env=api_key_env,
            temperature=temperature,
        )
    if provider == "ollama":
        return _chat_ollama(
            model=model,
            messages=messages,
            base_url=base_url,
            temperature=temperature,
            timeout=timeout,
        )
    return None


def _chat_openai(
    *,
    model: str,
    messages: list[dict[str, str]],
    api_key_env: str,
    temperature: float,
) -> str | None:
    if not os.environ.get(api_key_env):
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return (response.choices[0].message.content or "").strip() or None


def _chat_ollama(
    *,
    model: str,
    messages: list[dict[str, str]],
    base_url: str,
    temperature: float,
    timeout: float,
) -> str | None:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        return None

    message = body.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str):
        return None
    text = content.strip()
    return text or None
