# Internal HDBSCAN Benchmark Report

## Executive Summary
- This report summarizes the current internal benchmark baseline for the temporal HDBSCAN correlation engine.
- Eligible training windows: 40
- Low-quality training windows excluded: 24
- Active feature count: 16

## Current Validation Snapshot
- propagation_detection_rate: 0.315789
- false_propagation_rate: 0.75
- noise_rejection_rate: 0.25
- propagation_order_accuracy: 0.526316
- cluster_stability: 0.333333

## Top Variance Features
| feature | variance | std_dev |
|---|---:|---:|
| service_degradation_order_encoded | 990962.91 | 995.4712 |
| latency_p95_payments | 1423.357917 | 37.727416 |
| latency_p95_orders | 673.552582 | 25.952892 |
| lag_payments_to_redis | 671.399375 | 25.911375 |
| latency_p95_checkout | 638.972015 | 25.277896 |

## Top Absolute Correlations
| left_feature | right_feature | pearson |
|---|---|---:|
| iforest_score_checkout | latency_p95_checkout | 0.980379 |
| iforest_score_payments | latency_p95_payments | 0.980245 |
| iforest_score_orders | latency_p95_orders | 0.970803 |
| error_rate_orders | latency_p95_orders | 0.935198 |
| error_rate_orders | iforest_score_orders | 0.92468 |

## Top Positive/Negative Contrast Features
| feature | positive_mean | negative_mean | relative_contrast |
|---|---:|---:|---:|
| lag_payments_to_redis | 22.0 | 2.954545 | 0.763206 |
| service_degradation_order_encoded | 513.5 | 1592.045455 | 0.51224 |
| lag_redis_to_checkout | 5.944444 | 2.454545 | 0.415514 |
| iforest_score_payments | 0.39861 | 0.342358 | 0.075916 |
| redis_queue_depth | 30.130456 | 25.945906 | 0.074622 |

## Interpretation Notes
- This block is exploratory and diagnostic, not a supervised feature-importance ranking.
- High variance or high correlation does not automatically mean high operational value.
- The next tuning cycle should use this report to reduce redundancy, inspect unstable dimensions and target recall loss with more evidence.
- PCA and autoencoders remain future options; they are intentionally not introduced in this baseline step.

## Statistical Baselining
- Baseline artifact: /home/adien-i7-remote/workspace/anomaly-detection-iforest-docker/industrial_sandbox_HDBSCAN_training_v0_1/artifacts/metrics/statistical_baseline_v0_1.json
- Training summary artifact: /home/adien-i7-remote/workspace/anomaly-detection-iforest-docker/industrial_sandbox_HDBSCAN_training_v0_1/artifacts/metrics/hdbscan_temporal_training_summary_v0_1.json
- Validation summary artifact: /home/adien-i7-remote/workspace/anomaly-detection-iforest-docker/industrial_sandbox_HDBSCAN_training_v0_1/artifacts/metrics/correlation_engine_validation_summary_v0_1.json