"""Build the HDBSCAN temporal feature view from temporal windows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.build_temporal_windows import build_temporal_windows
from src.feature_calculator_v_02 import build_hdbscan_feature_rows_v_02, export_hdbscan_feature_rows_v_02
from src.scenario_engine import build_scenario_events

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "hdbscan_temporal_feature_view_v_02.json"


def build_hdbscan_temporal_feature_view_v_02(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_rows = build_hdbscan_feature_rows_v_02(windows)
    return _with_latency_deltas(base_rows)


def export_hdbscan_temporal_feature_view_v_02(rows: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> Path:
    return export_hdbscan_feature_rows_v_02(rows, output_path=output_path)


def main() -> int:
    sample_events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=8)
    sample_windows = build_temporal_windows(sample_events)
    rows = build_hdbscan_temporal_feature_view_v_02(sample_windows)
    export_hdbscan_temporal_feature_view_v_02(rows)
    print(f"HDBSCAN temporal feature view v_02 ready: {len(rows)} rows -> {OUTPUT_PATH}")
    return 0


def _with_latency_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get("scenario_tag"), []).append(row)

    output: list[dict[str, Any]] = []
    for scenario_tag, scenario_rows in grouped.items():
        ordered = sorted(scenario_rows, key=lambda item: _sort_key(item))
        previous_orders: float | None = None
        previous_checkout: float | None = None
        for row in ordered:
            current_orders = float(row.get("latency_p95_orders", 0.0))
            current_checkout = float(row.get("latency_p95_checkout", 0.0))
            enriched = dict(row)
            enriched["delta_latency_orders"] = round(current_orders - previous_orders, 6) if previous_orders is not None else 0.0
            enriched["delta_latency_checkout"] = round(current_checkout - previous_checkout, 6) if previous_checkout is not None else 0.0
            output.append(enriched)
            previous_orders = current_orders
            previous_checkout = current_checkout
    return sorted(output, key=lambda item: _sort_key(item))


def _sort_key(row: dict[str, Any]) -> tuple[str, datetime]:
    scenario_tag = row.get("scenario_tag") or ""
    window_start = row.get("window_start")
    timestamp = datetime.fromisoformat(window_start) if window_start else datetime.min
    return scenario_tag, timestamp
