from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from src.dataset_engine.profiles import SCENARIO_PROFILES, SERVICE_PROFILES, ScenarioProfile, ServiceProfile
from src.utils import FEATURE_COLUMNS, get_project_paths, load_json, timestamp_utc, write_json

EVENT_COLUMNS = (
    "event_id",
    "generated_at",
    "source_node",
    "service_name",
    "status_code",
    "is_synthetic",
    "scenario_tag",
    "telemetry_profile",
    *FEATURE_COLUMNS,
)


@dataclass(frozen=True)
class DatasetGenerationResult:
    dataset_name: str
    frame: pl.DataFrame
    dataset_path: Path
    manifest_path: Path
    report_path: Path
    scenario_profile: ScenarioProfile
    random_seed: int


class OfflineDatasetEngine:
    def __init__(self, *, random_seed: int = 42) -> None:
        self.random_seed = int(random_seed)
        self.rng = np.random.default_rng(self.random_seed)
        self.paths = get_project_paths()

    @staticmethod
    def bounded(value: float, lower: float, upper: float) -> float:
        return round(max(lower, min(upper, value)), 3)

    def load_profile_config(self, dataset_name: str) -> dict[str, Any]:
        config_path = self.paths.configs_dir / "dataset_profiles" / f"{dataset_name}.json"
        return load_json(config_path)

    def generate_dataset(
        self,
        dataset_name: str,
        *,
        row_count_target: int | None = None,
        export_format: str | None = None,
        output_path: Path | None = None,
    ) -> DatasetGenerationResult:
        config = self.load_profile_config(dataset_name)
        row_count = int(row_count_target or config["row_count_target"])
        scenario_profile = SCENARIO_PROFILES[dataset_name]

        events = self._generate_events(config=config, scenario_profile=scenario_profile, row_count=row_count)
        frame = pl.DataFrame(events).with_row_index("__row_id")
        frame = self._apply_generation_controls(frame=frame, config=config)
        frame = frame.sort("__row_id").drop("__row_id").select(list(EVENT_COLUMNS))

        dataset_path = self._resolve_dataset_path(config=config, export_format=export_format, output_path=output_path)
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_frame(frame, dataset_path)

        manifest_path = dataset_path.with_suffix(".manifest.json")
        report_path = self.paths.artifacts_dir / "reports" / f"{dataset_name}_generation_report.md"

        manifest = self._build_dataset_manifest(
            config=config,
            frame=frame,
            dataset_path=dataset_path,
            row_count_target=row_count,
        )
        report = self._build_generation_report(config=config, frame=frame, dataset_path=dataset_path)

        write_json(manifest_path, manifest)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

        return DatasetGenerationResult(
            dataset_name=dataset_name,
            frame=frame,
            dataset_path=dataset_path,
            manifest_path=manifest_path,
            report_path=report_path,
            scenario_profile=scenario_profile,
            random_seed=self.random_seed,
        )

    def _apply_generation_controls(self, *, frame: pl.DataFrame, config: dict[str, Any]) -> pl.DataFrame:
        frame = self._apply_residual_anomaly_control(frame=frame, config=config)
        return frame

    def _generate_events(self, *, config: dict[str, Any], scenario_profile: ScenarioProfile, row_count: int) -> list[dict[str, Any]]:
        services = config["services"]
        interval_seconds = float(config.get("timeline", {}).get("interval_seconds", 1.0))
        start_time = datetime.fromisoformat(config.get("timeline", {}).get("start_timestamp", "2026-04-20T00:00:00-04:00"))
        profile_name = config["telemetry_profile"]
        source_node = config.get("source_defaults", {}).get("source_node", "node-01")

        events: list[dict[str, Any]] = []
        for iteration in range(row_count):
            service_name = services[iteration % len(services)]
            service_profile = SERVICE_PROFILES[service_name]
            payload = self._market_event(
                service_profile=service_profile,
                scenario_profile=scenario_profile,
                iteration=iteration,
                row_count=row_count,
            )
            generated_at = start_time + timedelta(seconds=interval_seconds * iteration)
            event_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{config['dataset_name']}:{self.random_seed}:{iteration}")

            events.append(
                {
                    "event_id": str(event_id),
                    "generated_at": generated_at.isoformat(),
                    "source_node": source_node,
                    "service_name": service_name,
                    "status_code": payload["status_code"],
                    "is_synthetic": True,
                    "scenario_tag": payload["scenario_tag"],
                    "telemetry_profile": profile_name,
                    **{key: payload[key] for key in FEATURE_COLUMNS},
                }
            )
        return events

    def _market_event(
        self,
        *,
        service_profile: ServiceProfile,
        scenario_profile: ScenarioProfile,
        iteration: int,
        row_count: int,
    ) -> dict[str, Any]:
        reference_iteration = self._reference_iteration(
            iteration=iteration,
            row_count=row_count,
            drift_reference_rows=scenario_profile.drift_reference_rows,
        )
        phase = reference_iteration / 6.0
        seasonal = np.sin(phase) * 4.0 + np.cos(phase / 2.0) * 2.0

        scenario_intensity = 0.0
        if self.rng.random() < scenario_profile.anomaly_probability:
            scenario_intensity = scenario_profile.scenario_intensity

        burst_active = self.rng.random() < scenario_profile.burst_chance
        burst = (
            scenario_profile.burst_strength
            * self.rng.uniform(scenario_profile.burst_min, scenario_profile.burst_max)
            if burst_active
            else 0.0
        )
        drift = scenario_profile.drift_step * reference_iteration

        cpu = service_profile.cpu_base + seasonal + drift + scenario_intensity * 14.0 + burst + self.rng.normal(0.0, 2.2)
        memory = (
            service_profile.memory_base
            + seasonal * 0.65
            + drift * 0.4
            + scenario_intensity * 9.0
            + burst * 0.5
            + self.rng.normal(0.0, 1.8)
        )
        disk = service_profile.disk_base + seasonal * 0.35 + scenario_intensity * 6.5 + burst * 0.45 + self.rng.normal(0.0, 1.3)
        queue = (
            service_profile.queue_base
            + cpu * 0.45
            + drift * 3.0
            + burst * 5.0
            + scenario_intensity * 18.0
            + self.rng.normal(0.0, 4.5)
        )
        throughput = (
            service_profile.throughput_base
            + seasonal * 1.5
            - queue * 0.42
            - scenario_intensity * 16.0
            + burst * 1.8
            + self.rng.normal(0.0, 3.2)
        )
        http_5xx = (
            service_profile.http5xx_base
            + scenario_intensity * 1.7
            + burst * 0.22
            + max(queue - 35.0, 0.0) * 0.03
            + self.rng.normal(0.0, 0.08)
        )
        net_errors = service_profile.net_error_base + http_5xx * 0.33 + scenario_intensity * 0.7 + self.rng.normal(0.0, 0.04)
        latency = (
            service_profile.latency_base
            + cpu * 0.58 * service_profile.latency_bias
            + queue * 0.9
            - throughput * 0.17
            + http_5xx * 9.0
            + burst * 3.1
            + drift * 2.0
            + self.rng.normal(0.0, 6.0)
        )

        queue_length = self.bounded(queue, 0.0, 5000.0)
        throughput_rate = self.bounded(throughput, 0.0, 5000.0)
        http_5xx_rate = self.bounded(http_5xx, 0.0, 100.0)
        net_error_rate = self.bounded(net_errors, 0.0, 1000.0)
        cpu_pct = self.bounded(cpu, 0.0, 100.0)
        memory_pct = self.bounded(memory, 0.0, 100.0)
        disk_io_pct = self.bounded(disk, 0.0, 100.0)
        latency_ms = self.bounded(latency, 0.0, 5000.0)

        if http_5xx_rate >= 2.0:
            status_code = int(self.rng.choice([429, 500, 502, 503]))
        elif latency_ms > 120.0 or queue_length > 55.0:
            status_code = int(self.rng.choice([200, 200, 200, 429]))
        else:
            status_code = 200

        if (
            (scenario_profile.force_anomalous_label_on_intensity and scenario_intensity > 0.0)
            or (scenario_profile.label_burst_as_anomalous and burst_active)
            or http_5xx_rate >= scenario_profile.label_http5xx_threshold
            or queue_length >= scenario_profile.label_queue_threshold
            or latency_ms >= scenario_profile.label_latency_threshold
        ):
            scenario_tag = "anomalous"
        else:
            scenario_tag = "normal"

        return {
            "cpu_pct": cpu_pct,
            "memory_pct": memory_pct,
            "latency_ms": latency_ms,
            "disk_io_pct": disk_io_pct,
            "net_error_rate": net_error_rate,
            "queue_length": queue_length,
            "throughput_rate": throughput_rate,
            "http_5xx_rate": http_5xx_rate,
            "status_code": status_code,
            "scenario_tag": scenario_tag,
        }

    def _apply_residual_anomaly_control(self, *, frame: pl.DataFrame, config: dict[str, Any]) -> pl.DataFrame:
        control = config.get("residual_anomaly_control", {})
        if not control.get("enabled", False):
            return frame

        target_rate = float(control.get("target_rate", 0.0))
        minimum_count = int(control.get("minimum_count", 0))
        service_balanced = bool(control.get("service_balanced", True))

        target_count = max(int(round(frame.height * target_rate)), minimum_count)
        if target_count <= 0:
            return frame

        current_count = frame.filter(pl.col("scenario_tag") == "anomalous").height
        needed = max(0, target_count - current_count)
        if needed == 0:
            return frame

        allocations = self._allocate_residual_counts(
            frame=frame,
            needed=needed,
            service_balanced=service_balanced,
        )
        if sum(allocations.values()) == 0:
            return frame

        selected_ids: list[int] = []
        for service_name, service_target in allocations.items():
            if service_target <= 0:
                continue

            service_rows = frame.filter(
                (pl.col("service_name") == service_name) & (pl.col("scenario_tag") == "normal")
            )
            if service_rows.is_empty():
                continue

            service_rows = self._score_stress(service_rows)
            chosen_ids = (
                service_rows
                .sort("stress_score", descending=True)
                .head(service_target)
                .get_column("__row_id")
                .to_list()
            )
            selected_ids.extend(int(value) for value in chosen_ids)

        if not selected_ids:
            return frame

        selected_set = set(selected_ids)
        selected_expr = pl.col("__row_id").is_in(selected_ids)

        return frame.with_columns(
            pl.when(selected_expr)
            .then(pl.lit("anomalous"))
            .otherwise(pl.col("scenario_tag"))
            .alias("scenario_tag"),
            pl.when(selected_expr & (pl.col("status_code") == 200))
            .then(pl.lit(429))
            .otherwise(pl.col("status_code"))
            .alias("status_code"),
            pl.when(pl.col("__row_id").is_in(list(selected_set)))
            .then(pl.col("http_5xx_rate").clip(0.0, 5.5) + 0.12)
            .otherwise(pl.col("http_5xx_rate"))
            .alias("http_5xx_rate"),
            pl.when(pl.col("__row_id").is_in(list(selected_set)))
            .then(pl.col("net_error_rate") + 0.03)
            .otherwise(pl.col("net_error_rate"))
            .alias("net_error_rate"),
        )

    def _allocate_residual_counts(
        self,
        *,
        frame: pl.DataFrame,
        needed: int,
        service_balanced: bool,
    ) -> dict[str, int]:
        service_counts = {
            row["service_name"]: int(row["count"])
            for row in frame.group_by("service_name").len().rename({"len": "count"}).to_dicts()
        }
        if not service_balanced:
            total = sum(service_counts.values())
            allocations = {}
            running = 0
            services = list(service_counts.keys())
            for index, service_name in enumerate(services):
                if index == len(services) - 1:
                    allocations[service_name] = needed - running
                else:
                    share = int(round(needed * (service_counts[service_name] / total)))
                    allocations[service_name] = share
                    running += share
            return allocations

        services = sorted(service_counts.keys())
        base = needed // len(services)
        remainder = needed % len(services)
        allocations = {}
        for index, service_name in enumerate(services):
            allocations[service_name] = base + (1 if index < remainder else 0)
        return allocations

    @staticmethod
    def _score_stress(frame: pl.DataFrame) -> pl.DataFrame:
        metrics = {
            "cpu_pct": 1.0,
            "latency_ms": 1.3,
            "queue_length": 1.3,
            "http_5xx_rate": 1.2,
            "net_error_rate": 1.0,
            "throughput_rate": -0.8,
        }

        scored = frame
        score_terms: list[pl.Expr] = []
        for column_name, weight in metrics.items():
            column_mean = float(frame.select(pl.col(column_name).mean()).item())
            column_std = float(frame.select(pl.col(column_name).std()).item() or 0.0)
            if column_std == 0.0:
                normalized = pl.lit(0.0)
            else:
                normalized = (pl.col(column_name) - column_mean) / column_std
            score_terms.append(normalized * weight)

        stress_expr = score_terms[0]
        for term in score_terms[1:]:
            stress_expr = stress_expr + term

        return scored.with_columns(stress_expr.alias("stress_score"))

    @staticmethod
    def _reference_iteration(*, iteration: int, row_count: int, drift_reference_rows: int) -> float:
        if row_count <= 1:
            return 0.0
        progress = iteration / float(row_count - 1)
        return progress * float(drift_reference_rows)

    def _resolve_dataset_path(self, *, config: dict[str, Any], export_format: str | None, output_path: Path | None) -> Path:
        if output_path is not None:
            return output_path

        storage = config["storage"]
        resolved = self.paths.root / storage["relative_path"]
        target_format = (export_format or storage["format"]).lower()
        if target_format not in {"csv", "parquet"}:
            raise ValueError(f"Unsupported export format: {target_format}")
        return resolved.with_suffix(f".{target_format}")

    @staticmethod
    def _write_frame(frame: pl.DataFrame, dataset_path: Path) -> None:
        if dataset_path.suffix.lower() == ".csv":
            frame.write_csv(dataset_path)
        elif dataset_path.suffix.lower() == ".parquet":
            frame.write_parquet(dataset_path)
        else:
            raise ValueError(f"Unsupported export format: {dataset_path.suffix}")

    def _build_dataset_manifest(
        self,
        *,
        config: dict[str, Any],
        frame: pl.DataFrame,
        dataset_path: Path,
        row_count_target: int,
    ) -> dict[str, Any]:
        scenario_counts = {row["scenario_tag"]: int(row["count"]) for row in frame.group_by("scenario_tag").len().rename({"len": "count"}).to_dicts()}
        service_counts = {row["service_name"]: int(row["count"]) for row in frame.group_by("service_name").len().rename({"len": "count"}).to_dicts()}
        row_count_actual = frame.height

        scenario_mix_actual = {
            key: round(value / row_count_actual, 6)
            for key, value in scenario_counts.items()
        }

        return {
            "dataset_name": config["dataset_name"],
            "dataset_purpose": config["dataset_purpose"],
            "version": config["version"],
            "feature_contract": config["feature_contract"],
            "telemetry_profile": config["telemetry_profile"],
            "row_count_target": int(row_count_target),
            "row_count_actual": row_count_actual,
            "services": config["services"],
            "service_counts_actual": service_counts,
            "scenario_mix": config["scenario_mix"],
            "scenario_mix_actual": scenario_mix_actual,
            "storage": {
                "format": dataset_path.suffix.lstrip("."),
                "relative_path": str(dataset_path.relative_to(self.paths.root)),
                "output_path": str(dataset_path),
            },
            "source_reference": config["source_reference"],
            "reproducibility": {
                **config["reproducibility"],
                "random_seed": self.random_seed,
                "generated_at": timestamp_utc(),
            },
        }

    def _build_generation_report(self, *, config: dict[str, Any], frame: pl.DataFrame, dataset_path: Path) -> str:
        scenario_lines = []
        for row in frame.group_by("scenario_tag").len().rename({"len": "count"}).sort("scenario_tag").to_dicts():
            scenario_lines.append(f"- `{row['scenario_tag']}`: `{int(row['count'])}`")

        service_lines = []
        for row in frame.group_by("service_name").len().rename({"len": "count"}).sort("service_name").to_dicts():
            service_lines.append(f"- `{row['service_name']}`: `{int(row['count'])}`")

        stats = frame.select(
            [
                pl.col(name).min().alias(f"{name}_min")
                for name in FEATURE_COLUMNS
            ]
            + [
                pl.col(name).mean().alias(f"{name}_mean")
                for name in FEATURE_COLUMNS
            ]
        ).to_dicts()[0]

        stats_lines = []
        for name in FEATURE_COLUMNS:
            stats_lines.append(
                f"- `{name}`: min=`{stats[f'{name}_min']:.3f}`, mean=`{stats[f'{name}_mean']:.3f}`"
            )

        return "\n".join(
            [
                f"# Dataset Generation Report - {config['dataset_name']}",
                "",
                "## Summary",
                f"- generated_at: `{timestamp_utc()}`",
                f"- dataset_path: `{dataset_path}`",
                f"- row_count: `{frame.height}`",
                f"- telemetry_profile: `{config['telemetry_profile']}`",
                f"- random_seed: `{self.random_seed}`",
                "",
                "## Service Coverage",
                *service_lines,
                "",
                "## Scenario Mix",
                *scenario_lines,
                "",
                "## Feature Snapshot",
                *stats_lines,
            ]
        )
