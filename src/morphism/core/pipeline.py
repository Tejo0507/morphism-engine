"""morphism.core.pipeline – Async DAG pipeline with self-healing & functor cache.

Supports both linear chains *and* branching (``|+``) topologies.
Execution performs a topological traversal with ``asyncio.gather``
for parallel children.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from morphism.ai.synthesizer import LLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.schemas import Schema
from morphism.core.transport import adapt_payload_for_child
from morphism.exceptions import (
    EngineExecutionError,
    SchemaMismatchError,
    VerificationFailedError,
)
from morphism.utils.logger import get_logger

_log = get_logger("core.pipeline")

# Robust globals dict for eval()-ing LLM-generated lambdas.
# Gives the lambda access to json, math, re without __import__ hacks.
_EVAL_GLOBALS: dict[str, object] = {
    "__builtins__": __builtins__,
    "json": __import__("json"),
    "math": __import__("math"),
    "re": __import__("re"),
    "csv": __import__("csv"),
}

_TEE_END = object()
_TEE_ERROR = object()


def _is_async_iterable(value: Any) -> bool:
    return isinstance(value, AsyncIterable)


def _single_value_stream(value: Any) -> AsyncIterator[Any]:
    async def _single() -> AsyncIterator[Any]:
        yield value

    return _single()


def _async_tee(source: AsyncIterable[Any], branches: int) -> list[AsyncIterator[Any]]:
    queues = [asyncio.Queue(maxsize=1) for _ in range(branches)]
    producer_task: asyncio.Task[Any] | None = None
    active_consumers = branches
    lock = asyncio.Lock()

    async def _produce() -> None:
        try:
            async for item in source:
                for q in queues:
                    await q.put((None, item))
        except Exception as exc:
            for q in queues:
                await q.put((_TEE_ERROR, exc))
        finally:
            for q in queues:
                await q.put((_TEE_END, None))

    def _ensure_started() -> None:
        nonlocal producer_task
        if producer_task is None:
            producer_task = asyncio.create_task(_produce())

    async def _consumer(queue: asyncio.Queue[tuple[object | None, Any]]) -> AsyncIterator[Any]:
        nonlocal active_consumers
        _ensure_started()
        try:
            while True:
                marker, payload = await queue.get()
                if marker is _TEE_END:
                    break
                if marker is _TEE_ERROR:
                    raise payload
                yield payload
        finally:
            async with lock:
                active_consumers -= 1
                if (
                    active_consumers == 0
                    and producer_task is not None
                    and not producer_task.done()
                ):
                    producer_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await producer_task

    return [_consumer(queue) for queue in queues]


async def _drain_value(value: Any) -> None:
    if _is_async_iterable(value):
        async for _ in value:
            pass


async def _finalize_drain_tasks(tasks: list[asyncio.Task[None]]) -> None:
    if not tasks:
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)
    first_error = next((r for r in results if isinstance(r, Exception)), None)
    if isinstance(first_error, Exception):
        raise first_error


@dataclass
class MorphismPipeline:
    """A type-safe DAG of :class:`FunctorNode` vertices.

    When an ``llm_client`` is provided, schema mismatches trigger
    autonomous synthesis → verification → bridge-node injection.
    A :class:`FunctorCache` (SQLite) short-circuits repeated bridges.
    """

    root_nodes: list[FunctorNode] = field(default_factory=list, repr=False)
    all_nodes: list[FunctorNode] = field(default_factory=list, repr=False)
    current_context: Optional[FunctorNode] = field(default=None, repr=False)
    llm_client: Optional[LLMSynthesizer] = field(default=None, repr=False)
    cache: FunctorCache = field(default_factory=FunctorCache, repr=False)

    # ── Convenience properties (backward-compat) ─────────────────────

    @property
    def head(self) -> Optional[FunctorNode]:
        return self.root_nodes[0] if self.root_nodes else None

    @property
    def tail(self) -> Optional[FunctorNode]:
        return self.all_nodes[-1] if self.all_nodes else None

    @property
    def length(self) -> int:
        return len(self.all_nodes)

    # ------------------------------------------------------------------
    # Append (linear convenience – appends child to current tail)
    # ------------------------------------------------------------------
    async def append(self, new_node: FunctorNode) -> bool:
        """Append *new_node* as a child of the current tail node.

        If either schema is ``Pending`` the compatibility check is
        **deferred** until execution time.
        """
        if not self.all_nodes:
            # First node → root
            self.root_nodes.append(new_node)
            self.all_nodes.append(new_node)
            self.current_context = new_node
            return True

        parent = self.all_nodes[-1]

        # ── Deferred: Pending schemas bypass compile-time check ──
        if (
            parent.output_schema.name == "Pending"
            or new_node.input_schema.name == "Pending"
        ):
            parent.append_child(new_node)
            self.all_nodes.append(new_node)
            return True

        if parent.output_schema != new_node.input_schema:
            if self.llm_client is not None:
                bridge = await self._resolve_mismatch(parent, new_node)
                parent.append_child(bridge)
                self.all_nodes.append(bridge)
                bridge.append_child(new_node)
                self.all_nodes.append(new_node)
                return True
            else:
                msg = (
                    f"TYPE MISMATCH: Cannot pipe {parent} to {new_node}"
                )
                _log.warning(msg)
                raise SchemaMismatchError(msg)

        # Compatible – normal edge
        parent.append_child(new_node)
        self.all_nodes.append(new_node)
        return True

    # ------------------------------------------------------------------
    # Branching (DAG)
    # ------------------------------------------------------------------
    async def add_branch(
        self,
        parent: FunctorNode,
        children: list[FunctorNode],
    ) -> None:
        """Connect *parent* to multiple *children* (fan-out edge).

        Per-edge mismatch resolution is applied independently.
        """
        for child in children:
            if (
                parent.output_schema.name == "Pending"
                or child.input_schema.name == "Pending"
            ):
                parent.append_child(child)
                self.all_nodes.append(child)
                continue

            if parent.output_schema != child.input_schema:
                if self.llm_client is not None:
                    bridge = await self._resolve_mismatch(parent, child)
                    parent.append_child(bridge)
                    self.all_nodes.append(bridge)
                    bridge.append_child(child)
                    self.all_nodes.append(child)
                else:
                    raise SchemaMismatchError(
                        f"TYPE MISMATCH: Cannot branch {parent} to {child}"
                    )
            else:
                parent.append_child(child)
                self.all_nodes.append(child)

    # ------------------------------------------------------------------
    # Self-healing (with cache)
    # ------------------------------------------------------------------
    async def _resolve_mismatch(
        self,
        node_a: FunctorNode,
        node_b: FunctorNode,
    ) -> FunctorNode:
        assert self.llm_client is not None

        src = node_a.output_schema
        tgt = node_b.input_schema

        # ── 0. Cache lookup ──────────────────────────────────────────
        from morphism.math.z3_verifier import enforce_ast_sandbox, verify_functor_mapping

        cached_code = self.cache.lookup(src.name, tgt.name)
        if cached_code is not None:
            try:
                enforce_ast_sandbox(cached_code)
            except ValueError as exc:
                _log.warning(
                    "Cached lambda failed AST sandbox for %s->%s: %s. Evicting entry.",
                    src.name,
                    tgt.name,
                    exc,
                )
                self.cache.delete(src.name, tgt.name)
                cached_code = None

        if cached_code is not None:
            try:
                func: Callable[[Any], Any] = eval(cached_code, _EVAL_GLOBALS)  # noqa: S307
            except Exception:
                _log.warning("Cached lambda did not compile — falling through to LLM.")
            else:
                cached_proof_artifact: dict[str, Any] = {}
                if verify_functor_mapping(
                    src,
                    tgt,
                    func,
                    code_str=cached_code,
                    proof_artifact=cached_proof_artifact,
                ):
                    return FunctorNode(
                        input_schema=src,
                        output_schema=tgt,
                        executable=func,
                        name="AI_Bridge_Functor",
                    )
                _log.warning(
                    "Cached lambda failed verification for %s->%s; evicting stale cache entry.",
                    src.name, tgt.name,
                )
                self.cache.delete(src.name, tgt.name)

        # ── 1. LLM synthesis loop ───────────────────────────────────
        from morphism.config import config

        max_attempts = config.max_synthesis_attempts
        last_error: BaseException | None = None

        for attempt in range(1, max_attempts + 1):
            code_str = await self.llm_client.generate_functor(src, tgt)
            _log.info(
                "LLM Synthesising Functor F(%s -> %s)… (attempt %d/%d)",
                src.name, tgt.name, attempt, max_attempts,
            )

            try:
                enforce_ast_sandbox(code_str)
            except ValueError as exc:
                last_error = exc
                _log.warning("Rejecting functor (AST sandbox failed): %s", exc)
                continue

            try:
                func = eval(code_str, _EVAL_GLOBALS)  # noqa: S307
            except Exception as exc:
                last_error = exc
                _log.warning("Rejecting functor (compile failed): %s", exc)
                continue
            _log.info("Compiled functor: %s", code_str)

            try:
                proof_artifact: dict[str, Any] = {}
                is_safe = verify_functor_mapping(
                    src,
                    tgt,
                    func,
                    code_str=code_str,
                    proof_artifact=proof_artifact,
                )
            except (VerificationFailedError, ValueError) as exc:
                last_error = exc
                _log.warning("Rejecting functor (verifier error): %s", exc)
                continue

            if not is_safe:
                last_error = VerificationFailedError("Z3 rejected functor")
                continue

            # Semantic guardrails for canonical normalization
            if src.name == "Int_0_to_100" and tgt.name == "Float_Normalized":
                try:
                    y0, y50, y100 = float(func(0)), float(func(50)), float(func(100))
                except Exception as exc:
                    last_error = exc
                    _log.warning("Rejecting functor (anchor eval failed): %s", exc)
                    continue
                if not (
                    abs(y0 - 0.0) <= 1e-6
                    and abs(y50 - 0.5) <= 1e-6
                    and abs(y100 - 1.0) <= 1e-6
                ):
                    last_error = ValueError(
                        f"Anchors failed: f(0)={y0}, f(50)={y50}, f(100)={y100}"
                    )
                    _log.warning("Rejecting functor (anchors failed): %s", last_error)
                    continue

            _log.info(
                "Z3 Verification PASSED. Injecting AI_Bridge_Functor.",
            )

            # ── Persist to cache ─────────────────────────────────────
            self.cache.store(
                src.name,
                tgt.name,
                code_str,
                proof_certificate_path=proof_artifact.get("certificate_path"),
            )

            return FunctorNode(
                input_schema=src,
                output_schema=tgt,
                executable=func,
                name="AI_Bridge_Functor",
            )

        raise VerificationFailedError(
            f"Functor F({src.name} -> {tgt.name}) failed verification "
            f"after {max_attempts} attempt(s). Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Traversal (time-travel) – walks parent[0]/children[0] as "spine"
    # ------------------------------------------------------------------
    def maps_back(self) -> Optional[Any]:
        if self.current_context and self.current_context.parents:
            self.current_context = self.current_context.parents[0]
            return self.current_context.output_state
        return None

    def maps_forward(self) -> Optional[Any]:
        if self.current_context and self.current_context.children:
            self.current_context = self.current_context.children[0]
            return self.current_context.output_state
        return None

    # ------------------------------------------------------------------
    # Execute – topological DAG traversal
    # ------------------------------------------------------------------
    async def execute_all(self, initial_data: Any) -> Any:
        """Topological traversal of the DAG (materialized mode)."""
        return await self._execute_all_internal(initial_data, stream_mode=False)

    async def execute_all_stream(self, initial_data: Any) -> AsyncIterator[Any]:
        """Topological traversal returning a lazy async output stream."""
        result = await self._execute_all_internal(initial_data, stream_mode=True)
        if _is_async_iterable(result):
            return result
        return _single_value_stream(result)

    async def _execute_all_internal(self, initial_data: Any, stream_mode: bool) -> Any:
        """Shared DAG traversal for materialized and streaming execution."""

        def _adapt_for_child(data: Any, node: FunctorNode, child: FunctorNode) -> Any:
            if _is_async_iterable(data):
                async def _adapted_stream() -> AsyncIterator[Any]:
                    async for item in data:
                        yield adapt_payload_for_child(item, node, child)

                return _adapted_stream()

            return adapt_payload_for_child(data, node, child)

        async def _invoke_node(node: FunctorNode, data: Any) -> Any:
            if stream_mode:
                return await node.execute_stream(data)
            return await node.execute(data)

        async def _run_node(node: FunctorNode, data: Any) -> Any:
            try:
                result = await _invoke_node(node, data)
            except Exception as exc:
                raise EngineExecutionError(
                    f"Node {node.name!r} failed: {exc}"
                ) from exc

            if not node.children:
                return result

            # ── Resolve deferred edges & fan-out ─────────────────────
            child_inputs: list[Any]
            if _is_async_iterable(result) and len(node.children) > 1:
                child_inputs = list(_async_tee(result, len(node.children)))
            else:
                child_inputs = [result] * len(node.children)

            child_tasks: list[Any] = []
            for idx, child in enumerate(node.children):
                actual_out = node.output_schema
                next_in = child.input_schema
                child_data = _adapt_for_child(child_inputs[idx], node, child)

                if next_in.name == "Pending":
                    child.input_schema = actual_out
                    child_tasks.append(_run_node(child, child_data))
                elif actual_out != next_in:
                    # Runtime mismatch → bridge
                    if self.llm_client is None:
                        raise SchemaMismatchError(
                            f"Runtime schema mismatch: "
                            f"{actual_out.name} → {next_in.name} "
                            f"(no LLM client)"
                        )
                    _log.info(
                        "Runtime mismatch: %s → %s. Synthesising bridge…",
                        actual_out.name, next_in.name,
                    )
                    bridge = await self._resolve_mismatch(node, child)
                    # Insert bridge into DAG
                    node.children[node.children.index(child)] = bridge
                    bridge.append_child(child)
                    child.parents[child.parents.index(node)] = bridge
                    bridge.parents.append(node)
                    self.all_nodes.append(bridge)
                    try:
                        bridge_result = await _invoke_node(bridge, child_data)
                    except Exception as exc:
                        raise EngineExecutionError(
                            f"Bridge node failed: {exc}"
                        ) from exc
                    child_tasks.append(_run_node(child, bridge_result))
                else:
                    child_tasks.append(_run_node(child, child_data))

            results = await asyncio.gather(*child_tasks)

            if not stream_mode:
                return results[-1]  # last branch result for compat

            if len(results) == 1:
                return results[0]

            side_tasks = [
                asyncio.create_task(_drain_value(value))
                for value in results[:-1]
            ]
            last_result = results[-1]

            if not _is_async_iterable(last_result):
                await _finalize_drain_tasks(side_tasks)
                return last_result

            async def _last_with_side_drains() -> AsyncIterator[Any]:
                try:
                    async for item in last_result:
                        yield item
                finally:
                    await _finalize_drain_tasks(side_tasks)

            return _last_with_side_drains()

        # ── Execute all roots (typically one) ────────────────────────
        root_tasks = [_run_node(r, initial_data) for r in self.root_nodes]
        root_results = await asyncio.gather(*root_tasks)

        if stream_mode and len(root_results) > 1:
            side_tasks = [
                asyncio.create_task(_drain_value(value))
                for value in root_results[:-1]
            ]
            tail_result = root_results[-1]
            if _is_async_iterable(tail_result):
                async def _tail_with_side_drains() -> AsyncIterator[Any]:
                    try:
                        async for item in tail_result:
                            yield item
                    finally:
                        await _finalize_drain_tasks(side_tasks)

                final_result = _tail_with_side_drains()
            else:
                await _finalize_drain_tasks(side_tasks)
                final_result = tail_result
        else:
            final_result = root_results[-1] if root_results else None

        # Set current_context to last leaf for time-travel
        self.current_context = self.all_nodes[-1] if self.all_nodes else None
        return final_result

    def __repr__(self) -> str:
        return f"MorphismPipeline(nodes={self.length})"
