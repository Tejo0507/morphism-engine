"""morphism.cli.tui – Textual TUI for the Morphism Engine (Tokyo Night rewrite).

Layout (Horizontal/Vertical composition — no CSS Grid):

* **Left  – Tool Catalog** searchable ``DataTable`` sidebar.
* **Centre – Topographer** ``Tree`` DAG + ``Static`` Inspector.
* **Right – Telemetry** ``RichLog`` streaming all engine logs.
* **Bottom – Command Input** with pipe-aware autocomplete.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    LoadingIndicator,
    RichLog,
    Static,
    Tree,
)
from textual.widgets._tree import TreeNode

from morphism.ai.synthesizer import OllamaSynthesizer
from morphism.config import config
from morphism.core.cache import FunctorCache
from morphism.core.native_node import NativeCommandNode
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import (
    Float_Normalized,
    Int_0_to_100,
    Schema,
    String_NonEmpty,
)
from morphism.exceptions import EngineExecutionError, MorphismError
from morphism.utils.logger import get_logger

_log = get_logger("cli.tui")


# ======================================================================
# Tool Registry (shared with shell.py)
# ======================================================================

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "emit_raw": {
        "func": lambda x: 50,
        "input_schema": None,
        "output_schema": Int_0_to_100,
    },
    "render_float": {
        "func": lambda x: f"[RENDERED UI]: {x}",
        "input_schema": Float_Normalized,
        "output_schema": String_NonEmpty,
    },
}

# Pre-computed list for the suggester.
_TOOL_NAMES: list[str] = list(TOOL_REGISTRY.keys())


def _make_node(cmd_name: str) -> FunctorNode:
    """Instantiate a tool node or fall back to NativeCommandNode."""
    entry = TOOL_REGISTRY.get(cmd_name)
    if entry is not None:
        in_schema: Schema = entry["input_schema"] or entry["output_schema"]
        out_schema: Schema = entry["output_schema"]
        return FunctorNode(
            input_schema=in_schema,
            output_schema=out_schema,
            executable=entry["func"],
            name=cmd_name,
        )
    return NativeCommandNode.from_command(cmd_name)


# ======================================================================
# Logging handler → RichLog widget
# ======================================================================

class _RichLogHandler(logging.Handler):
    """Bridges Python logging → Textual ``RichLog`` widget."""

    def __init__(self, rich_log: RichLog) -> None:
        super().__init__(level=logging.DEBUG)
        self._widget = rich_log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._widget.write(msg)
        except Exception:
            self.handleError(record)


# ======================================================================
# Pipe-aware Suggester
# ======================================================================

class _PipeSuggester(SuggestFromList):
    """Auto-completes tool names, resetting after every ``|`` token."""

    def __init__(self, items: list[str]) -> None:
        super().__init__(items, case_sensitive=False)
        self._items = items

    async def get_suggestion(self, value: str) -> str | None:
        if "|" in value:
            prefix = value.rsplit("|", 1)[0] + "| "
            fragment = value.rsplit("|", 1)[1].strip()
            if not fragment:
                return None
            for item in self._items:
                if item.lower().startswith(fragment.lower()):
                    return prefix + item
            return None
        return await super().get_suggestion(value)


# ======================================================================
# Textual App
# ======================================================================

class MorphismApp(App):
    """The Morphism TUI — Tokyo Night edition."""

    TITLE = "Morphism Engine v3.1"
    CSS_PATH = "morphism.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pipeline: Optional[MorphismPipeline] = None
        self._node_map: dict[str, FunctorNode] = {}
        self._log_handler: Optional[_RichLogHandler] = None
        self._cache = FunctorCache()
        self._loading: bool = False
        self._stream_mode: str = self._normalize_stream_mode(config.stream_mode)

    # ── Layout (Horizontal / Vertical — no Grid) ─────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # The Main Stage
        with Horizontal(id="main-stage"):
            # LEFT: Catalog
            with Vertical(id="left-pane"):
                yield Static("Tool Catalog", classes="pane-title")
                yield Input(id="catalog-filter", placeholder="Filter\u2026")
                yield DataTable(id="catalog-table", cursor_type="row")

            # CENTER: DAG Tree & Inspector
            with Vertical(id="center-pane"):
                with Vertical(id="tree-container", classes="split-top"):
                    yield Static("Pipeline DAG", classes="pane-title")
                    yield Tree("Engine Ready", id="dag-tree")
                with Vertical(id="inspector-container", classes="split-bottom"):
                    yield Static("Node Inspector", classes="pane-title")
                    yield Static(
                        "Select a node to inspect\u2026", id="inspector-pane",
                    )

            # RIGHT: Telemetry
            with Vertical(id="right-pane"):
                yield Static("Telemetry & Proofs", classes="pane-title")
                yield RichLog(
                    id="telemetry-log", wrap=True, highlight=True, markup=True,
                )

        # BOTTOM: Command Bar
        yield Input(
            id="cmd-input",
            placeholder="Type a pipeline command (e.g., emit_raw | render_float)",
            suggester=_PipeSuggester(_TOOL_NAMES),
        )
        yield Footer()

    # ── Mount ─────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        telemetry: RichLog = self.query_one("#telemetry-log", RichLog)
        self._log_handler = _RichLogHandler(telemetry)
        self._log_handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s \u2013 %(message)s"),
        )
        root_logger = logging.getLogger("morphism")
        root_logger.addHandler(self._log_handler)
        root_logger.setLevel(logging.DEBUG)

        telemetry.write(
            "[bold green]Morphism Engine v3.1 \u2014 TUI ready.[/bold green]",
        )
        telemetry.write("Type a pipeline command below and press Enter.")

        self._populate_catalog()

    def _populate_catalog(self, filter_text: str = "") -> None:
        table: DataTable = self.query_one("#catalog-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Tool", "Input", "Output")
        ft = filter_text.lower()
        for name, entry in TOOL_REGISTRY.items():
            if ft and ft not in name.lower():
                continue
            in_name = entry["input_schema"].name if entry["input_schema"] else "\u2014"
            out_name = entry["output_schema"].name
            table.add_row(name, in_name, out_name)

    # ── Catalog filter ────────────────────────────────────────────────

    async def on_input_changed(self, message: Input.Changed) -> None:
        if message.input.id == "catalog-filter":
            self._populate_catalog(message.value)

    # ── Command submission ────────────────────────────────────────────

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        if message.input.id != "cmd-input":
            return

        line = message.value.strip()
        if not line:
            return

        cmd_input: Input = self.query_one("#cmd-input", Input)
        cmd_input.value = ""

        if self._handle_stream_command(line):
            return

        telemetry: RichLog = self.query_one("#telemetry-log", RichLog)
        telemetry.write(f"\n[bold cyan]> {line}[/bold cyan]")

        # Disable input while running
        cmd_input.disabled = True
        self._execute_pipeline(line)

    # ── Worker-backed pipeline execution ──────────────────────────────

    @work(exclusive=True)
    async def _execute_pipeline(self, line: str) -> None:
        self._show_loading(True)
        try:
            await self._run_pipeline(line)
        except EngineExecutionError as exc:
            # Native subprocess failures — clean, user-facing message only.
            telemetry: RichLog = self.query_one("#telemetry-log", RichLog)
            telemetry.write(
                f"[bold red]Process Failed:[/bold red] {exc}",
            )
        except MorphismError as exc:
            # Schema mismatches, synthesis timeouts, verification failures.
            telemetry: RichLog = self.query_one("#telemetry-log", RichLog)
            telemetry.write(
                f"[bold red]Pipeline Error:[/bold red] {exc}",
            )
        except Exception as exc:
            # Truly unexpected — log full traceback for diagnostics.
            telemetry: RichLog = self.query_one("#telemetry-log", RichLog)
            telemetry.write(
                f"[bold red]Unexpected Error:[/bold red] {exc}",
            )
            _log.error("Unexpected error: %s", exc, exc_info=True)
        finally:
            self._show_loading(False)
            # Re-enable input
            cmd_input: Input = self.query_one("#cmd-input", Input)
            cmd_input.disabled = False

    def _show_loading(self, show: bool) -> None:
        self._loading = show
        wrapper = self.query_one("#tree-container", Vertical)
        existing = wrapper.query(LoadingIndicator)
        if show and not existing:
            wrapper.mount(LoadingIndicator())
        elif not show and existing:
            for indicator in existing:
                indicator.remove()

    async def _run_pipeline(self, line: str) -> None:
        synthesizer = OllamaSynthesizer()
        pipeline = MorphismPipeline(
            llm_client=synthesizer, cache=self._cache,
        )

        branch_match = re.match(r"^(.+?)\s*\|\+\s*\((.+)\)\s*$", line)
        if branch_match:
            prefix = branch_match.group(1).strip()
            branch_body = branch_match.group(2).strip()
            for seg in (s.strip() for s in prefix.split("|") if s.strip()):
                await pipeline.append(_make_node(seg))
            child_names = [c.strip() for c in branch_body.split(",") if c.strip()]
            children = [_make_node(c) for c in child_names]
            parent = pipeline.tail
            assert parent is not None
            await pipeline.add_branch(parent, children)
        else:
            segments = [s.strip() for s in line.split("|") if s.strip()]
            for seg in segments:
                await pipeline.append(_make_node(seg))

        telemetry: RichLog = self.query_one("#telemetry-log", RichLog)

        if self._should_stream_pipeline(pipeline):
            stream = await pipeline.execute_all_stream(None)
            preview_parts: list[str] = []
            preview_budget = 8192

            telemetry.write("[bold green]>>> [/bold green]")
            async for chunk in stream:
                text = chunk if isinstance(chunk, str) else str(chunk)
                telemetry.write(escape(text))
                if preview_budget > 0:
                    keep = text[:preview_budget]
                    preview_parts.append(keep)
                    preview_budget -= len(keep)

            if pipeline.tail is not None and preview_parts:
                pipeline.tail.output_state = "".join(preview_parts)
        else:
            result = await pipeline.execute_all(None)
            telemetry.write(f"[bold green]>>> {result}[/bold green]")

        self._pipeline = pipeline

        self._rebuild_tree()

    def _handle_stream_command(self, line: str) -> bool:
        stripped = line.strip().lower()
        if not stripped.startswith("stream"):
            return False

        telemetry: RichLog = self.query_one("#telemetry-log", RichLog)
        parts = stripped.split()

        if len(parts) == 1:
            telemetry.write(
                "[bold yellow]Stream mode:[/bold yellow] "
                f"{self._stream_mode} (valid: auto, on, off)"
            )
            return True

        mode = parts[1]
        if mode not in {"auto", "on", "off"}:
            telemetry.write("[bold red]Usage:[/bold red] stream [auto|on|off]")
            return True

        self._stream_mode = mode
        telemetry.write(
            "[bold green]Stream mode updated:[/bold green] "
            f"{self._stream_mode}"
        )
        return True

    def _should_stream_pipeline(self, pipeline: MorphismPipeline) -> bool:
        if self._stream_mode == "on":
            return True
        if self._stream_mode == "off":
            return False
        if not config.stream_auto_for_native:
            return False
        return any(isinstance(node, NativeCommandNode) for node in pipeline.all_nodes)

    @staticmethod
    def _normalize_stream_mode(mode: str) -> str:
        lowered = mode.strip().lower()
        return lowered if lowered in {"on", "off", "auto"} else "auto"

    # ── DAG tree visualisation ────────────────────────────────────────

    def _rebuild_tree(self) -> None:
        tree: Tree[str] = self.query_one("#dag-tree", Tree)
        tree.clear()
        self._node_map.clear()

        if self._pipeline is None:
            return

        visited: set[int] = set()

        def _add(parent_tree_node: TreeNode[str], fnode: FunctorNode) -> None:
            node_id = str(id(fnode))
            label = (
                f"{fnode.name}  "
                f"[{fnode.input_schema.name} \u2192 {fnode.output_schema.name}]"
            )
            child_tree = parent_tree_node.add(label, data=node_id)
            self._node_map[node_id] = fnode
            if id(fnode) in visited:
                return
            visited.add(id(fnode))
            for child in fnode.children:
                _add(child_tree, child)

        for root in self._pipeline.root_nodes:
            node_id = str(id(root))
            label = (
                f"{root.name}  "
                f"[{root.input_schema.name} \u2192 {root.output_schema.name}]"
            )
            root_tree = tree.root.add(label, data=node_id)
            self._node_map[node_id] = root
            visited.add(id(root))
            for child in root.children:
                _add(root_tree, child)

        tree.root.expand_all()

    # ── Inspector ─────────────────────────────────────────────────────

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        inspector: Static = self.query_one("#inspector-pane", Static)
        node_id = event.node.data
        if node_id is None or node_id not in self._node_map:
            inspector.update("Select a node to inspect\u2026")
            return

        fnode = self._node_map[node_id]
        state_preview = repr(fnode.output_state)
        if len(state_preview) > 500:
            state_preview = state_preview[:500] + "\u2026"

        text = (
            f"[bold]{fnode.name}[/bold]\n\n"
            f"[cyan]Input Schema:[/cyan]  {fnode.input_schema.name}\n"
            f"  type = {fnode.input_schema.data_type.__name__}\n"
            f"  constraints = {fnode.input_schema.constraints!r}\n\n"
            f"[cyan]Output Schema:[/cyan] {fnode.output_schema.name}\n"
            f"  type = {fnode.output_schema.data_type.__name__}\n"
            f"  constraints = {fnode.output_schema.constraints!r}\n\n"
            f"[cyan]Output State:[/cyan]\n{state_preview}"
        )
        inspector.update(text)

    # ── Cleanup ───────────────────────────────────────────────────────

    def on_unmount(self) -> None:
        if self._log_handler is not None:
            logging.getLogger("morphism").removeHandler(self._log_handler)
        self._cache.close()


# ======================================================================
# Entry point
# ======================================================================

def main() -> None:
    """Launch the Morphism TUI."""
    from morphism.utils.logger import setup_logging
    setup_logging("DEBUG")
    app = MorphismApp()
    app.run()


if __name__ == "__main__":
    main()
