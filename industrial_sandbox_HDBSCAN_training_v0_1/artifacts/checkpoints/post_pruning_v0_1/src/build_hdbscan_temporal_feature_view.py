"""Build the HDBSCAN temporal feature view from temporal windows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.build_temporal_windows import build_temporal_windows
from src.feature_calculator import build_hdbscan_feature_rows, export_hdbscan_feature_rows
from src.scenario_engine import build_scenario_events

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "hdbscan_temporal_feature_view_v0_1.json"


def build_hdbscan_temporal_feature_view(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return build_hdbscan_feature_rows(windows)


def export_hdbscan_temporal_feature_view(rows: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> Path:
    return export_hdbscan_feature_rows(rows, output_path=output_path)


def main() -> int:
    sample_events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=8)
    sample_windows = build_temporal_windows(sample_events)
    rows = build_hdbscan_temporal_feature_view(sample_windows)
    export_hdbscan_temporal_feature_view(rows)
    print(f"HDBSCAN temporal feature view ready: {len(rows)} rows -> {OUTPUT_PATH}")
    return 0
