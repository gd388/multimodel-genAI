# llm/gemini_client.py
# Mode: STRUCTURED — best for JSON/structured output extraction from documents.
# Model: gemini-2.0-flash-lite (fast + strong instruction following for structured tasks).

import json
import os
import google.generativeai as genai
from .base import BaseLLM, LLMResponse


class GeminiLLM(BaseLLM):
    provider_name = "gemini"
    model_name    = "gemini-2.0-flash-lite"

    def __init__(self):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self._model = genai.GenerativeModel(self.model_name)

    def generate(self, prompt: str, system: str = "", **kwargs) -> LLMResponse:
        # Gemini combines system + user into a single prompt
        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        generation_config = genai.types.GenerationConfig(
            temperature=kwargs.get("temperature", 0.1),
            max_output_tokens=kwargs.get("max_tokens", 1024),
        )

        # If caller requests JSON output, tell Gemini explicitly
        if kwargs.get("json_mode"):
            generation_config.response_mime_type = "application/json"

        resp = self._model.generate_content(
            full_prompt,
            generation_config=generation_config,
        )

        content = resp.text

        # Auto-parse JSON if json_mode was requested
        extra: dict = {}
        if kwargs.get("json_mode"):
            try:
                extra["parsed"] = json.loads(content)
            except json.JSONDecodeError:
                pass

        return LLMResponse(
            content=content,
            provider=self.provider_name,
            model=self.model_name,
            extra=extra,
        )

    def health_check(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))
