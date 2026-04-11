"""morphism.ai.synthesizer – Async LLM synthesiser backed by Ollama.

Includes the abstract base class, the async Ollama implementation,
and a deterministic mock for offline testing.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional

import aiohttp

from morphism.config import MorphismConfig, config as _default_config
from morphism.core.schemas import Schema
from morphism.exceptions import SynthesisTimeoutError
from morphism.utils.logger import get_logger

_log = get_logger("ai.synthesizer")


# ======================================================================
# Abstract base
# ======================================================================

class LLMSynthesizer(ABC):
    """Abstract base for any LLM backend that generates functor code."""

    @abstractmethod
    async def generate_functor(self, source: Schema, target: Schema) -> str:
        """Return a Python lambda string mapping *source* → *target*."""
        ...


# ======================================================================
# Async Ollama implementation
# ======================================================================

class OllamaSynthesizer(LLMSynthesizer):
    """Queries a local Ollama instance via ``aiohttp`` with exponential
    back-off retry (max 3 network-level retries).
    """

    def __init__(self, cfg: MorphismConfig | None = None) -> None:
        self._cfg: MorphismConfig = cfg or _default_config
        # Base URL without trailing /api/generate – we build the full URL.
        self._url: str = self._cfg.ollama_url
        self._model: str = self._cfg.model_name
        self._timeout: int = self._cfg.llm_request_timeout

    # ------------------------------------------------------------------
    async def generate_functor(self, source: Schema, target: Schema) -> str:
        prompt: str = (
            "You are Morphism, an algebraic code synthesizer. "
            f"Input Schema: name={source.name}, type={source.data_type.__name__}, "
            f"constraints=({source.constraints}). "
            f"Output Schema: name={target.name}, type={target.data_type.__name__}, "
            f"constraints=({target.constraints}). "
            "Write a single Python lambda expression that transforms the Input "
            "into the Output without violating the target bounds. "
            "DO NOT write anything else. NO markdown. NO explanations. "
            "RETURN ONLY THE LAMBDA STRING. "
            "CRITICAL TYPE RULES: If the Input Schema is `JSON_Object` or "
            "`JSON_Array` derived from a native OS command, the input `x` will "
            "be a raw STRING. You MUST explicitly parse it using "
            "`json.loads(x)` inside your lambda. "
            "BAD: `lambda x: x['score'] / 100.0` (This will crash because x "
            "is a string). "
            "GOOD: `lambda x: float(__import__('json').loads(x)['score']) / "
            "100.0`. "
            "You must always ensure the final output matches the Target "
            "Schema's Python type. "
            "Example: lambda x: x / 100.0"
        )
        _log.debug("Prompt: %s", prompt)
        _log.info("Sending synthesis request to %s (%s)…", self._model, self._url)

        payload = {"model": self._model, "prompt": prompt, "stream": False}

        max_retries = 3
        last_exc: BaseException | None = None
        backoff = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self._url, json=payload) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                        raw: str = data["response"]
                        _log.debug("Raw LLM response: %r", raw)
                        clean = self._sanitise(raw)
                        _log.info("Sanitised lambda: %r", clean)
                        return clean
            except (aiohttp.ClientError, TimeoutError, KeyError) as exc:
                last_exc = exc
                _log.warning(
                    "Ollama request failed (attempt %d/%d): %s",
                    attempt, max_retries, exc,
                )
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(backoff)
                    backoff *= 2

        raise SynthesisTimeoutError(
            f"Ollama synthesis failed after {max_retries} retries. "
            f"Last error: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Regex sanitiser
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitise(raw: str) -> str:
        """Extract the first ``lambda …`` expression from *raw*."""
        text: str = re.sub(r"```(?:python)?", "", raw)
        text = text.replace("```", "")
        text = " ".join(text.split())

        idx = text.find("lambda")
        if idx == -1:
            raise ValueError(
                f"Could not extract a lambda from LLM response: {raw!r}"
            )

        tail = text[idx:]

        m: Optional[re.Match[str]] = re.search(
            r"^(lambda\s+[^:]+:\s*.+?)(?:$|\s*```|\s*(?:Output|Example|Explanation)\b|\s*(?:This|The|It|Note|Where|Here)\b)",
            tail,
        )
        candidate = (m.group(1) if m else tail).strip()

        candidate = candidate.strip().strip("`").rstrip(".")
        if (
            (candidate.startswith('"') and candidate.endswith('"'))
            or (candidate.startswith("'") and candidate.endswith("'"))
        ):
            candidate = candidate[1:-1].strip()
        candidate = candidate.strip().strip("`").rstrip('`"\'')

        if not candidate.lstrip().startswith("lambda"):
            raise ValueError(
                f"Could not extract a lambda from LLM response: {raw!r}"
            )
        return candidate


# ======================================================================
# Deterministic mock (offline testing)
# ======================================================================

class MockLLMSynthesizer(LLMSynthesizer):
    """Returns known code strings for pre-defined schema pairs."""

    async def generate_functor(self, source: Schema, target: Schema) -> str:
        if source.name == "Int_0_to_100" and target.name == "Float_Normalized":
            code = "lambda x: x / 100.0"
            _log.info(
                "MockLLM synthesised F(%s -> %s): %s",
                source.name, target.name, code,
            )
            return code

        code = "lambda x: x * 999.0"
        _log.info(
            "MockLLM synthesised (UNSAFE) F(%s -> %s): %s",
            source.name, target.name, code,
        )
        return code
