# llm/base.py
# Abstract base class every LLM provider must implement.
# To add a new LLM: subclass BaseLLM, implement generate(), register in router.py.

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    content: str
    provider: str                       # which LLM actually answered
    model: str                          # exact model name used
    extra: dict = field(default_factory=dict)  # structured data, token counts, etc.


class BaseLLM(ABC):
    """Every LLM provider must implement this interface."""

    provider_name: str = ""   # override in subclass e.g. "groq", "gemini", "hf"
    model_name: str    = ""   # override in subclass

    @abstractmethod
    def generate(self, prompt: str, system: str = "", **kwargs) -> LLMResponse:
        """
        Generate a response from the LLM.

        Args:
            prompt:  The user / RAG prompt (already has context injected).
            system:  Optional system instruction.
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.)

        Returns:
            LLMResponse with at minimum .content filled.

        Raises:
            Exception on unrecoverable errors (router will catch and try next).
        """
        ...

    def health_check(self) -> bool:
        """
        Optional lightweight check (e.g. ping the API).
        Return False to skip this provider at startup.
        Default: always available.
        """
        return True
