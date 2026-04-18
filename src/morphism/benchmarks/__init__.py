"""Benchmark suite for Morphism Engine."""

from morphism.benchmarks.dirty_data import run_dirty_data_benchmark
from morphism.benchmarks.latency import run_latency_microbenchmark

__all__ = [
    "run_dirty_data_benchmark",
    "run_latency_microbenchmark",
]
