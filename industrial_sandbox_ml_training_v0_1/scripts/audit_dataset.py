#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import FEATURE_COLUMNS, ensure_feature_columns, get_project_paths, read_frame, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a basic structural audit over a CSV or Parquet dataset.")
    parser.add_argument("dataset", type=Path, help="Dataset path to audit.")
    parser.add_argument("--output", type=Path, help="Optional output JSON path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    frame = read_frame(args.dataset)
    ensure_feature_columns(frame.columns)

    missing_counts = {}
    for column in FEATURE_COLUMNS:
        missing_counts[column] = int(frame.select(frame[column].is_null().sum()).item())

    audit_payload = {
        "audited_at": timestamp_utc(),
        "dataset_path": str(args.dataset),
        "row_count": frame.height,
        "column_count": frame.width,
        "columns": frame.columns,
        "missing_counts": missing_counts,
        "services_seen": frame.get_column("service_name").value_counts().to_dicts() if "service_name" in frame.columns else [],
        "scenario_mix": frame.get_column("scenario_tag").value_counts().to_dicts() if "scenario_tag" in frame.columns else [],
    }

    output = args.output or paths.data_dir / "audits" / f"{args.dataset.stem}_audit.json"
    write_json(output, audit_payload)

    print(json.dumps(
        {
            "status": "ok",
            "dataset": str(args.dataset),
            "rows": frame.height,
            "columns": frame.width,
            "output": str(output),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
