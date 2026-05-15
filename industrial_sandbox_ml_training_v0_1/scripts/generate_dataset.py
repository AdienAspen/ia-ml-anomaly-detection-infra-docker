#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.dataset_engine import OfflineDatasetEngine
from src.utils import get_project_paths, load_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a reproducible offline dataset-generation plan.")
    parser.add_argument(
        "--profile",
        default="training_normal_v1",
        choices=["training_normal_v1", "validation_mixed_v1"],
        help="Dataset profile name.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional explicit config path. Defaults to configs/dataset_profiles/<profile>.json.",
    )
    parser.add_argument(
        "--plan-output",
        type=Path,
        help="Optional output path for the generated dataset file (.csv/.parquet) or manifest (.json).",
    )
    parser.add_argument(
        "--rows",
        type=int,
        help="Optional row-count override.",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "parquet"],
        help="Optional export format override.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    config_path = args.config or paths.configs_dir / "dataset_profiles" / f"{args.profile}.json"
    dataset_config = load_json(config_path)
    output_path = None
    manifest_override = None
    if args.plan_output:
        suffix = args.plan_output.suffix.lower()
        if suffix in {".csv", ".parquet"}:
            output_path = args.plan_output
        elif suffix == ".json":
            manifest_override = args.plan_output

    engine = OfflineDatasetEngine(random_seed=args.seed)
    result = engine.generate_dataset(
        args.profile,
        row_count_target=args.rows,
        export_format=args.format,
        output_path=output_path,
    )
    if manifest_override is not None:
        manifest_override.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.manifest_path, manifest_override)
        manifest_path = manifest_override
    else:
        manifest_path = result.manifest_path

    print(json.dumps(
        {
            "status": "ok",
            "profile": args.profile,
            "dataset_path": str(result.dataset_path),
            "manifest_path": str(manifest_path),
            "report_path": str(result.report_path),
            "target_rows": int(args.rows or dataset_config["row_count_target"]),
            "generated_rows": result.frame.height,
            "export_format": result.dataset_path.suffix.lstrip("."),
            "scenario_counts": {
                row["scenario_tag"]: int(row["count"])
                for row in result.frame.group_by("scenario_tag").len().rename({"len": "count"}).to_dicts()
            },
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
