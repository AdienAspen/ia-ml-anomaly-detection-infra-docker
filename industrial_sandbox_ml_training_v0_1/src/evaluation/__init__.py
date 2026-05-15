"""Evaluation helpers for block 1B threshold analysis."""

from .analysis import (
    apply_service_thresholds,
    build_score_distribution_svg,
    build_service_score_distribution_svg,
    build_top_outliers_markdown,
    compute_flagged_metrics,
    compute_threshold_metrics,
    derive_analysis_columns,
    generate_threshold_grid,
    summarize_score_distribution,
)

__all__ = [
    "apply_service_thresholds",
    "build_score_distribution_svg",
    "build_service_score_distribution_svg",
    "build_top_outliers_markdown",
    "compute_flagged_metrics",
    "compute_threshold_metrics",
    "derive_analysis_columns",
    "generate_threshold_grid",
    "summarize_score_distribution",
]
