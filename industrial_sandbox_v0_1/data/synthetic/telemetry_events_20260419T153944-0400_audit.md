# Telemetry Export Audit - telemetry_events_20260419T153944-0400.csv

## Executive Summary
- total_samples: `5000`
- time_range_start: `2026-04-19T15:39:44.215297-04:00`
- time_range_end: `2026-04-19T15:42:02.001210-04:00`
- profiles_seen: `{'market_aware_v1': 5000}`
- services_seen: `{'payments-api': 1667, 'orders-api': 1667, 'checkout-api': 1666}`
- scenarios_seen: `{'normal': 4979, 'anomalous': 21}`
- source_nodes_seen: `{'node-01': 5000}`

## Missing Values
- No missing values detected in the exported rows.

## Feature Stats
| feature | min | mean | std | p05 | p50 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| cpu_pct | 31.657 | 48.097 | 5.094 | 39.981 | 48.083 | 56.485 | 63.632 |
| memory_pct | 37.047 | 48.156 | 3.581 | 42.153 | 48.206 | 53.924 | 59.588 |
| latency_ms | 45.966 | 112.978 | 19.541 | 80.884 | 112.930 | 145.083 | 167.735 |
| disk_io_pct | 20.669 | 28.704 | 2.662 | 24.269 | 28.795 | 32.901 | 36.494 |
| net_error_rate | 0.063 | 0.440 | 0.125 | 0.232 | 0.443 | 0.640 | 0.865 |
| queue_length | 27.519 | 53.592 | 8.904 | 39.331 | 53.557 | 68.168 | 79.254 |
| throughput_rate | 41.859 | 76.848 | 15.961 | 53.939 | 74.204 | 102.774 | 114.872 |
| http_5xx_rate | 0.059 | 0.978 | 0.305 | 0.472 | 0.978 | 1.472 | 2.085 |

## Top Correlations
- `net_error_rate` vs `http_5xx_rate`: `0.913`
- `queue_length` vs `http_5xx_rate`: `0.903`
- `latency_ms` vs `http_5xx_rate`: `0.896`
- `latency_ms` vs `queue_length`: `0.878`
- `latency_ms` vs `net_error_rate`: `0.802`
- `disk_io_pct` vs `throughput_rate`: `0.779`
- `net_error_rate` vs `queue_length`: `0.749`
- `cpu_pct` vs `disk_io_pct`: `0.647`

## Burst Indicators
- `payments-api`: samples=`1667`, burst_samples=`88`, burst_ratio=`0.053`, burst_runs=`59`, max_burst_run=`6`
- `orders-api`: samples=`1667`, burst_samples=`78`, burst_ratio=`0.047`, burst_runs=`56`, max_burst_run=`6`
- `checkout-api`: samples=`1666`, burst_samples=`93`, burst_ratio=`0.056`, burst_runs=`59`, max_burst_run=`5`

## Drift Indicators
- `payments-api`
  - `cpu_pct`: early_mean=`41.767`, late_mean=`47.814`, delta=`6.047`, relative_delta=`0.145`
  - `latency_ms`: early_mean=`101.269`, late_mean=`144.042`, delta=`42.773`, relative_delta=`0.422`
  - `queue_length`: early_mean=`44.913`, late_mean=`65.870`, delta=`20.956`, relative_delta=`0.467`
  - `http_5xx_rate`: early_mean=`0.743`, late_mean=`1.378`, delta=`0.635`, relative_delta=`0.854`
- `orders-api`
  - `cpu_pct`: early_mean=`47.897`, late_mean=`53.988`, delta=`6.091`, relative_delta=`0.127`
  - `latency_ms`: early_mean=`81.273`, late_mean=`121.427`, delta=`40.155`, relative_delta=`0.494`
  - `queue_length`: early_mean=`41.870`, late_mean=`62.165`, delta=`20.295`, relative_delta=`0.485`
  - `http_5xx_rate`: early_mean=`0.497`, late_mean=`1.097`, delta=`0.599`, relative_delta=`1.205`
- `checkout-api`
  - `cpu_pct`: early_mean=`45.896`, late_mean=`51.764`, delta=`5.868`, relative_delta=`0.128`
  - `latency_ms`: early_mean=`94.828`, late_mean=`135.027`, delta=`40.199`, relative_delta=`0.424`
  - `queue_length`: early_mean=`43.115`, late_mean=`63.165`, delta=`20.050`, relative_delta=`0.465`
  - `http_5xx_rate`: early_mean=`0.763`, late_mean=`1.366`, delta=`0.603`, relative_delta=`0.790`

## Readiness Notes
- This audit is a pilot check for Project `1B`, not a training evaluation.
- Use it to confirm service coverage, feature stability, burst presence, and early drift realism before large-scale export.
- For the full `~72k` target, compare these same indicators again after the long export run.
