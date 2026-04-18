---
title: Benchmarking Suite
slug: /benchmarks
description: Reproducible benchmark methodology for Morphism Engine latency and dirty-data robustness.
---

## Overview

Morphism ships with a built-in benchmark suite for publication-style evaluation.

The suite currently includes:

1. Latency microbenchmark
2. Dirty-data benchmark

Run both with:

```bash
morphism-bench --output-dir benchmarks/results --trials 30
```

Equivalent module invocation:

```bash
python -m morphism.benchmarks.suite --output-dir benchmarks/results --trials 30
```

Artifacts are written under the selected output directory.

## Latency Microbenchmark

### What it measures

The latency benchmark compares:

1. Raw shell pipe (bash when available)
2. Morphism Engine cache-hit path
3. Morphism Engine cold start path (synthesis + verification + cache write)

### Workload definition

All three scenarios compute the same normalized transform:

$$
f(x) = x / 100
$$

Input value is fixed at $x = 50$ so expected output is $0.5$ in every scenario.

### Commands

Run only latency benchmark:

```bash
python -m morphism.benchmarks.latency --output-dir benchmarks/results --trials 30
```

### Generated artifacts

- `latency_microbenchmark_samples.csv`
- `latency_microbenchmark_summary.json`
- `latency_microbenchmark.svg`
- `latency_microbenchmark.md`

### Interpretation target

The publication claim supported by this benchmark is:

- cold start incurs synthesis/proof overhead,
- cache-hit execution substantially reduces this overhead,
- warm path approaches raw shell latency.

## Dirty-Data Benchmark

### Goal

Evaluate robustness on a famously messy real-world dataset (Titanic CSV) with deliberate corruption.

### Method

1. Download Titanic dataset.
2. Inject dirty values (`""`, `"??"`, `"NaN"`) into `Fare` and `"unknown"` into `Age`.
3. Run naive raw shell CSV pipeline (`cut` + `awk`) that silently miscomputes statistics.
4. Run Morphism with schema mismatch boundary `CSV_Data -> Float_Normalized`.
5. Capture event trace showing mismatch detection, bridge synthesis, verifier admission, and successful execution.

### Commands

Run only dirty-data benchmark:

```bash
python -m morphism.benchmarks.dirty_data --output-dir benchmarks/results
```

### Generated artifacts

- `dirty_data_benchmark.md`
- `dirty_data_benchmark.json`
- `dirty_data_benchmark.svg`
- `data/titanic.csv`
- `data/titanic_dirty.csv`

### Verification and traceability

The report includes:

1. Raw pipeline result and error gap vs robust CSV ground truth.
2. Morphism result and error gap vs ground truth.
3. Event trace proving:
- schema mismatch detection,
- bridge synthesis and injection,
- verifier mode/result,
- successful processing outcome.

## Reproducibility Notes

1. Pin Python and dependency versions for publication runs.
2. Keep benchmark host and load stable across trial sets.
3. Use at least 30 trials for latency runs.
4. Preserve generated JSON and SVG artifacts with paper submissions.
