"""test_phase12_streaming.py – Phase 12: true lazy streaming execution paths."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

import pytest

from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.native_node import NativeCommandNode
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Float_Normalized, Int_0_to_100, String_NonEmpty


async def _collect(stream: AsyncIterator[object]) -> list[object]:
    items: list[object] = []
    async for item in stream:
        items.append(item)
    return items


class TestFunctorNodeStreaming:
    @pytest.mark.asyncio
    async def test_functor_node_maps_async_input_lazily(self) -> None:
        async def source() -> AsyncIterator[int]:
            for i in range(5):
                yield i

        node = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=lambda x: x + 1,
            name="increment",
        )

        stream = await node.execute_stream(source())
        values = await asyncio.wait_for(_collect(stream), timeout=5)
        assert values == [1, 2, 3, 4, 5]


class TestNativeCommandStreaming:
    @pytest.mark.asyncio
    async def test_native_node_streams_in_chunks(self, tmp_path) -> None:
        script = tmp_path / "emit_many_lines.py"
        script.write_text(
            "import sys\n"
            "line = (b'x' * 1024) + b'\\n'\n"
            "for _ in range(4096):\n"
            "    sys.stdout.buffer.write(line)\n"
            "sys.stdout.flush()\n",
            encoding="utf-8",
        )

        cmd = f'"{sys.executable}" "{script}"'
        node = NativeCommandNode.from_command(cmd)

        stream = await node.execute_stream(None)

        chunk_count = 0
        total_chars = 0
        async for chunk in stream:
            chunk_count += 1
            total_chars += len(chunk)

        assert chunk_count > 1
        assert total_chars == 4096 * 1025


class TestPipelineStreaming:
    @pytest.mark.asyncio
    async def test_execute_all_stream_with_verified_bridge(self) -> None:
        pipeline = MorphismPipeline(llm_client=MockLLMSynthesizer())

        src = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=lambda x: x,
            name="source_int",
        )
        sink = FunctorNode(
            input_schema=Float_Normalized,
            output_schema=String_NonEmpty,
            executable=lambda x: f"{x:.1f}",
            name="render_float",
        )

        await pipeline.append(src)
        await pipeline.append(sink)

        async def source_stream() -> AsyncIterator[int]:
            for value in (0, 50, 100):
                yield value

        out_stream = await pipeline.execute_all_stream(source_stream())
        rendered = await asyncio.wait_for(_collect(out_stream), timeout=5)

        assert rendered == ["0.0", "0.5", "1.0"]
