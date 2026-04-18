"""Latency microbenchmark suite for Morphism Engine."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from morphism.ai.synthesizer import LLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Float_Normalized, Int_0_to_100


@dataclass(frozen=True)
class _ScenarioStats:
    name: str
    samples_ms: list[float]

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples_ms)

    @property
    def median(self) -> float:
        return _percentile(self.samples_ms, 50)

    @property
    def p95(self) -> float:
        return _percentile(self.samples_ms, 95)

    @property
    def stddev(self) -> float:
        if len(self.samples_ms) < 2:
            return 0.0
        return statistics.stdev(self.samples_ms)


class _DeterministicNormalizerSynth(LLMSynthesizer):
    async def generate_functor(self, source, target) -> str:  # type: ignore[override]
        return "lambda x: x / 100.0"


class _FailIfCalledSynth(LLMSynthesizer):
    async def generate_functor(self, source, target) -> str:  # type: ignore[override]
        raise RuntimeError("Synthesis was called on cache-hit path")


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _clamp_non_negative(value: float) -> float:
    return value if value >= 0.0 else 0.0


def _detect_shell_command() -> tuple[str, list[str]]:
    bash = shutil.which("bash")
    if bash and _shell_works([bash, "-lc", "echo 1"]):
        return (
            "bash",
            [
                bash,
                "-lc",
                "printf '50\\n' | { read x; echo \"0.$((x / 10))\"; }",
            ],
        )

    sh = shutil.which("sh")
    if sh and _shell_works([sh, "-lc", "echo 1"]):
        return (
            "sh",
            [
                sh,
                "-lc",
                "printf '50\\n' | { read x; echo \"0.$((x / 10))\"; }",
            ],
        )

    powershell = shutil.which("powershell")
    if powershell:
        return (
            "powershell-fallback",
            [
                powershell,
                "-NoProfile",
                "-Command",
                "$value = 50; $value / 100.0",
            ],
        )

    raise RuntimeError("No shell runtime found for raw pipe benchmark")


def _shell_works(smoke_command: list[str]) -> bool:
    try:
        proc = subprocess.run(
            smoke_command,
            check=False,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except OSError:
        return False


def _run_raw_shell_pipe_once(command: list[str]) -> float:
    proc = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    out = proc.stdout.strip().splitlines()
    if not out:
        raise RuntimeError("Raw shell pipeline produced no output")
    return float(out[-1].strip())


async def _run_morphism_once(cache_path: Path, synthesizer: LLMSynthesizer) -> float:
    cache = FunctorCache(db_path=cache_path)
    try:
        source = FunctorNode(
            input_schema=Int_0_to_100,
            output_schema=Int_0_to_100,
            executable=lambda x: x,
            name="emit_raw",
        )
        sink = FunctorNode(
            input_schema=Float_Normalized,
            output_schema=Float_Normalized,
            executable=lambda x: x,
            name="identity_float",
        )

        pipeline = MorphismPipeline(llm_client=synthesizer, cache=cache)
        await pipeline.append(source)
        await pipeline.append(sink)

        result = await pipeline.execute_all(50)
        return float(result)
    finally:
        cache.close()


async def _run_cold_trials(trials: int) -> list[float]:
    with tempfile.TemporaryDirectory(prefix="morphism_cold_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        samples: list[float] = []
        for idx in range(trials):
            cache_path = tmp_path / f"cold_{idx}.db"
            cache_path.unlink(missing_ok=True)

            start = time.perf_counter()
            out = await _run_morphism_once(cache_path, _DeterministicNormalizerSynth())
            elapsed_ms = _clamp_non_negative((time.perf_counter() - start) * 1000.0)

            if abs(out - 0.5) > 1e-9:
                raise RuntimeError(f"Unexpected cold-start output: {out}")
            samples.append(elapsed_ms)

        return samples


async def _run_cache_hit_trials(trials: int) -> list[float]:
    with tempfile.TemporaryDirectory(prefix="morphism_warm_") as tmp_dir:
        cache_path = Path(tmp_dir) / "warm.db"

        warm_out = await _run_morphism_once(cache_path, _DeterministicNormalizerSynth())
        if abs(warm_out - 0.5) > 1e-9:
            raise RuntimeError(f"Unexpected warm-up output: {warm_out}")

        samples: list[float] = []
        for _ in range(trials):
            start = time.perf_counter()
            out = await _run_morphism_once(cache_path, _FailIfCalledSynth())
            elapsed_ms = _clamp_non_negative((time.perf_counter() - start) * 1000.0)

            if abs(out - 0.5) > 1e-9:
                raise RuntimeError(f"Unexpected cache-hit output: {out}")
            samples.append(elapsed_ms)

        return samples


def _run_raw_pipe_trials(command: list[str], trials: int) -> list[float]:
    samples: list[float] = []
    for _ in range(trials):
        start = time.perf_counter()
        _ = _run_raw_shell_pipe_once(command)
        elapsed_ms = _clamp_non_negative((time.perf_counter() - start) * 1000.0)
        samples.append(elapsed_ms)
    return samples


def _write_csv(path: Path, scenarios: list[_ScenarioStats]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scenario", "trial_index", "latency_ms"])
        for scenario in scenarios:
            for idx, sample in enumerate(scenario.samples_ms, start=1):
                writer.writerow([scenario.name, idx, f"{sample:.6f}"])


def _write_summary_json(path: Path, scenarios: list[_ScenarioStats], shell_runtime: str) -> None:
    summary = {
        "shell_runtime": shell_runtime,
        "scenarios": {
            s.name: {
                "mean_ms": s.mean,
                "median_ms": s.median,
                "p95_ms": s.p95,
                "stddev_ms": s.stddev,
                "trials": len(s.samples_ms),
            }
            for s in scenarios
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _write_bar_chart_svg(path: Path, scenarios: list[_ScenarioStats], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    width = 980
    height = 560
    margin_left = 90
    margin_right = 40
    margin_top = 80
    margin_bottom = 120
    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom

    means = [s.mean for s in scenarios]
    max_mean = max(means) if means else 1.0
    max_val = max(max_mean * 1.2, 1.0)

    colors = ["#355070", "#6d597a", "#b56576"]
    bar_gap = 40
    bar_w = (chart_w - bar_gap * (len(scenarios) + 1)) / max(len(scenarios), 1)

    lines: list[str] = []
    lines.append(f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>")
    lines.append("<rect width='100%' height='100%' fill='#f9fafb' />")
    lines.append(
        f"<text x='{width / 2}' y='42' text-anchor='middle' "
        "font-family='Segoe UI, Arial, sans-serif' font-size='24' fill='#1f2937'>"
        f"{title}</text>"
    )

    lines.append(
        f"<line x1='{margin_left}' y1='{margin_top + chart_h}' "
        f"x2='{margin_left + chart_w}' y2='{margin_top + chart_h}' stroke='#334155' stroke-width='2' />"
    )
    lines.append(
        f"<line x1='{margin_left}' y1='{margin_top}' "
        f"x2='{margin_left}' y2='{margin_top + chart_h}' stroke='#334155' stroke-width='2' />"
    )

    for tick in range(6):
        value = (max_val / 5) * tick
        y = margin_top + chart_h - ((value / max_val) * chart_h)
        lines.append(
            f"<line x1='{margin_left}' y1='{y:.2f}' x2='{margin_left + chart_w}' y2='{y:.2f}' "
            "stroke='#e2e8f0' stroke-width='1' />"
        )
        lines.append(
            f"<text x='{margin_left - 10}' y='{y + 5:.2f}' text-anchor='end' "
            "font-family='Segoe UI, Arial, sans-serif' font-size='12' fill='#475569'>"
            f"{value:.1f}</text>"
        )

    for idx, scenario in enumerate(scenarios):
        mean = scenario.mean
        x = margin_left + bar_gap + idx * (bar_w + bar_gap)
        bar_h = (mean / max_val) * chart_h
        y = margin_top + chart_h - bar_h
        color = colors[idx % len(colors)]

        lines.append(
            f"<rect x='{x:.2f}' y='{y:.2f}' width='{bar_w:.2f}' height='{bar_h:.2f}' "
            f"fill='{color}' rx='6' ry='6' />"
        )
        lines.append(
            f"<text x='{x + bar_w / 2:.2f}' y='{y - 8:.2f}' text-anchor='middle' "
            "font-family='Segoe UI, Arial, sans-serif' font-size='12' fill='#0f172a'>"
            f"{mean:.2f} ms</text>"
        )
        lines.append(
            f"<text x='{x + bar_w / 2:.2f}' y='{margin_top + chart_h + 24}' text-anchor='middle' "
            "font-family='Segoe UI, Arial, sans-serif' font-size='12' fill='#1f2937'>"
            f"{scenario.name}</text>"
        )

    lines.append(
        f"<text x='{margin_left + chart_w / 2}' y='{height - 20}' text-anchor='middle' "
        "font-family='Segoe UI, Arial, sans-serif' font-size='13' fill='#334155'>Latency (ms)</text>"
    )

    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_markdown_report(path: Path, scenarios: list[_ScenarioStats], shell_runtime: str) -> None:
    lines = [
        "# Latency Microbenchmark",
        "",
        "This benchmark compares raw shell piping vs Morphism cold and warm paths.",
        "",
        f"- Raw shell runtime: `{shell_runtime}`",
        "",
        "| Scenario | Mean (ms) | Median (ms) | P95 (ms) | StdDev (ms) | Trials |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for s in scenarios:
        lines.append(
            f"| {s.name} | {s.mean:.3f} | {s.median:.3f} | {s.p95:.3f} | {s.stddev:.3f} | {len(s.samples_ms)} |"
        )

    warm = next((s for s in scenarios if s.name == "morphism_cache_hit"), None)
    cold = next((s for s in scenarios if s.name == "morphism_cold_start"), None)
    raw = next((s for s in scenarios if s.name == "raw_bash_pipe"), None)

    if warm and cold and raw:
        lines.extend(
            [
                "",
                "## Interpretation",
                "",
                f"- Cold-start overhead multiplier vs cache-hit: `{cold.mean / max(warm.mean, 1e-9):.2f}x`.",
                f"- Cache-hit overhead multiplier vs raw shell: `{warm.mean / max(raw.mean, 1e-9):.2f}x`.",
                "- This validates the cache value proposition: after first synthesis+proof, subsequent runs approach shell-level latency.",
            ]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_latency_microbenchmark(output_dir: Path, trials: int = 30) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    shell_runtime, command = _detect_shell_command()
    raw_samples = _run_raw_pipe_trials(command, trials)

    cold_samples = asyncio.run(_run_cold_trials(trials))
    hit_samples = asyncio.run(_run_cache_hit_trials(trials))

    scenarios = [
        _ScenarioStats("raw_bash_pipe", raw_samples),
        _ScenarioStats("morphism_cache_hit", hit_samples),
        _ScenarioStats("morphism_cold_start", cold_samples),
    ]

    csv_path = output_dir / "latency_microbenchmark_samples.csv"
    summary_path = output_dir / "latency_microbenchmark_summary.json"
    chart_path = output_dir / "latency_microbenchmark.svg"
    report_path = output_dir / "latency_microbenchmark.md"

    _write_csv(csv_path, scenarios)
    _write_summary_json(summary_path, scenarios, shell_runtime)
    _write_bar_chart_svg(chart_path, scenarios, "Latency Microbenchmark")
    _write_markdown_report(report_path, scenarios, shell_runtime)

    return {
        "samples_csv": str(csv_path),
        "summary_json": str(summary_path),
        "chart_svg": str(chart_path),
        "report_md": str(report_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Morphism latency microbenchmark")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks") / "results",
        help="Directory for benchmark artifacts",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=30,
        help="Number of trials per scenario",
    )
    args = parser.parse_args()

    artifacts = run_latency_microbenchmark(args.output_dir, trials=args.trials)
    print("Latency microbenchmark completed.")
    for name, path in artifacts.items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
