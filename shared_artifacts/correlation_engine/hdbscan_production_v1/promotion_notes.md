# Correlation Engine Promotion Notes

- block 1B.2 validates and exports; block 1C consumes this package as a pre-production/shadow candidate.
- selected candidate: `hdbscan_production_v1`
- selected source checkpoint: `post_filter_operating_point_v_02`
- rationale: this is the agreed operating point before the final stability-only experiments, preserving high recall.
- post-filter policy: `iforest_score_mean`, threshold `0.30`, aggregation `percentile_25`
- recall: `0.847619`
- precision: `0.681818`
- noise rejection: `0.681818`
- propagation order accuracy: `0.52381`
- cluster stability: `0.362903`
- 1C should treat this package as read-only and load it through the active alias under `shared_artifacts/correlation_engine`.
- 1C must not append `chaos_template`, `chaos_execution_plan`, or `replay_metadata` to the exported runtime event.
