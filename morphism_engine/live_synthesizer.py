"""live_synthesizer.py – Local LLM integration via Ollama for live functor synthesis."""

from __future__ import annotations

import re
from typing import Optional

import requests

from morphism_engine.schemas import Schema
from morphism_engine.synthesizer import LLMSynthesizer


class OllamaSynthesizer(LLMSynthesizer):
    """A concrete :class:`LLMSynthesizer` that queries a locally-running
    `Ollama <https://ollama.com>`_ instance for functor code generation.

    The generated text is aggressively sanitised via regex to extract
    *only* the Python lambda expression, rejecting markdown fences,
    explanatory prose, and any other noise the model may emit.

    Parameters
    ----------
    base_url:
        The Ollama HTTP API base (default ``http://localhost:11434``).
    model_name:
        The model tag to use (default ``qwen2.5-coder:1.5b``).
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_name: str = "qwen2.5-coder:1.5b",
        timeout: int = 60,
    ) -> None:
        self.base_url: str = base_url.rstrip("/")
        self.model_name: str = model_name
        self.timeout: int = timeout

    # ------------------------------------------------------------------
    # LLMSynthesizer interface
    # ------------------------------------------------------------------
    def generate_functor(self, source: Schema, target: Schema) -> str:  # type: ignore[override]
        """Hit the local Ollama ``/api/generate`` endpoint and return a
        sanitised Python lambda string."""

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
            "Example: lambda x: x / 100.0"
        )

        print(f"[OllamaSynthesizer] Sending prompt to {self.model_name}…")

        payload: dict = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
        }

        resp = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        raw_response: str = resp.json()["response"]
        print(f"[OllamaSynthesizer] Raw LLM response: {raw_response!r}")

        clean: str = self._sanitise(raw_response)
        print(f"[OllamaSynthesizer] Sanitised lambda: {clean!r}")
        return clean

    # ------------------------------------------------------------------
    # Regex sanitiser
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitise(raw: str) -> str:
        """Extract the first ``lambda …`` expression from *raw*,
        stripping markdown fences and conversational noise.

        Returns the bare lambda string (e.g. ``"lambda x: x / 100.0"``).

        Raises ``ValueError`` if no lambda can be found.
        """
        # 1. Strip markdown code fences
        text: str = re.sub(r"```(?:python)?", "", raw)
        text = text.replace("```", "")

        # 2. Collapse whitespace to a single line
        text = " ".join(text.split())

        # 3. Locate the first lambda and take a reasonable slice
        idx = text.find("lambda")
        if idx == -1:
            raise ValueError(
                f"[OllamaSynthesizer] Could not extract a lambda from LLM response: {raw!r}"
            )

        tail = text[idx:]

        # 4. Prefer a conservative match: "lambda <params>: <expr>"
        #    Stop at common delimiters the model might append.
        m: Optional[re.Match[str]] = re.search(
            r"^(lambda\s+[^:]+:\s*.+?)(?:$|\s*```|\s*(?:Output|Example|Explanation)\b|\s*(?:This|The|It|Note|Where|Here)\b)",
            tail,
        )
        candidate = (m.group(1) if m else tail).strip()

        # 5. Remove surrounding quotes/backticks and trailing punctuation.
        candidate = candidate.strip().strip("`")
        candidate = candidate.rstrip(".")
        if (
            (candidate.startswith("\"") and candidate.endswith("\""))
            or (candidate.startswith("'") and candidate.endswith("'"))
        ):
            candidate = candidate[1:-1].strip()
        candidate = candidate.strip().strip("`")
        candidate = candidate.rstrip("`\"'")

        # 6. Final validation: must start with "lambda"
        if not candidate.lstrip().startswith("lambda"):
            raise ValueError(
                f"[OllamaSynthesizer] Could not extract a lambda from LLM response: {raw!r}"
            )

        return candidate
