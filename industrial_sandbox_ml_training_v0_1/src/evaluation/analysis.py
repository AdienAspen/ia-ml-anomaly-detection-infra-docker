from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


def derive_analysis_columns(frame: pl.DataFrame) -> pl.DataFrame:
    result = frame
    if "generated_at" in result.columns and "generated_at_ts" not in result.columns:
        result = result.with_columns(
            pl.col("generated_at").str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", strict=False).alias("generated_at_ts")
        )

    if "generated_at_ts" in result.columns and "service_name" in result.columns:
        result = result.sort(["service_name", "generated_at_ts"])
        result = result.with_columns(
            (pl.col("generated_at_ts").rank("ordinal").over("service_name") - 1).cast(pl.Int64).alias("service_event_index"),
            pl.len().over("service_name").cast(pl.Int64).alias("service_event_count"),
        )
        result = result.with_columns(
            pl.when(pl.col("service_event_count") > 1)
            .then(pl.col("service_event_index") / (pl.col("service_event_count") - 1))
            .otherwise(0.0)
            .alias("service_progress")
        )
        result = result.with_columns(
            pl.when(pl.col("service_progress") < 0.33)
            .then(pl.lit("early"))
            .when(pl.col("service_progress") < 0.66)
            .then(pl.lit("mid"))
            .otherwise(pl.lit("late"))
            .alias("drift_slice"),
            (pl.col("service_progress") * 10.0)
            .floor()
            .clip(0, 9)
            .cast(pl.Int64)
            .alias("temporal_bucket"),
        )

    if "service_name" in result.columns and "burst_proxy" not in result.columns:
        result = result.with_columns(
            pl.col("queue_length").quantile(0.97).over("service_name").alias("queue_p97"),
            pl.col("latency_ms").quantile(0.97).over("service_name").alias("latency_p97"),
            pl.col("http_5xx_rate").quantile(0.97).over("service_name").alias("http5xx_p97"),
        )
        result = result.with_columns(
            (
                (pl.col("queue_length") >= pl.col("queue_p97")).cast(pl.Int8)
                + (pl.col("latency_ms") >= pl.col("latency_p97")).cast(pl.Int8)
                + (pl.col("http_5xx_rate") >= pl.col("http5xx_p97")).cast(pl.Int8)
            ).alias("burst_proxy_score")
        )
        result = result.with_columns((pl.col("burst_proxy_score") >= 2).alias("burst_proxy"))
        result = result.drop(["queue_p97", "latency_p97", "http5xx_p97"])

    return result


def summarize_score_distribution(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "p05": float(np.quantile(values, 0.05)),
        "p50": float(np.quantile(values, 0.50)),
        "p95": float(np.quantile(values, 0.95)),
        "max": float(np.max(values)),
    }


def _group_score_summary(frame: pl.DataFrame, group_columns: list[str]) -> list[dict[str, Any]]:
    if not all(column in frame.columns for column in group_columns):
        return []
    return (
        frame.group_by(group_columns)
        .agg(
            pl.len().alias("row_count"),
            pl.col("anomaly_score").mean().alias("anomaly_score_mean"),
            pl.col("anomaly_score").median().alias("anomaly_score_p50"),
            pl.col("anomaly_score").quantile(0.95).alias("anomaly_score_p95"),
            pl.col("predicted_flag").mean().alias("flag_rate"),
        )
        .sort(group_columns)
        .to_dicts()
    )


def compute_flagged_metrics(
    flagged: pl.DataFrame,
    *,
    threshold: float | None = None,
    threshold_mode: str = "global",
    threshold_by_service: dict[str, float] | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "threshold": float(threshold) if threshold is not None else None,
        "threshold_mode": threshold_mode,
        "row_count": flagged.height,
        "flag_rate_overall": float(flagged.get_column("predicted_flag").mean()),
        "raw_score_summary": summarize_score_distribution(flagged.get_column("raw_score").to_numpy()),
        "anomaly_score_summary": summarize_score_distribution(flagged.get_column("anomaly_score").to_numpy()),
        "service_flag_rates": _group_score_summary(flagged, ["service_name"]) if "service_name" in flagged.columns else [],
        "scenario_flag_rates": _group_score_summary(flagged, ["scenario_tag"]) if "scenario_tag" in flagged.columns else [],
        "service_scenario_flag_rates": _group_score_summary(flagged, ["service_name", "scenario_tag"])
        if {"service_name", "scenario_tag"}.issubset(set(flagged.columns))
        else [],
        "burst_slice_metrics": _group_score_summary(flagged, ["burst_proxy"]) if "burst_proxy" in flagged.columns else [],
        "drift_slice_metrics": _group_score_summary(flagged, ["drift_slice"]) if "drift_slice" in flagged.columns else [],
        "temporal_stability": _group_score_summary(flagged, ["service_name", "temporal_bucket"])
        if {"service_name", "temporal_bucket"}.issubset(set(flagged.columns))
        else [],
        "score_by_scenario": (
            flagged.group_by("scenario_tag")
            .agg(
                pl.len().alias("row_count"),
                pl.col("anomaly_score").mean().alias("anomaly_score_mean"),
                pl.col("anomaly_score").quantile(0.50).alias("anomaly_score_p50"),
                pl.col("anomaly_score").quantile(0.95).alias("anomaly_score_p95"),
            )
            .sort("scenario_tag")
            .to_dicts()
        )
        if "scenario_tag" in flagged.columns
        else [],
    }

    if "scenario_tag" in flagged.columns:
        normal_slice = flagged.filter(pl.col("scenario_tag") == "normal")
        anomalous_slice = flagged.filter(pl.col("scenario_tag") == "anomalous")
        metrics["false_positive_rate_on_normal"] = (
            float(normal_slice.get_column("predicted_flag").mean()) if normal_slice.height > 0 else None
        )
        metrics["true_positive_rate_on_anomalous"] = (
            float(anomalous_slice.get_column("predicted_flag").mean()) if anomalous_slice.height > 0 else None
        )

    if "burst_proxy" in flagged.columns and "scenario_tag" in flagged.columns:
        burst_slice = flagged.filter(pl.col("burst_proxy"))
        metrics["burst_proxy_detection"] = {
            "row_count": burst_slice.height,
            "flag_rate": float(burst_slice.get_column("predicted_flag").mean()) if burst_slice.height > 0 else None,
            "anomalous_share": (
                float((burst_slice.get_column("scenario_tag") == "anomalous").mean()) if burst_slice.height > 0 else None
            ),
        }

    if "drift_slice" in flagged.columns and "scenario_tag" in flagged.columns:
        late_slice = flagged.filter(pl.col("drift_slice") == "late")
        early_slice = flagged.filter(pl.col("drift_slice") == "early")
        metrics["drift_detection"] = {
            "early_flag_rate": float(early_slice.get_column("predicted_flag").mean()) if early_slice.height > 0 else None,
            "late_flag_rate": float(late_slice.get_column("predicted_flag").mean()) if late_slice.height > 0 else None,
            "late_anomaly_score_mean": (
                float(late_slice.get_column("anomaly_score").mean()) if late_slice.height > 0 else None
            ),
        }

    service_rates = [
        float(row["flag_rate"])
        for row in metrics["service_flag_rates"]
        if row.get("flag_rate") is not None
    ]
    metrics["service_flag_rate_span"] = max(service_rates) - min(service_rates) if service_rates else None
    if threshold_by_service is not None:
        metrics["threshold_by_service"] = threshold_by_service
    return metrics


def compute_threshold_metrics(frame: pl.DataFrame, threshold: float) -> dict[str, Any]:
    flagged = frame.with_columns((pl.col("anomaly_score") >= threshold).alias("predicted_flag"))
    return compute_flagged_metrics(flagged, threshold=threshold, threshold_mode="global")


def apply_service_thresholds(
    frame: pl.DataFrame,
    *,
    threshold_by_service: dict[str, float],
    score_column: str = "anomaly_score",
) -> pl.DataFrame:
    thresholds = pl.DataFrame(
        {
            "service_name": list(threshold_by_service.keys()),
            "service_threshold": list(threshold_by_service.values()),
        }
    )
    flagged = frame.join(thresholds, on="service_name", how="left")
    return flagged.with_columns((pl.col(score_column) >= pl.col("service_threshold")).alias("predicted_flag"))


def build_top_outliers_markdown(frame: pl.DataFrame, path: Path, top_n: int = 20) -> Path:
    columns = [
        "event_id",
        "generated_at",
        "service_name",
        "scenario_tag",
        "anomaly_score",
        "latency_ms",
        "queue_length",
        "http_5xx_rate",
        "burst_proxy",
        "drift_slice",
    ]
    available = [column for column in columns if column in frame.columns]
    top_rows = frame.sort("anomaly_score", descending=True).select(available).head(top_n).to_dicts()

    lines = [
        "# Top Outliers",
        "",
        "| rank | service | scenario | anomaly_score | latency_ms | queue_length | http_5xx_rate | burst_proxy | drift_slice | event_id |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(top_rows, start=1):
        lines.append(
            "| {rank} | {service} | {scenario} | {score:.6f} | {latency:.3f} | {queue:.3f} | {http5xx:.3f} | {burst} | {drift} | `{event_id}` |".format(
                rank=index,
                service=row.get("service_name", "-"),
                scenario=row.get("scenario_tag", "-"),
                score=float(row.get("anomaly_score", 0.0)),
                latency=float(row.get("latency_ms", 0.0)),
                queue=float(row.get("queue_length", 0.0)),
                http5xx=float(row.get("http_5xx_rate", 0.0)),
                burst=str(row.get("burst_proxy", "-")),
                drift=row.get("drift_slice", "-"),
                event_id=row.get("event_id", "-"),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_score_distribution_svg(frame: pl.DataFrame, path: Path) -> Path:
    if "scenario_tag" not in frame.columns:
        path.write_text("<svg xmlns='http://www.w3.org/2000/svg' width='900' height='420'></svg>\n", encoding="utf-8")
        return path

    normal = frame.filter(pl.col("scenario_tag") == "normal").get_column("anomaly_score").to_numpy()
    anomalous = frame.filter(pl.col("scenario_tag") == "anomalous").get_column("anomaly_score").to_numpy()
    score_min = float(frame.get_column("anomaly_score").min())
    score_max = float(frame.get_column("anomaly_score").max())
    bins = np.linspace(score_min, score_max, 25)
    normal_hist, _ = np.histogram(normal, bins=bins)
    anomalous_hist, _ = np.histogram(anomalous, bins=bins)
    max_count = max(int(normal_hist.max(initial=0)), int(anomalous_hist.max(initial=0)), 1)

    width = 900
    height = 420
    margin_left = 70
    margin_bottom = 40
    plot_width = width - margin_left - 30
    plot_height = height - 30 - margin_bottom

    def points_for(hist: np.ndarray) -> str:
        coords: list[str] = []
        for index, value in enumerate(hist):
            x = margin_left + (index / max(len(hist) - 1, 1)) * plot_width
            y = 30 + plot_height - ((float(value) / max_count) * plot_height)
            coords.append(f"{x:.2f},{y:.2f}")
        return " ".join(coords)

    normal_points = points_for(normal_hist)
    anomalous_points = points_for(anomalous_hist)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="#fbfaf6" />
  <line x1="{margin_left}" y1="30" x2="{margin_left}" y2="{30 + plot_height}" stroke="#222" stroke-width="1.5"/>
  <line x1="{margin_left}" y1="{30 + plot_height}" x2="{margin_left + plot_width}" y2="{30 + plot_height}" stroke="#222" stroke-width="1.5"/>
  <text x="{margin_left}" y="20" font-family="Helvetica, Arial, sans-serif" font-size="16" fill="#222">Anomaly score distribution: normal vs anomalous</text>
  <polyline fill="none" stroke="#1f77b4" stroke-width="3" points="{normal_points}" />
  <polyline fill="none" stroke="#c0392b" stroke-width="3" points="{anomalous_points}" />
  <text x="{margin_left + plot_width - 170}" y="40" font-family="Helvetica, Arial, sans-serif" font-size="13" fill="#1f77b4">normal</text>
  <text x="{margin_left + plot_width - 90}" y="40" font-family="Helvetica, Arial, sans-serif" font-size="13" fill="#c0392b">anomalous</text>
  <text x="{margin_left}" y="{height - 10}" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#444">min {score_min:.3f}</text>
  <text x="{margin_left + plot_width - 80}" y="{height - 10}" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#444">max {score_max:.3f}</text>
</svg>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path


def build_service_score_distribution_svg(
    frame: pl.DataFrame,
    path: Path,
    *,
    score_column: str = "anomaly_score",
    title: str = "Service score distributions",
) -> Path:
    if "service_name" not in frame.columns or "scenario_tag" not in frame.columns:
        path.write_text("<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='420'></svg>\n", encoding="utf-8")
        return path

    services = sorted(frame.get_column("service_name").unique().to_list())
    score_min = float(frame.get_column(score_column).min())
    score_max = float(frame.get_column(score_column).max())
    bins = np.linspace(score_min, score_max, 25)

    width = 1200
    height = 420
    panel_width = 320
    panel_gap = 40
    margin_left = 50
    top = 50
    plot_height = 280
    bottom = 60
    max_count = 1
    histograms: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for service_name in services:
        service_frame = frame.filter(pl.col("service_name") == service_name)
        normal = service_frame.filter(pl.col("scenario_tag") == "normal").get_column(score_column).to_numpy()
        anomalous = service_frame.filter(pl.col("scenario_tag") == "anomalous").get_column(score_column).to_numpy()
        normal_hist, _ = np.histogram(normal, bins=bins)
        anomalous_hist, _ = np.histogram(anomalous, bins=bins)
        histograms[service_name] = (normal_hist, anomalous_hist)
        max_count = max(max_count, int(normal_hist.max(initial=0)), int(anomalous_hist.max(initial=0)))

    def points_for(hist: np.ndarray, x_offset: float) -> str:
        coords: list[str] = []
        for index, value in enumerate(hist):
            x = x_offset + (index / max(len(hist) - 1, 1)) * panel_width
            y = top + plot_height - ((float(value) / max_count) * plot_height)
            coords.append(f"{x:.2f},{y:.2f}")
        return " ".join(coords)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <rect width="{width}" height="{height}" fill="#fbfaf6" />',
        f'  <text x="40" y="24" font-family="Helvetica, Arial, sans-serif" font-size="18" fill="#222">{title}</text>',
    ]
    for index, service_name in enumerate(services):
        x_offset = margin_left + index * (panel_width + panel_gap)
        normal_hist, anomalous_hist = histograms[service_name]
        parts.extend(
            [
                f'  <line x1="{x_offset}" y1="{top}" x2="{x_offset}" y2="{top + plot_height}" stroke="#222" stroke-width="1.5"/>',
                f'  <line x1="{x_offset}" y1="{top + plot_height}" x2="{x_offset + panel_width}" y2="{top + plot_height}" stroke="#222" stroke-width="1.5"/>',
                f'  <text x="{x_offset}" y="{top - 10}" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#222">{service_name}</text>',
                f'  <polyline fill="none" stroke="#1f77b4" stroke-width="3" points="{points_for(normal_hist, x_offset)}" />',
                f'  <polyline fill="none" stroke="#c0392b" stroke-width="3" points="{points_for(anomalous_hist, x_offset)}" />',
                f'  <text x="{x_offset}" y="{height - 18}" font-family="Helvetica, Arial, sans-serif" font-size="11" fill="#444">min {score_min:.3f}</text>',
                f'  <text x="{x_offset + panel_width - 70}" y="{height - 18}" font-family="Helvetica, Arial, sans-serif" font-size="11" fill="#444">max {score_max:.3f}</text>',
            ]
        )
    parts.extend(
        [
            f'  <text x="{width - 170}" y="28" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#1f77b4">normal</text>',
            f'  <text x="{width - 90}" y="28" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#c0392b">anomalous</text>',
            "</svg>",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def generate_threshold_grid(
    scores: np.ndarray,
    *,
    quantiles: list[float],
    include_thresholds: list[float] | None = None,
) -> list[float]:
    grid = {float(np.quantile(scores, quantile)) for quantile in quantiles}
    if include_thresholds:
        grid.update(float(value) for value in include_thresholds)
    return sorted(grid)
