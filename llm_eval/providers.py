from __future__ import annotations

import time
from collections.abc import Callable
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import PermanentProviderError, ProviderConfigurationError, TransientProviderError
from .models import ProviderResponse


class Provider:
    """Provider port. Adapters implement this method for OpenAI, Anthropic, etc."""

    def complete(self, prompt: str, params: dict, seed: int | None = None) -> ProviderResponse:
        raise NotImplementedError


class CallableProvider(Provider):
    def __init__(self, fn: Callable[[str, dict, int | None], str | ProviderResponse]): self.fn = fn

    def complete(self, prompt: str, params: dict, seed: int | None = None) -> ProviderResponse:
        started = time.perf_counter()
        result = self.fn(prompt, params, seed)
        if isinstance(result, ProviderResponse): return result
        return ProviderResponse(str(result), latency_ms=(time.perf_counter() - started) * 1000)


class FixtureProvider(Provider):
    """Offline adapter useful for examples and deterministic CI tests."""
    def __init__(self, responses: dict[str, str]): self.responses = responses

    def complete(self, prompt: str, params: dict, seed: int | None = None) -> ProviderResponse:
        if prompt not in self.responses: raise PermanentProviderError(f"no fixture for prompt: {prompt}")
        return ProviderResponse(self.responses[prompt])


class OpenAICompatibleProvider(Provider):
    """Credential-aware adapter for OpenAI-compatible chat-completion endpoints.

    The transport is injectable so tests and demos never need network access. The
    default transport uses urllib and is only invoked when a caller explicitly
    configures and uses this adapter.
    """

    def __init__(self, endpoint: str, *, api_key: str | None = None,
                 api_key_env: str = "LLM_EVAL_API_KEY", timeout_seconds: float = 30,
                 model: str | None = None,
                 transport: Callable[[Request, float], Any] | None = None):
        if not endpoint: raise ProviderConfigurationError("provider endpoint is required")
        self.endpoint = endpoint
        self.api_key = api_key or os.getenv(api_key_env)
        self.timeout_seconds, self.model = timeout_seconds, model
        self.transport = transport or self._urlopen_transport

    @staticmethod
    def _urlopen_transport(request: Request, timeout: float):
        return urlopen(request, timeout=timeout)

    def complete(self, prompt: str, params: dict, seed: int | None = None) -> ProviderResponse:
        payload = {"messages": [{"role": "user", "content": prompt}], **params}
        if self.model and "model" not in payload: payload["model"] = self.model
        if seed is not None: payload.setdefault("seed", seed)
        headers = {"Content-Type": "application/json"}
        if self.api_key: headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with self.transport(request, self.timeout_seconds) as response:
                body = json.loads(response.read().decode())
        except HTTPError as exc:
            if exc.code == 429 or exc.code >= 500: raise TransientProviderError(f"provider HTTP {exc.code}") from exc
            raise PermanentProviderError(f"provider HTTP {exc.code}") from exc
        except (TimeoutError, URLError) as exc:
            raise TransientProviderError(f"provider transport failure: {exc}") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PermanentProviderError(f"invalid provider response: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PermanentProviderError("provider response lacks choices[0].message.content") from exc
        return ProviderResponse(str(content), raw=body, latency_ms=(time.perf_counter() - started) * 1000,
                                usage=body.get("usage", {}))
