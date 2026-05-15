from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for bootstrap environments
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

FEATURE_COLUMNS = (
    "cpu_pct",
    "memory_pct",
    "latency_ms",
    "disk_io_pct",
    "net_error_rate",
    "queue_length",
    "throughput_rate",
    "http_5xx_rate",
)

LABEL_COLUMNS = ("scenario_tag",)
SERVICE_NAMES = ("payments-api", "orders-api", "checkout-api")


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    parent_root: Path
    source_1a_root: Path
    configs_dir: Path
    contracts_dir: Path
    data_dir: Path
    artifacts_dir: Path
    notebooks_dir: Path
    docs_dir: Path


def get_project_paths() -> ProjectPaths:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")

    parent_root = Path(os.getenv("PARENT_ROOT", root.parent))
    source_1a_root = Path(os.getenv("SOURCE_1A_ROOT", parent_root / "industrial_sandbox_v0_1"))

    return ProjectPaths(
        root=root,
        parent_root=parent_root,
        source_1a_root=source_1a_root,
        configs_dir=root / "configs",
        contracts_dir=root / "contracts",
        data_dir=root / "data",
        artifacts_dir=root / "artifacts",
        notebooks_dir=root / "notebooks",
        docs_dir=root / "docs",
    )


def load_json(path: Path | str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path | str, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    return path


def read_frame(path: Path | str) -> Any:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    import polars as pl

    if path.suffix.lower() == ".csv":
        return pl.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)

    raise ValueError(f"Unsupported dataset format: {path.suffix}")


def ensure_feature_columns(columns: list[str] | tuple[str, ...]) -> None:
    missing = [column for column in FEATURE_COLUMNS if column not in columns]
    if missing:
        raise ValueError(f"Missing required feature columns: {missing}")


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
