"""Render publication-ready benchmark plots from benchmark JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _plot_latency(latency_json: dict, output_path: Path) -> None:
    scenarios = latency_json["scenarios"]
    labels = ["Raw Bash Pipe", "Morphism Cache Hit", "Morphism Cold Start"]
    keys = ["raw_bash_pipe", "morphism_cache_hit", "morphism_cold_start"]

    means = [scenarios[k]["mean_ms"] for k in keys]
    stds = [scenarios[k]["stddev_ms"] for k in keys]
    lower_err = [min(s, m) for s, m in zip(stds, means)]
    upper_err = stds

    fig, ax = plt.subplots(figsize=(11, 6), dpi=180)
    colors = ["#9a031e", "#0f4c5c", "#5f0f40"]
    x = np.arange(len(labels))

    bars = ax.bar(
        x,
        means,
        yerr=np.vstack([lower_err, upper_err]),
        color=colors,
        capsize=7,
        edgecolor="#1f2937",
    )

    for bar, mean in zip(bars, means):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2.0,
            f"{mean:.2f} ms",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=0, fontsize=10)
    ax.set_ylabel("Latency (ms)", fontsize=11)
    ax.set_title("Morphism Latency Microbenchmark (50 Trials)", fontsize=14, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(means) * 1.2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _plot_dirty_data(dirty_json: dict, output_path: Path) -> None:
    labels = ["Raw Baseline", "Morphism", "Ground Truth"]
    values = [
        dirty_json["raw_normalized"],
        dirty_json["morphism_normalized"],
        dirty_json["ground_truth_normalized"],
    ]
    colors = ["#c1121f", "#003049", "#2a9d8f"]

    fig, ax = plt.subplots(figsize=(10, 6), dpi=180)
    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=colors, edgecolor="#1f2937")

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.02,
            f"{value:.4f}",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    ax.set_ylim(0, 1.1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Normalized Mean Fare", fontsize=11)
    ax.set_title("Dirty-Data Robustness Benchmark (Titanic)", fontsize=14, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    raw_gap = dirty_json["raw_gap"]
    morph_gap = dirty_json["morphism_gap"]
    ax.text(
        0.52,
        0.98,
        f"Gap vs Truth: Raw={raw_gap:.4f}, Morphism={morph_gap:.4f}",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color="#111827",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.7, "edgecolor": "#d1d5db"},
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render benchmark plots")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("benchmarks") / "results_publication",
        help="Directory containing benchmark JSON outputs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs") / "assets" / "benchmarks",
        help="Directory for generated PNG charts",
    )
    args = parser.parse_args()

    latency_json = _load_json(args.results_dir / "latency_microbenchmark_summary.json")
    dirty_json = _load_json(args.results_dir / "dirty_data_benchmark.json")

    _plot_latency(latency_json, args.output_dir / "latency_microbenchmark_50trials.png")
    _plot_dirty_data(dirty_json, args.output_dir / "dirty_data_benchmark_titanic.png")

    print("Generated benchmark plots:")
    print(f"- {args.output_dir / 'latency_microbenchmark_50trials.png'}")
    print(f"- {args.output_dir / 'dirty_data_benchmark_titanic.png'}")


if __name__ == "__main__":
    main()
