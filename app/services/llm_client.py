from __future__ import annotations

import json
from urllib import request
from urllib.error import HTTPError, URLError

from app.core.config import settings


class LLMProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _http_post(url: str, payload: dict, headers: dict[str, str]) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise LLMProviderError("llm_auth_failed", "LLM provider rejected the credentials.") from exc
        raise LLMProviderError("llm_http_error", f"LLM provider returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise LLMProviderError("llm_connection_error", "Failed to connect to the configured LLM provider.") from exc


def generate_llm_text(system_prompt: str, user_prompt: str) -> str:
    provider = settings.effective_llm_provider
    if provider == "openai":
        payload = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        response = _http_post(
            f"{settings.openai_base_url.rstrip('/')}/v1/chat/completions",
            payload,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.openai_api_key}",
            },
        )
        return response["choices"][0]["message"]["content"]

    if provider == "ollama":
        payload = {
            "model": settings.ollama_model,
            "prompt": f"{system_prompt}\n\n{user_prompt}",
            "stream": False,
        }
        response = _http_post(
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
            payload,
            {"Content-Type": "application/json"},
        )
        return response.get("response", "")

    raise LLMProviderError("llm_provider_not_supported", "Unsupported LLM provider.")
