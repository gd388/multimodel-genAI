# llm/router.py
# Central routing layer. Picks the right LLM by mode, falls back on failure.
#
# ── How to add a new LLM provider ────────────────────────────────────────────
#  1. Create llm/your_client.py — subclass BaseLLM, implement generate()
#  2. Add it to REGISTRY below with a unique key
#  3. Add the key to ROUTE_ORDER for the mode(s) it should serve
#  That's it — zero other changes needed.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import logging
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING

from .base import BaseLLM, LLMResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Available modes ───────────────────────────────────────────────────────────

class QueryMode(str, Enum):
    GROQ   = "groq"     # user picks Groq → fast latency, HF fallback
    GEMINI = "gemini"   # user picks Gemini → structured/quality, HF fallback


# ── Provider registry ─────────────────────────────────────────────────────────
# Add new providers here only. Order inside ROUTE_ORDER controls priority.

def _build_registry() -> dict[str, BaseLLM]:
    """
    Lazily instantiate providers. If a key is missing (no API key) the
    health_check will return False and the router skips it automatically.
    """
    from .groq_client    import GroqLLM
    from .gemini_client  import GeminiLLM
    from .hf_client      import HuggingFaceLLM

    providers: dict[str, BaseLLM] = {
        "groq":    GroqLLM(),
        "gemini":  GeminiLLM(),
        "hf":      HuggingFaceLLM(),
        # ← add new providers here: "openai": OpenAILLM(), etc.
    }
    return {k: v for k, v in providers.items() if v.health_check()}


# Priority order per mode. User picks primary; HF is always the silent fallback.
ROUTE_ORDER: dict[QueryMode, list[str]] = {
    QueryMode.GROQ:   ["groq",   "hf"],
    QueryMode.GEMINI: ["gemini", "hf"],
    # ← add new modes here if needed
}


# ── Router class ──────────────────────────────────────────────────────────────

class LLMRouter:
    def __init__(self):
        self._registry: dict[str, BaseLLM] = _build_registry()
        alive = list(self._registry.keys())
        logger.info(f"[LLMRouter] Available providers: {alive}")

    def generate(
        self,
        prompt:  str,
        mode:    QueryMode = QueryMode.GROQ,
        system:  str = "",
        **kwargs,
    ) -> LLMResponse:
        """
        Route to the best provider for the given mode.
        Automatically falls back to the next provider on any exception.

        Args:
            prompt:  The user prompt (with RAG context already injected).
            mode:    Routing mode — FAST | STRUCTURED | FALLBACK
            system:  Optional system message.
            **kwargs: Passed through to the provider (temperature, max_tokens, json_mode…)

        Returns:
            LLMResponse from whichever provider succeeded.

        Raises:
            RuntimeError if ALL providers in the chain fail.
        """
        chain  = ROUTE_ORDER.get(mode, ROUTE_ORDER[QueryMode.GROQ])
        errors = {}

        for key in chain:
            provider = self._registry.get(key)
            if provider is None:
                logger.debug(f"[LLMRouter] '{key}' not available — skipping")
                continue
            try:
                logger.info(f"[LLMRouter] Trying '{key}' (mode={mode})")
                result = provider.generate(prompt, system=system, **kwargs)
                logger.info(f"[LLMRouter] '{key}' succeeded")
                return result
            except Exception as e:
                logger.warning(f"[LLMRouter] '{key}' failed: {e}")
                errors[key] = str(e)

        raise RuntimeError(
            f"All LLM providers failed for mode '{mode}'. Errors: {errors}"
        )

    @property
    def available_providers(self) -> list[str]:
        return list(self._registry.keys())


@lru_cache(maxsize=1)
def get_router() -> LLMRouter:
    """Singleton — instantiated once at startup, reused across requests."""
    return LLMRouter()
