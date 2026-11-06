"""Small OpenAI-compatible DeepSeek vision/function-calling adapter.

No request is sent merely by importing this module. Callers must pass
allow_network=True, which makes paid API use an explicit runtime decision.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .api_config import resolve_base_url


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_seconds: float = 45.0
    retries: int = 2

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set; baseline mode remains available.")
        return cls(key, resolve_base_url(os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")),
                   os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))


class DeepSeekClient:
    def __init__(self, settings: DeepSeekSettings, *, allow_network: bool = False) -> None:
        self.settings, self.allow_network = settings, allow_network
        self.usage: list[dict[str, Any]] = []

    def _client(self) -> Any:
        if not self.allow_network:
            raise RuntimeError("API use is disabled. Re-run only after approval with --allow-api.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is unavailable in the selected Python environment.") from exc
        return OpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url,
                      timeout=self.settings.timeout_seconds, max_retries=0)

    def complete(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> Any:
        client, error = self._client(), None
        for attempt in range(self.settings.retries + 1):
            try:
                response = client.chat.completions.create(model=self.settings.model, messages=messages, tools=tools)
                usage = getattr(response, "usage", None)
                self.usage.append({"attempt": attempt + 1, "model": self.settings.model,
                                   "prompt_tokens": getattr(usage, "prompt_tokens", None),
                                   "completion_tokens": getattr(usage, "completion_tokens", None),
                                   "total_tokens": getattr(usage, "total_tokens", None)})
                return response
            except Exception as exc:  # retained only as a safe final error below
                error = exc
                status = getattr(exc, "status_code", None)
                retryable = not (isinstance(status, int) and 400 <= status < 500 and status not in {408, 409, 429})
                if attempt < self.settings.retries and retryable:
                    time.sleep(1.0 * (2**attempt))
                else:
                    break
        status = getattr(error, "status_code", None)
        detail = f" (HTTP {status})" if isinstance(status, int) else ""
        raise RuntimeError(f"DeepSeek request failed after {attempt + 1} attempts{detail}: {type(error).__name__}")

    @staticmethod
    def image_part(path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix)
        if not mime:
            raise ValueError(f"Unsupported image format: {path}")
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload}"}}

    def inspect_frames(self, frames: Iterable[Path], prompt: str) -> Any:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(self.image_part(p) for p in frames)
        return self.complete([{"role": "user", "content": content}])
