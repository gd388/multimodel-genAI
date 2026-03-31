# llm/groq_client.py
# Mode: FAST — lowest latency, ideal for real-time Q&A.
# Model: llama-3.3-70b-versatile (best quality on Groq's infrastructure).

import os
from groq import Groq
from .base import BaseLLM, LLMResponse


class GroqLLM(BaseLLM):
    provider_name = "groq"
    model_name    = "llama-3.3-70b-versatile"

    def __init__(self):
        self._client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def generate(self, prompt: str, system: str = "", **kwargs) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self._client.chat.completions.create(
            model=kwargs.get("model", self.model_name),
            messages=messages,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", 1024),
        )
        return LLMResponse(
            content=resp.choices[0].message.content,
            provider=self.provider_name,
            model=resp.model,
            extra={"usage": dict(resp.usage)},
        )

    def health_check(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))
