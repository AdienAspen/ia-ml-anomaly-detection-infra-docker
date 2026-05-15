#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from time import perf_counter

import joblib
import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import load_json, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark startup-load + cached inference against a simulated per-inference reload path."
    )
    parser.add_argument(
        "--policy-alias",
        type=Path,
        default=Path(
            "../shared_artifacts/detector_policy/active_detector_policy.json"
        ),
        help="Path to the shared active detector policy alias.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/processed/validation_mixed_v1.parquet"),
        help="Dataset used to benchmark inference latency.",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=512,
        help="Number of rows for the cached inference benchmark.",
    )
    parser.add_argument(
        "--uncached-rows",
        type=int,
        default=64,
        help="Number of rows for the simulated per-inference reload benchmark.",
    )
    parser.add_argument(
        "--startup-repeats",
        type=int,
        default=5,
        help="How many startup loads to sample.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("artifacts/reports/detector_policy_runtime_benchmark_v1.json"),
        help="JSON report output path.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("artifacts/reports/detector_policy_runtime_benchmark_v1.md"),
        help="Markdown summary output path.",
    )
    return parser.parse_args()


def resolve_policy(alias_path: Path) -> tuple[dict, Path]:
    alias_payload = load_json(alias_path)
    if alias_payload.get("schema_version") == "detector_policy_alias_v1":
        policy_path = (alias_path.parent / alias_payload["active_policy_path"]).resolve()
        return load_json(policy_path), policy_path
    return alias_payload, alias_path


def load_runtime(alias_path: Path) -> dict:
    started = perf_counter()
    policy, policy_path = resolve_policy(alias_path)
    model_path = (policy_path.parent / policy["model_path"]).resolve()
    model = joblib.load(model_path)
    load_ms = (perf_counter() - started) * 1000
    return {
        "load_ms": load_ms,
        "policy": policy,
        "policy_path": policy_path,
        "model_path": model_path,
        "model": model,
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def benchmark_cached_inference(model: object, matrix: list[list[float]]) -> dict:
    latencies_ms: list[float] = []
    for vector in matrix:
        started = perf_counter()
        model.score_samples([vector])
        latencies_ms.append((perf_counter() - started) * 1000)
    return {
        "rows": len(matrix),
        "mean_ms": mean(latencies_ms),
        "p95_ms": percentile(latencies_ms, 0.95),
        "max_ms": max(latencies_ms),
    }


def benchmark_uncached(alias_path: Path, matrix: list[list[float]]) -> dict:
    latencies_ms: list[float] = []
    for vector in matrix:
        started = perf_counter()
        runtime = load_runtime(alias_path)
        runtime["model"].score_samples([vector])
        latencies_ms.append((perf_counter() - started) * 1000)
    return {
        "rows": len(matrix),
        "mean_ms": mean(latencies_ms),
        "p95_ms": percentile(latencies_ms, 0.95),
        "max_ms": max(latencies_ms),
    }


def main() -> int:
    args = parse_args()
    alias_path = args.policy_alias if args.policy_alias.is_absolute() else (REPO_ROOT / args.policy_alias).resolve()
    dataset_path = args.dataset if args.dataset.is_absolute() else (REPO_ROOT / args.dataset).resolve()
    output_json = args.output_json if args.output_json.is_absolute() else (REPO_ROOT / args.output_json).resolve()
    output_md = args.output_md if args.output_md.is_absolute() else (REPO_ROOT / args.output_md).resolve()

    startup_loads = [load_runtime(alias_path)["load_ms"] for _ in range(args.startup_repeats)]
    runtime = load_runtime(alias_path)
    policy = runtime["policy"]
    feature_columns = policy["expected_features"]

    frame = pl.read_parquet(dataset_path).select(feature_columns).head(args.rows)
    cached_matrix = frame.to_numpy().tolist()

    uncached_frame = pl.read_parquet(dataset_path).select(feature_columns).head(args.uncached_rows)
    uncached_matrix = uncached_frame.to_numpy().tolist()

    cached_metrics = benchmark_cached_inference(runtime["model"], cached_matrix)
    uncached_metrics = benchmark_uncached(alias_path, uncached_matrix)

    report = {
        "policy_alias_path": str(alias_path),
        "policy_path": str(runtime["policy_path"]),
        "model_path": str(runtime["model_path"]),
        "feature_columns": feature_columns,
        "startup_load": {
            "repeats": args.startup_repeats,
            "mean_ms": mean(startup_loads),
            "p95_ms": percentile(startup_loads, 0.95),
            "max_ms": max(startup_loads),
        },
        "cached_inference": cached_metrics,
        "simulated_uncached_inference": uncached_metrics,
        "comparison": {
            "mean_latency_delta_ms": uncached_metrics["mean_ms"] - cached_metrics["mean_ms"],
            "mean_latency_ratio": (
                uncached_metrics["mean_ms"] / cached_metrics["mean_ms"]
                if cached_metrics["mean_ms"] > 0
                else None
            ),
        },
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_json, report)
    output_md.write_text(
        "\n".join(
            [
                "# Detector Policy Runtime Benchmark v1",
                "",
                f"- policy alias: `{alias_path}`",
                f"- policy path: `{runtime['policy_path']}`",
                f"- model path: `{runtime['model_path']}`",
                f"- startup load mean: `{report['startup_load']['mean_ms']:.3f} ms`",
                f"- startup load p95: `{report['startup_load']['p95_ms']:.3f} ms`",
                f"- cached inference mean: `{cached_metrics['mean_ms']:.6f} ms`",
                f"- cached inference p95: `{cached_metrics['p95_ms']:.6f} ms`",
                f"- simulated uncached inference mean: `{uncached_metrics['mean_ms']:.3f} ms`",
                f"- simulated uncached inference p95: `{uncached_metrics['p95_ms']:.3f} ms`",
                f"- mean latency delta: `{report['comparison']['mean_latency_delta_ms']:.3f} ms`",
                f"- mean latency ratio: `{report['comparison']['mean_latency_ratio']:.2f}x`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
