# llm/hf_client.py
# Mode: FALLBACK — used when Groq and Gemini are unavailable.
# Uses HuggingFace Inference API (serverless, OpenAI-compatible chat endpoint).
# Model: Qwen/Qwen2.5-Coder-32B-Instruct (strong, free tier).

import os
import requests
from .base import BaseLLM, LLMResponse

_MODEL      = "meta-llama/Llama-3.1-8B-Instruct"
_HF_API_URL = "https://router.huggingface.co/v1/chat/completions"
_TIMEOUT    = 60  # seconds


class HuggingFaceLLM(BaseLLM):
    provider_name = "huggingface"
    model_name    = _MODEL

    def __init__(self):
        token = os.getenv("HF_TOKEN")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._headers["Content-Type"] = "application/json"

    def generate(self, prompt: str, system: str = "", **kwargs) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": _MODEL,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 512),
            "temperature": kwargs.get("temperature", 0.3),
        }

        resp = requests.post(
            _HF_API_URL,
            headers=self._headers,
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data    = resp.json()
        content = data["choices"][0]["message"]["content"]

        return LLMResponse(
            content=content.strip(),
            provider=self.provider_name,
            model=self.model_name,
        )

    def health_check(self) -> bool:
        return bool(os.getenv("HF_TOKEN"))
