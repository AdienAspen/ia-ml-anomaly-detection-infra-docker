#!/usr/bin/env python3
import argparse
import csv
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


FEATURE_FIELDS = [
    "cpu_pct",
    "memory_pct",
    "latency_ms",
    "disk_io_pct",
    "net_error_rate",
    "queue_length",
    "throughput_rate",
    "http_5xx_rate",
]

BURST_FIELDS = ["cpu_pct", "latency_ms", "queue_length", "http_5xx_rate"]
DRIFT_FIELDS = ["cpu_pct", "latency_ms", "queue_length", "http_5xx_rate"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a synthetic telemetry CSV export for Project 1B readiness."
    )
    parser.add_argument("csv_path", help="Path to exported telemetry CSV.")
    parser.add_argument(
        "--output",
        help="Optional Markdown output path. Defaults to <csv_stem>_audit.md next to the CSV.",
    )
    return parser.parse_args()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mean_x = mean(xs)
    mean_y = mean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if std_x == 0.0 or std_y == 0.0:
        return 0.0
    return cov / (std_x * std_y)


def format_num(value: float) -> str:
    return f"{value:.3f}"


def build_feature_stats(rows: list[dict]) -> dict[str, dict[str, float]]:
    stats = {}
    for field in FEATURE_FIELDS:
        values = [float(row[field]) for row in rows]
        stats[field] = {
            "min": min(values) if values else 0.0,
            "mean": mean(values),
            "std": stddev(values),
            "p05": percentile(values, 0.05),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "max": max(values) if values else 0.0,
        }
    return stats


def build_top_correlations(rows: list[dict]) -> list[tuple[str, str, float]]:
    values_by_field = {
        field: [float(row[field]) for row in rows]
        for field in FEATURE_FIELDS
    }
    correlations = []
    for index, left in enumerate(FEATURE_FIELDS):
        for right in FEATURE_FIELDS[index + 1 :]:
            correlations.append(
                (left, right, pearson(values_by_field[left], values_by_field[right]))
            )
    correlations.sort(key=lambda item: abs(item[2]), reverse=True)
    return correlations[:8]


def build_burst_summary(rows: list[dict]) -> dict[str, dict[str, float]]:
    by_service = defaultdict(list)
    for row in rows:
        by_service[row["service_name"]].append(row)

    summary = {}
    for service_name, service_rows in by_service.items():
        thresholds = {
            field: percentile([float(row[field]) for row in service_rows], 0.95)
            for field in BURST_FIELDS
        }
        burst_flags = []
        for row in service_rows:
            hits = sum(float(row[field]) >= thresholds[field] for field in BURST_FIELDS)
            burst_flags.append(hits >= 2)

        burst_samples = sum(burst_flags)
        burst_runs = 0
        max_run = 0
        current_run = 0
        for flag in burst_flags:
            if flag:
                current_run += 1
                max_run = max(max_run, current_run)
                if current_run == 1:
                    burst_runs += 1
            else:
                current_run = 0

        summary[service_name] = {
            "samples": len(service_rows),
            "burst_samples": burst_samples,
            "burst_sample_ratio": burst_samples / len(service_rows) if service_rows else 0.0,
            "burst_runs": burst_runs,
            "max_burst_run": max_run,
        }
    return summary


def build_drift_summary(rows: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    by_service = defaultdict(list)
    for row in rows:
        by_service[row["service_name"]].append(row)

    summary = {}
    for service_name, service_rows in by_service.items():
        sorted_rows = sorted(service_rows, key=lambda row: row["generated_at"])
        chunk = max(1, len(sorted_rows) // 5)
        early = sorted_rows[:chunk]
        late = sorted_rows[-chunk:]
        service_summary = {}
        for field in DRIFT_FIELDS:
            early_values = [float(row[field]) for row in early]
            late_values = [float(row[field]) for row in late]
            early_mean = mean(early_values)
            late_mean = mean(late_values)
            delta = late_mean - early_mean
            relative = (delta / early_mean) if early_mean else 0.0
            service_summary[field] = {
                "early_mean": early_mean,
                "late_mean": late_mean,
                "delta": delta,
                "relative_delta": relative,
            }
        summary[service_name] = service_summary
    return summary


def build_markdown_report(rows: list[dict], csv_path: Path) -> str:
    generated_values = sorted(datetime.fromisoformat(row["generated_at"]) for row in rows)
    total_samples = len(rows)
    coverage_counter = Counter(row["service_name"] for row in rows)
    scenario_counter = Counter(row["scenario_tag"] for row in rows)
    profile_counter = Counter(row["telemetry_profile"] for row in rows)
    source_counter = Counter(row["source_node"] for row in rows)
    missing_counter = Counter()

    for row in rows:
        for key, value in row.items():
            if value in ("", None):
                missing_counter[key] += 1

    feature_stats = build_feature_stats(rows)
    top_correlations = build_top_correlations(rows)
    burst_summary = build_burst_summary(rows)
    drift_summary = build_drift_summary(rows)

    lines = [
        f"# Telemetry Export Audit - {csv_path.name}",
        "",
        "## Executive Summary",
        f"- total_samples: `{total_samples}`",
        f"- time_range_start: `{generated_values[0].isoformat()}`",
        f"- time_range_end: `{generated_values[-1].isoformat()}`",
        f"- profiles_seen: `{dict(profile_counter)}`",
        f"- services_seen: `{dict(coverage_counter)}`",
        f"- scenarios_seen: `{dict(scenario_counter)}`",
        f"- source_nodes_seen: `{dict(source_counter)}`",
        "",
        "## Missing Values",
    ]

    if missing_counter:
        for key, count in sorted(missing_counter.items()):
            lines.append(f"- `{key}`: `{count}`")
    else:
        lines.append("- No missing values detected in the exported rows.")

    lines.extend(
        [
            "",
            "## Feature Stats",
            "| feature | min | mean | std | p05 | p50 | p95 | max |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for field, stats in feature_stats.items():
        lines.append(
            "| {field} | {min_} | {mean_} | {std_} | {p05} | {p50} | {p95} | {max_} |".format(
                field=field,
                min_=format_num(stats["min"]),
                mean_=format_num(stats["mean"]),
                std_=format_num(stats["std"]),
                p05=format_num(stats["p05"]),
                p50=format_num(stats["p50"]),
                p95=format_num(stats["p95"]),
                max_=format_num(stats["max"]),
            )
        )

    lines.extend(
        [
            "",
            "## Top Correlations",
        ]
    )
    for left, right, value in top_correlations:
        lines.append(f"- `{left}` vs `{right}`: `{value:.3f}`")

    lines.extend(
        [
            "",
            "## Burst Indicators",
        ]
    )
    for service_name, values in burst_summary.items():
        lines.append(
            "- `{service}`: samples=`{samples}`, burst_samples=`{burst_samples}`, burst_ratio=`{ratio:.3f}`, burst_runs=`{runs}`, max_burst_run=`{max_run}`".format(
                service=service_name,
                samples=values["samples"],
                burst_samples=values["burst_samples"],
                ratio=values["burst_sample_ratio"],
                runs=values["burst_runs"],
                max_run=values["max_burst_run"],
            )
        )

    lines.extend(
        [
            "",
            "## Drift Indicators",
        ]
    )
    for service_name, service_values in drift_summary.items():
        lines.append(f"- `{service_name}`")
        for field, values in service_values.items():
            lines.append(
                "  - `{field}`: early_mean=`{early}`, late_mean=`{late}`, delta=`{delta}`, relative_delta=`{relative:.3f}`".format(
                    field=field,
                    early=format_num(values["early_mean"]),
                    late=format_num(values["late_mean"]),
                    delta=format_num(values["delta"]),
                    relative=values["relative_delta"],
                )
            )

    lines.extend(
        [
            "",
            "## Readiness Notes",
            "- This audit is a pilot check for Project `1B`, not a training evaluation.",
            "- Use it to confirm service coverage, feature stability, burst presence, and early drift realism before large-scale export.",
            "- For the full `~72k` target, compare these same indicators again after the long export run.",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv_path).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else csv_path.with_name(f"{csv_path.stem}_audit.md")
    )

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise SystemExit(f"CSV has no rows: {csv_path}")

    report = build_markdown_report(rows, csv_path)
    output_path.write_text(report, encoding="utf-8")
    print(f"Audit report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
