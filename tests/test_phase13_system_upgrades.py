"""test_phase13_system_upgrades.py – String proofs, stream toggles, Arrow transport."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from morphism.ai.synthesizer import LLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.cli.shell import MorphismShell
from morphism.cli.tui import MorphismApp
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Float_Normalized, Int_0_to_100
from morphism.core.transport import ArrowPayload, arrow_available


class TestShellStreamToggle:
    def test_shell_stream_toggle_command(self) -> None:
        shell = MorphismShell()

        shell.do_stream("on")
        assert shell._stream_mode == "on"

        shell.do_stream("off")
        assert shell._stream_mode == "off"

        shell.do_stream("auto")
        assert shell._stream_mode == "auto"


class TestTuiStreamToggle:
    @pytest.mark.asyncio
    async def test_tui_stream_toggle_command(self) -> None:
        app = MorphismApp()
        async with app.run_test() as pilot:
            cmd_input = app.query_one("#cmd-input")
            cmd_input.value = "stream on"
            await cmd_input.action_submit()
            await pilot.pause()
            assert app._stream_mode == "on"

            cmd_input.value = "stream auto"
            await cmd_input.action_submit()
            await pilot.pause()
            assert app._stream_mode == "auto"


class TestArrowTransport:
    @pytest.mark.asyncio
    async def test_arrow_transport_fallback_to_python(self) -> None:
        pipeline = MorphismPipeline()

        producer = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=lambda _: [{"value": 1}, {"value": 2}],
            name="producer",
            supports_arrow=True,
        )

        def consume(payload):
            assert isinstance(payload, list)
            return len(payload)

        consumer = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=consume,
            name="consumer",
            supports_arrow=False,
        )

        await pipeline.append(producer)
        await pipeline.append(consumer)
        result = await pipeline.execute_all(None)

        assert result == 2


class _UnsafeThenSafeSynth(LLMSynthesizer):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_functor(self, source, target) -> str:  # type: ignore[override]
        self.calls += 1
        if self.calls == 1:
            return "__import__('os').system('echo blocked') or (lambda x: x / 100.0)"
        return "lambda x: x / 100.0"


class TestAstSandboxInSynthesisLoop:
    @pytest.mark.asyncio
    async def test_sandbox_rejects_malicious_candidate_before_eval(self, tmp_path) -> None:
        cache = FunctorCache(db_path=tmp_path / "sandbox_cache.db")
        llm = _UnsafeThenSafeSynth()
        pipeline = MorphismPipeline(llm_client=llm, cache=cache)

        source = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=lambda x: x,
            name="source_int",
        )
        sink = FunctorNode(
            input_schema=Float_Normalized,
            output_schema=Float_Normalized,
            executable=lambda x: x,
            name="sink_float",
        )

        with patch("os.system", side_effect=AssertionError("os.system should not execute")) as mocked:
            await pipeline.append(source)
            await pipeline.append(sink)
            result = await pipeline.execute_all(50)

        assert result == pytest.approx(0.5, abs=1e-6)
        assert llm.calls == 2
        assert mocked.call_count == 0

    @pytest.mark.asyncio
    async def test_arrow_transport_zero_copy_path_when_available(self) -> None:
        pipeline = MorphismPipeline()

        producer = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=lambda _: [{"value": 7}, {"value": 9}],
            name="producer_arrow",
            supports_arrow=True,
        )

        def consume(payload):
            if arrow_available():
                assert isinstance(payload, ArrowPayload)
                return payload.table.num_rows
            assert isinstance(payload, list)
            return len(payload)

        consumer = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=consume,
            name="consumer_arrow",
            supports_arrow=True,
        )

        await pipeline.append(producer)
        await pipeline.append(consumer)
        result = await pipeline.execute_all(None)

        assert result == 2
