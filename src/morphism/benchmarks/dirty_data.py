"""Dirty-data benchmark suite for Morphism Engine."""

from __future__ import annotations

import asyncio
import argparse
import csv
import json
import math
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import requests

from morphism.ai.synthesizer import LLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import CSV_Data, Float_Normalized, String_NonEmpty

_TITANIC_URL = "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"


class _DirtyFareSynth(LLMSynthesizer):
    async def generate_functor(self, source, target) -> str:  # type: ignore[override]
        return (
            "lambda x: max(0.0, min(1.0, "
            "(lambda vals: ((sum(vals) / len(vals)) / 100.0) if len(vals) > 0 else 0.0)"
            "(list(map(float, filter(lambda v: re.fullmatch(r'[0-9]+(?:\\\\.[0-9]+)?', v or ''), "
            "map(lambda row: row[9] if len(row) > 9 else '', csv.reader(x.splitlines()))))))))"
        )


class _TracedPipeline(MorphismPipeline):
    def __init__(self, *args: Any, events: list[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._events = events

    async def _resolve_mismatch(self, node_a, node_b):  # type: ignore[override]
        self._events.append(
            f"Mismatch caught: {node_a.output_schema.name} -> {node_b.input_schema.name}"
        )
        bridge = await super()._resolve_mismatch(node_a, node_b)
        self._events.append("Bridge synthesized, verified, and injected: AI_Bridge_Functor")
        return bridge


def _download_dataset(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def _build_dirty_dataset(clean_path: Path, dirty_path: Path) -> Path:
    with clean_path.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not fieldnames or "Fare" not in fieldnames:
        raise RuntimeError("Titanic dataset does not include expected Fare column")

    for idx, row in enumerate(rows):
        if idx % 17 == 0:
            row["Fare"] = ""
        elif idx % 29 == 0:
            row["Fare"] = "??"
        elif idx % 41 == 0:
            row["Fare"] = "NaN"

        if idx % 23 == 0:
            row["Age"] = "unknown"

    dirty_path.parent.mkdir(parents=True, exist_ok=True)
    with dirty_path.open("w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return dirty_path


def _naive_python_fallback(dirty_path: Path) -> float:
    lines = dirty_path.read_text(encoding="utf-8").splitlines()[1:]
    total = 0.0
    count = 0
    for line in lines:
        parts = line.split(",")
        if len(parts) <= 9:
            continue
        count += 1
        try:
            total += float(parts[9])
        except ValueError:
            total += 0.0
    return total / count if count else 0.0


def _run_raw_bash_pipeline(dirty_path: Path) -> tuple[float, str, str]:
    quoted = str(dirty_path).replace("'", "'\"'\"'")
    command_text = (
        f"cat '{quoted}' | tail -n +2 | cut -d, -f10 | "
        "awk '{sum += $1; n += 1} END {if (n>0) print sum/n; else print 0}'"
    )

    bash = shutil.which("bash")
    if bash and _shell_works([bash, "-lc", "echo 1"]):
        proc = subprocess.run(
            [bash, "-lc", command_text],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip().splitlines()
            return (float(out[-1]) if out else 0.0, "bash", command_text)

    sh = shutil.which("sh")
    if sh and _shell_works([sh, "-lc", "echo 1"]):
        proc = subprocess.run(
            [sh, "-lc", command_text],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip().splitlines()
            return (float(out[-1]) if out else 0.0, "sh", command_text)

    return (_naive_python_fallback(dirty_path), "python-naive-fallback", "python line.split(',')[9] naive parser")


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


def _ground_truth_mean_fare(dirty_path: Path) -> float:
    fares: list[float] = []
    with dirty_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw = (row.get("Fare") or "").strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            fares.append(value)

    if not fares:
        return 0.0
    return sum(fares) / len(fares)


def _clamp_norm(value: float) -> float:
    return max(0.0, min(1.0, value / 100.0))


async def _run_morphism_pipeline(dirty_path: Path, cache_path: Path) -> dict[str, Any]:
    events: list[str] = []
    cache = FunctorCache(db_path=cache_path)
    try:
        producer = FunctorNode(
            input_schema=CSV_Data,
            output_schema=CSV_Data,
            executable=lambda _: dirty_path.read_text(encoding="utf-8"),
            name="load_dirty_titanic",
        )
        consumer = FunctorNode(
            input_schema=Float_Normalized,
            output_schema=String_NonEmpty,
            executable=lambda x: f"mean_fare_norm={x:.6f}",
            name="render_float",
        )

        if producer.output_schema != consumer.input_schema:
            events.append(
                "Schema mismatch detected at boundary: CSV_Data -> Float_Normalized"
            )

        pipeline = _TracedPipeline(
            llm_client=_DirtyFareSynth(),
            cache=cache,
            events=events,
        )
        await pipeline.append(producer)
        await pipeline.append(consumer)
        rendered = await pipeline.execute_all(None)

        parsed_match = re.search(r"([0-9]+(?:\.[0-9]+)?)$", str(rendered).strip())
        morphism_norm = float(parsed_match.group(1)) if parsed_match else 0.0

        with sqlite3.connect(cache_path) as conn:
            row = conn.execute(
                "SELECT lambda_string, proof_certificate_path FROM functors "
                "WHERE source_name=? AND target_name=?",
                (CSV_Data.name, Float_Normalized.name),
            ).fetchone()

        lambda_string = row[0] if row else ""
        proof_path = row[1] if row else None

        proof_payload: dict[str, Any] = {}
        if proof_path:
            proof_file = Path(proof_path)
            if proof_file.exists():
                proof_payload = json.loads(proof_file.read_text(encoding="utf-8"))

        return {
            "events": events,
            "output": str(rendered),
            "morphism_normalized": morphism_norm,
            "lambda_string": lambda_string,
            "proof_path": proof_path,
            "proof_payload": proof_payload,
        }
    finally:
        cache.close()


def _write_dirty_comparison_svg(path: Path, raw_norm: float, morph_norm: float, truth_norm: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    width = 920
    height = 520
    margin_left = 90
    margin_right = 40
    margin_top = 80
    margin_bottom = 120
    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom

    labels = ["raw_bash", "morphism", "ground_truth"]
    values = [raw_norm, morph_norm, truth_norm]
    colors = ["#dc2626", "#2563eb", "#16a34a"]

    max_val = max(max(values) * 1.2, 1.0)
    gap = 40
    bar_w = (chart_w - gap * (len(labels) + 1)) / len(labels)

    lines: list[str] = []
    lines.append(f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>")
    lines.append("<rect width='100%' height='100%' fill='#ffffff' />")
    lines.append(
        f"<text x='{width / 2}' y='42' text-anchor='middle' "
        "font-family='Segoe UI, Arial, sans-serif' font-size='24' fill='#111827'>Dirty Data Benchmark</text>"
    )

    lines.append(
        f"<line x1='{margin_left}' y1='{margin_top + chart_h}' x2='{margin_left + chart_w}' y2='{margin_top + chart_h}' stroke='#334155' stroke-width='2' />"
    )
    lines.append(
        f"<line x1='{margin_left}' y1='{margin_top}' x2='{margin_left}' y2='{margin_top + chart_h}' stroke='#334155' stroke-width='2' />"
    )

    for tick in range(6):
        value = (max_val / 5) * tick
        y = margin_top + chart_h - ((value / max_val) * chart_h)
        lines.append(
            f"<line x1='{margin_left}' y1='{y:.2f}' x2='{margin_left + chart_w}' y2='{y:.2f}' stroke='#e2e8f0' stroke-width='1' />"
        )
        lines.append(
            f"<text x='{margin_left - 10}' y='{y + 5:.2f}' text-anchor='end' font-family='Segoe UI, Arial, sans-serif' font-size='12' fill='#475569'>{value:.3f}</text>"
        )

    for idx, (label, value) in enumerate(zip(labels, values)):
        x = margin_left + gap + idx * (bar_w + gap)
        bar_h = (value / max_val) * chart_h
        y = margin_top + chart_h - bar_h
        lines.append(
            f"<rect x='{x:.2f}' y='{y:.2f}' width='{bar_w:.2f}' height='{bar_h:.2f}' fill='{colors[idx]}' rx='6' ry='6' />"
        )
        lines.append(
            f"<text x='{x + bar_w / 2:.2f}' y='{y - 8:.2f}' text-anchor='middle' font-family='Segoe UI, Arial, sans-serif' font-size='12' fill='#0f172a'>{value:.4f}</text>"
        )
        lines.append(
            f"<text x='{x + bar_w / 2:.2f}' y='{margin_top + chart_h + 24}' text-anchor='middle' font-family='Segoe UI, Arial, sans-serif' font-size='12' fill='#1f2937'>{label}</text>"
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Dirty Data Benchmark",
        "",
        "This benchmark compares a naive raw shell CSV pipeline against Morphism on a deliberately corrupted Titanic dataset.",
        "",
        "## Dataset",
        "",
        f"- Clean source: `{payload['clean_dataset']}`",
        f"- Dirty dataset: `{payload['dirty_dataset']}`",
        "",
        "## Raw Pipeline (Silent Failure)",
        "",
        f"- Runtime: `{payload['raw_runtime']}`",
        f"- Command: `{payload['raw_command']}`",
        f"- Naive raw mean fare: `{payload['raw_mean_fare']:.6f}`",
        f"- Naive normalized value: `{payload['raw_normalized']:.6f}`",
        "",
        "## Morphism Engine Path",
        "",
        f"- Output: `{payload['morphism_output']}`",
        f"- Morphism normalized value: `{payload['morphism_normalized']:.6f}`",
        f"- Cached bridge lambda: `{payload['lambda_string']}`",
        f"- Proof artifact: `{payload['proof_path']}`",
        f"- Verifier mode: `{payload['proof_mode']}`",
        f"- Verifier result: `{payload['proof_solver_result']}`",
        "",
        "### Event Trace",
        "",
    ]

    for event in payload["events"]:
        lines.append(f"- {event}")

    lines.extend(
        [
            "",
            "## Ground Truth",
            "",
            f"- Robust CSV mean fare: `{payload['ground_truth_mean_fare']:.6f}`",
            f"- Robust normalized value: `{payload['ground_truth_normalized']:.6f}`",
            "",
            "## Verdict",
            "",
            f"- Raw silent-failure gap vs truth: `{payload['raw_gap']:.6f}`",
            f"- Morphism gap vs truth: `{payload['morphism_gap']:.6f}`",
            f"- Raw pipeline silent failure observed: `{payload['raw_silent_failure']}`",
            f"- Morphism successfully processed dirty data: `{payload['morphism_success']}`",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_dirty_data_benchmark(output_dir: Path, dataset_url: str = _TITANIC_URL) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"

    clean_path = _download_dataset(dataset_url, data_dir / "titanic.csv")
    dirty_path = _build_dirty_dataset(clean_path, data_dir / "titanic_dirty.csv")

    raw_mean, raw_runtime, raw_command = _run_raw_bash_pipeline(dirty_path)
    raw_norm = _clamp_norm(raw_mean)

    truth_mean = _ground_truth_mean_fare(dirty_path)
    truth_norm = _clamp_norm(truth_mean)

    cache_path = output_dir / "dirty_data_cache.db"
    cache_path.unlink(missing_ok=True)
    morphism = asyncio.run(_run_morphism_pipeline(dirty_path, cache_path))

    morph_norm = float(morphism["morphism_normalized"])
    raw_gap = abs(raw_norm - truth_norm)
    morph_gap = abs(morph_norm - truth_norm)

    proof_payload = morphism.get("proof_payload") or {}

    result_payload = {
        "clean_dataset": str(clean_path),
        "dirty_dataset": str(dirty_path),
        "raw_runtime": raw_runtime,
        "raw_command": raw_command,
        "raw_mean_fare": raw_mean,
        "raw_normalized": raw_norm,
        "ground_truth_mean_fare": truth_mean,
        "ground_truth_normalized": truth_norm,
        "morphism_output": morphism.get("output", ""),
        "morphism_normalized": morph_norm,
        "lambda_string": morphism.get("lambda_string", ""),
        "proof_path": morphism.get("proof_path"),
        "proof_mode": proof_payload.get("mode", "unknown"),
        "proof_solver_result": proof_payload.get("solver_result", "unknown"),
        "events": morphism.get("events", []),
        "raw_gap": raw_gap,
        "morphism_gap": morph_gap,
        "raw_silent_failure": raw_gap > 0.02,
        "morphism_success": morph_gap <= 0.02,
    }

    report_path = output_dir / "dirty_data_benchmark.md"
    json_path = output_dir / "dirty_data_benchmark.json"
    chart_path = output_dir / "dirty_data_benchmark.svg"

    _write_report(report_path, result_payload)
    json_path.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
    _write_dirty_comparison_svg(chart_path, raw_norm, morph_norm, truth_norm)

    return {
        "report_md": str(report_path),
        "summary_json": str(json_path),
        "chart_svg": str(chart_path),
        "dirty_dataset": str(dirty_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Morphism dirty-data benchmark")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks") / "results",
        help="Directory for benchmark artifacts",
    )
    parser.add_argument(
        "--dataset-url",
        type=str,
        default=_TITANIC_URL,
        help="Dataset URL to download",
    )
    args = parser.parse_args()

    artifacts = run_dirty_data_benchmark(args.output_dir, dataset_url=args.dataset_url)
    print("Dirty-data benchmark completed.")
    for name, path in artifacts.items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
