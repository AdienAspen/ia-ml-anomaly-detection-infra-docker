# Feature Stability Analysis Report

- bootstrap_iterations: 12
- eligible_window_count: 35
- baseline_mean_cluster_stability: 0.537932

## Per-Feature Impact
| feature | with_feature | without_feature | delta_without | classification |
|---|---:|---:|---:|---|
| error_rate_payments | 0.537932 | 0.518698 | -0.019234 | neutral |
| error_rate_orders | 0.537932 | 0.524255 | -0.013677 | neutral |
| latency_p95_payments | 0.537932 | 0.525777 | -0.012155 | neutral |
| delta_latency_orders | 0.537932 | 0.527196 | -0.010736 | neutral |
| iforest_score_mean | 0.537932 | 0.532228 | -0.005704 | neutral |
| window_anomaly_density | 0.537932 | 0.537932 | 0.0 | neutral |
| redis_latency | 0.537932 | 0.539349 | 0.001417 | neutral |
| lag_redis_to_checkout | 0.537932 | 0.54628 | 0.008348 | neutral |
| iforest_score_max | 0.537932 | 0.559273 | 0.021341 | neutral |
| iforest_score_spread | 0.537932 | 0.564073 | 0.026141 | neutral |
| redis_queue_depth | 0.537932 | 0.575435 | 0.037503 | destabilizer_or_redundant |
| lag_payments_to_redis | 0.537932 | 0.593529 | 0.055597 | destabilizer_or_redundant |
| latency_p95_checkout | 0.537932 | 0.598844 | 0.060912 | destabilizer_or_redundant |
| latency_p95_orders | 0.537932 | 0.607488 | 0.069556 | destabilizer_or_redundant |
| delta_latency_checkout | 0.537932 | 0.612936 | 0.075004 | destabilizer_or_redundant |
| error_rate_checkout | 0.537932 | 0.629492 | 0.09156 | destabilizer_or_redundant |
| service_degradation_order_encoded | 0.537932 | 0.635764 | 0.097832 | destabilizer_or_redundant |

## Interpretation
- `stabilizer`: removing the feature lowers mean cluster stability materially.
- `destabilizer_or_redundant`: removing the feature improves stability materially.
- `neutral`: removing the feature does not move stability enough to matter yet.