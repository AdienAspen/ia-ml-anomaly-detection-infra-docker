# Telemetry Export Audit - telemetry_events_20260419T161247-0400.csv

## Executive Summary
- total_samples: `5000`
- time_range_start: `2026-04-19T16:12:47.462023-04:00`
- time_range_end: `2026-04-19T16:14:59.959505-04:00`
- profiles_seen: `{'market_aware_v1': 5000}`
- services_seen: `{'payments-api': 1667, 'orders-api': 1667, 'checkout-api': 1666}`
- scenarios_seen: `{'normal': 2771, 'anomalous': 2229}`
- source_nodes_seen: `{'node-01': 5000}`

## Missing Values
- No missing values detected in the exported rows.

## Feature Stats
| feature | min | mean | std | p05 | p50 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu_pct | 31.540 | 63.467 | 11.824 | 44.992 | 63.443 | 82.435 | 93.881 |
| memory_pct | 38.342 | 54.347 | 5.533 | 45.337 | 54.321 | 63.390 | 72.229 |
| latency_ms | 63.164 | 218.229 | 76.011 | 100.569 | 217.163 | 336.751 | 382.224 |
| disk_io_pct | 16.691 | 28.809 | 2.705 | 24.238 | 28.863 | 33.012 | 37.126 |
| net_error_rate | 0.087 | 0.989 | 0.398 | 0.366 | 0.992 | 1.608 | 2.153 |
| queue_length | 20.502 | 106.120 | 37.794 | 47.525 | 106.055 | 164.438 | 186.252 |
| throughput_rate | 0.000 | 54.582 | 22.237 | 18.816 | 54.346 | 93.279 | 115.865 |
| http_5xx_rate | 0.131 | 2.599 | 1.158 | 0.789 | 2.595 | 4.400 | 5.819 |

## Top Correlations
- `latency_ms` vs `queue_length`: `0.991`
- `latency_ms` vs `http_5xx_rate`: `0.988`
- `queue_length` vs `http_5xx_rate`: `0.987`
- `net_error_rate` vs `http_5xx_rate`: `0.984`
- `latency_ms` vs `net_error_rate`: `0.960`
- `net_error_rate` vs `queue_length`: `0.954`
- `cpu_pct` vs `queue_length`: `0.918`
- `cpu_pct` vs `http_5xx_rate`: `0.898`

## Burst Indicators
- `payments-api`: samples=`1667`, burst_samples=`89`, burst_ratio=`0.053`, burst_runs=`40`, max_burst_run=`10`
- `orders-api`: samples=`1667`, burst_samples=`90`, burst_ratio=`0.054`, burst_runs=`33`, max_burst_run=`11`
- `checkout-api`: samples=`1666`, burst_samples=`88`, burst_ratio=`0.053`, burst_runs=`43`, max_burst_run=`9`

## Drift Indicators
- `payments-api`
  - `cpu_pct`: early_mean=`45.185`, late_mean=`75.075`, delta=`29.890`, relative_delta=`0.661`
  - `latency_ms`: early_mean=`124.677`, late_mean=`333.063`, delta=`208.386`, relative_delta=`1.671`
  - `queue_length`: early_mean=`56.448`, late_mean=`159.905`, delta=`103.456`, relative_delta=`1.833`
  - `http_5xx_rate`: early_mean=`1.133`, late_mean=`4.258`, delta=`3.124`, relative_delta=`2.756`
- `orders-api`
  - `cpu_pct`: early_mean=`51.410`, late_mean=`81.312`, delta=`29.902`, relative_delta=`0.582`
  - `latency_ms`: early_mean=`102.721`, late_mean=`308.567`, delta=`205.847`, relative_delta=`2.004`
  - `queue_length`: early_mean=`52.629`, late_mean=`156.701`, delta=`104.072`, relative_delta=`1.977`
  - `http_5xx_rate`: early_mean=`0.851`, late_mean=`3.986`, delta=`3.135`, relative_delta=`3.683`
- `checkout-api`
  - `cpu_pct`: early_mean=`49.146`, late_mean=`79.298`, delta=`30.152`, relative_delta=`0.614`
  - `latency_ms`: early_mean=`116.764`, late_mean=`324.377`, delta=`207.613`, relative_delta=`1.778`
  - `queue_length`: early_mean=`53.812`, late_mean=`157.679`, delta=`103.867`, relative_delta=`1.930`
  - `http_5xx_rate`: early_mean=`1.125`, late_mean=`4.245`, delta=`3.120`, relative_delta=`2.774`

## Readiness Notes
- This audit is a pilot check for Project `1B`, not a training evaluation.
- Use it to confirm service coverage, feature stability, burst presence, and early drift realism before large-scale export.
- For the full `~72k` target, compare these same indicators again after the long export run.
