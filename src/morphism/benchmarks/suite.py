"""Run the full Morphism benchmark suite."""

from __future__ import annotations

import argparse
from pathlib import Path

from morphism.benchmarks.dirty_data import run_dirty_data_benchmark
from morphism.benchmarks.latency import run_latency_microbenchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Morphism benchmark suite")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks") / "results",
        help="Directory for benchmark outputs",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=30,
        help="Latency trials per scenario",
    )
    parser.add_argument(
        "--dataset-url",
        type=str,
        default="https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv",
        help="Dirty-data benchmark dataset URL",
    )
    parser.add_argument(
        "--skip-latency",
        action="store_true",
        help="Skip latency microbenchmark",
    )
    parser.add_argument(
        "--skip-dirty-data",
        action="store_true",
        help="Skip dirty-data benchmark",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Benchmark output directory: {output_dir}")

    if not args.skip_latency:
        print("Running latency microbenchmark...")
        artifacts = run_latency_microbenchmark(output_dir, trials=args.trials)
        for name, path in artifacts.items():
            print(f"  latency.{name}: {path}")

    if not args.skip_dirty_data:
        print("Running dirty-data benchmark...")
        artifacts = run_dirty_data_benchmark(output_dir, dataset_url=args.dataset_url)
        for name, path in artifacts.items():
            print(f"  dirty_data.{name}: {path}")

    print("Benchmark suite complete.")


if __name__ == "__main__":
    main()
