"""pipeline.py – MorphismPipeline: compose FunctorNodes with type-safety.

Phase 4 additions:
    * ``llm_client`` attribute for injecting an LLM synthesizer.
    * ``_resolve_mismatch()`` – synthesis → compile → Z3 verify → inject.
    * ``ProofFailedHalt`` exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

from morphism_engine.node import FunctorNode

if TYPE_CHECKING:
    from morphism_engine.synthesizer import LLMSynthesizer


# ======================================================================
# Custom Exceptions
# ======================================================================

class TypeMismatchHalt(Exception):
    """Raised when a newly appended node's input_schema does not match
    the current tail's output_schema – a category-theoretic composition
    failure (and no LLM client is available to heal it)."""


class ProofFailedHalt(Exception):
    """Raised when the LLM-synthesised functor **fails** Z3 verification.
    The pipeline remains safely halted and unlinked."""


# ======================================================================
# Pipeline (Doubly Linked List of FunctorNodes)
# ======================================================================

@dataclass
class MorphismPipeline:
    """A type-safe, doubly-linked pipeline of ``FunctorNode`` objects.

    Schema compatibility is enforced on every ``append``.  When an
    ``llm_client`` is provided, mismatches trigger autonomous synthesis,
    formal verification, and bridge-node injection.  Without an LLM
    client the original ``TypeMismatchHalt`` behaviour is preserved.
    """

    head: Optional[FunctorNode] = field(default=None, repr=False)
    tail: Optional[FunctorNode] = field(default=None, repr=False)
    current_context: Optional[FunctorNode] = field(default=None, repr=False)
    length: int = 0
    llm_client: Optional["LLMSynthesizer"] = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------
    def append(self, new_node: FunctorNode) -> bool:
        """Append *new_node* to the pipeline.

        Returns ``True`` on success.

        If schemas mismatch **and** an ``llm_client`` is available, the
        pipeline attempts autonomous self-healing via
        ``_resolve_mismatch()``.  On success a bridge ``FunctorNode`` is
        injected between the current tail and *new_node*.

        Raises
        ------
        TypeMismatchHalt
            When schemas mismatch and no ``llm_client`` is configured.
        ProofFailedHalt
            When the synthesised functor fails Z3 verification.
        """
        if self.tail is not None:
            if self.tail.output_schema != new_node.input_schema:
                if self.llm_client is not None:
                    # ── Self-healing path ──────────────────────────
                    bridge: FunctorNode = self._resolve_mismatch(
                        self.tail, new_node,
                    )
                    # Link tail → bridge
                    self.tail.next = bridge
                    bridge.prev = self.tail
                    self.tail = bridge
                    self.length += 1

                    # Link bridge → new_node
                    self.tail.next = new_node
                    new_node.prev = self.tail
                    self.tail = new_node
                    self.length += 1
                    return True
                else:
                    # ── Legacy halt path (no LLM) ─────────────────
                    msg = (
                        f"[Morphism] TYPE MISMATCH HALT: Cannot pipe "
                        f"{self.tail} to {new_node}"
                    )
                    print(msg)
                    raise TypeMismatchHalt(msg)

            # ── Compatible schemas – normal link ──────────────────
            self.tail.next = new_node
            new_node.prev = self.tail
            self.tail = new_node
        else:
            # First node – initialise head / tail / context
            self.head = new_node
            self.tail = new_node
            self.current_context = new_node

        self.length += 1
        return True

    # ------------------------------------------------------------------
    # Self-healing: synthesis → compile → verify → inject
    # ------------------------------------------------------------------
    def _resolve_mismatch(
        self,
        node_a: FunctorNode,
        node_b: FunctorNode,
    ) -> FunctorNode:
        """Attempt to bridge *node_a* → *node_b* via the LLM client.

        1. **Synthesis** – ask the LLM for a lambda string.
        2. **Compilation** – ``eval()`` the string into a ``Callable``.
        3. **Verification** – prove the mapping safe via Z3.
        4. **Injection** – return a new ``FunctorNode`` (the bridge).

        Raises ``ProofFailedHalt`` if Z3 rejects the generated code.
        """
        assert self.llm_client is not None

        src_schema = node_a.output_schema
        tgt_schema = node_b.input_schema

        from morphism_engine.z3_verifier import verify_functor_mapping

        max_attempts = 6
        last_error: Optional[BaseException] = None

        for attempt in range(1, max_attempts + 1):
            # 1. Synthesis
            code_str: str = self.llm_client.generate_functor(src_schema, tgt_schema)
            print(
                f"[Morphism] LLM Synthesising Functor "
                f"F({src_schema.name} -> {tgt_schema.name})… "
                f"(attempt {attempt}/{max_attempts})"
            )

            # 2. Compilation (in-memory, no filesystem artefacts)
            try:
                func: Callable[[Any], Any] = eval(code_str)  # noqa: S307
            except Exception as exc:  # pragma: no cover
                last_error = exc
                print(f"[Morphism] Rejecting functor (compile failed): {exc}")
                continue
            print(f"[Morphism] Compiled functor: {code_str}")

            # 3. Formal verification (sound symbolic check when code_str provided)
            try:
                is_safe: bool = verify_functor_mapping(
                    src_schema,
                    tgt_schema,
                    func,
                    code_str=code_str,
                )
            except Exception as exc:  # pragma: no cover
                last_error = exc
                print(f"[Morphism] Rejecting functor (verifier error): {exc}")
                continue

            if not is_safe:
                last_error = ProofFailedHalt("Z3 rejected functor")
                continue

            # 3b. MVP semantic guardrails for the canonical normalization demo
            if src_schema.name == "Int_0_to_100" and tgt_schema.name == "Float_Normalized":
                try:
                    y0 = float(func(0))
                    y50 = float(func(50))
                    y100 = float(func(100))
                except Exception as exc:
                    last_error = exc
                    print(f"[Morphism] Rejecting functor (runtime eval failed): {exc}")
                    continue

                def approx(a: float, b: float, tol: float = 1e-6) -> bool:
                    return abs(a - b) <= tol

                if not (approx(y0, 0.0) and approx(y50, 0.5) and approx(y100, 1.0)):
                    last_error = ValueError(
                        f"Normalization anchors not satisfied: f(0)={y0}, f(50)={y50}, f(100)={y100}"
                    )
                    print(f"[Morphism] Rejecting functor (anchors failed): {last_error}")
                    continue

            print(
                f"[Morphism] Z3 Verification PASSED. "
                f"Injecting AI_Bridge_Functor into pipeline."
            )

            # 4. Create the bridge node
            return FunctorNode(
                input_schema=src_schema,
                output_schema=tgt_schema,
                executable=func,
                name="AI_Bridge_Functor",
            )

        raise ProofFailedHalt(
            f"[Morphism] PROOF FAILED HALT: Generated functor "
            f"F({src_schema.name} -> {tgt_schema.name}) "
            f"failed verification after {max_attempts} attempt(s). "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Traversal helpers (time-travel debugging)
    # ------------------------------------------------------------------
    def maps_back(self) -> Optional[Any]:
        """Move ``current_context`` one step backward and return its
        cached ``output_state``."""
        if self.current_context is not None and self.current_context.prev is not None:
            self.current_context = self.current_context.prev
            return self.current_context.output_state
        return None

    def maps_forward(self) -> Optional[Any]:
        """Move ``current_context`` one step forward and return its
        cached ``output_state``."""
        if self.current_context is not None and self.current_context.next is not None:
            self.current_context = self.current_context.next
            return self.current_context.output_state
        return None

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def execute_all(self, initial_data: Any) -> Any:
        """Run every node in sequence, threading data through."""
        node = self.head
        data = initial_data
        while node is not None:
            data = node.execute(data)
            node = node.next
        # After full execution, park context at tail
        self.current_context = self.tail
        return data

    def __repr__(self) -> str:
        return f"MorphismPipeline(length={self.length})"
