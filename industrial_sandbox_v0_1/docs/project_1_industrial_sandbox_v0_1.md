# Project 1 - Industrial Sandbox v0.1

## Purpose
Establish a Docker baseline for an industrial backend that generates, transports, scores, and observes synthetic infrastructure telemetry for early anomaly detection.

## Industrial Context
This project simulates an observability workload for a NOC/SRE team in a small or medium-sized company. The operational goal is to detect anomalous patterns in node and service telemetry before a visible degradation or incident occurs.

## Baseline Preservation
The original `simple` telemetry profile remains available as the baseline reference. This preserves the previous smoke behavior and keeps the pipeline compatible while the generator evolves behind explicit configuration.

## Iteration Scope
This refinement introduces a second telemetry profile named `market_aware_v1` while keeping the Docker baseline intact. The refined profile expands telemetry generation to three homogeneous API services:
- `payments-api`
- `orders-api`
- `checkout-api`

## Logical Architecture
- `telemetry-generator`: emits synthetic infrastructure events using `simple` or `market_aware_v1`.
- `queue-broker`: Redis baseline broker for decoupled transport.
- `anomaly-detector`: consumes telemetry, builds simple windows, and scores events using Isolation Forest.
- `otel-collector`: receives logs, metrics, and traces for baseline observability.

## Feature Contract
The current feature contract for model-facing telemetry is:
- `cpu_pct`
- `memory_pct`
- `latency_ms`
- `disk_io_pct`
- `net_error_rate`
- `queue_length`
- `throughput_rate`
- `http_5xx_rate`

The event payload still keeps `status_code` for operational compatibility and downstream observability.

## Feature Notes
- `cpu_pct`: host or workload CPU utilization percentage.
- `memory_pct`: memory utilization percentage.
- `latency_ms`: synthetic application latency in milliseconds.
- `disk_io_pct`: synthetic disk I/O pressure percentage.
- `net_error_rate`: synthetic transport/network error rate.
- `queue_length`: backlog proxy for pending work.
- `throughput_rate`: synthetic processed requests/work units per interval.
- `http_5xx_rate`: rate of server-side HTTP failures.

## Telemetry Profiles
### simple
Legacy baseline profile preserved for compatibility. Generates one service stream (`payments-api`) with lightweight Gaussian variation and the original mixed anomaly behavior.

### market_aware_v1
Refined profile that emits telemetry for `payments-api`, `orders-api`, and `checkout-api`, each with slightly different behavioral baselines.

The refined profile adds:
- light seasonality
- basic metric correlations
- service-specific patterns
- short bursts of elevated load
- gradual degradation under anomalous conditions

### Scenario Modes for `market_aware_v1`
The generator currently supports these scenario modes:
- `normal`: operational baseline with low stress.
- `anomalous`: mixed operational anomaly mode used for smoke and robustness checks.
- `training_normal_v1`: export-oriented mode for predominantly normal training data with only low residual anomaly pressure.
- `validation_mixed_v1`: export-oriented mixed validation mode with controlled bursts, drift, and anomalous segments.

## Data Flow
1. `telemetry-generator` creates synthetic events.
2. Events are published to Redis on the raw telemetry channel.
3. `anomaly-detector` consumes events, maintains a scoring window, and emits `anomaly_signal` records.
4. Logs and telemetry are exported to `otel-collector` for inspection and future expansion to Prometheus/Grafana.

## Dataset Export for 1B
The generator can optionally export telemetry events to CSV for downstream dataset preparation. Export is controlled through environment variables and is intended to prepare Project `1B`, not to replace runtime transport through Redis.

By default, export files are versioned per run with a timestamp suffix so each audit can target one isolated execution without mixing prior samples.

The generator also supports two completion modes:
- `time-bound`: stop after `TELEMETRY_RUN_DURATION_MINUTES`
- `count-bound`: stop after `TELEMETRY_MAX_EVENTS`

If `TELEMETRY_MAX_EVENTS > 0`, count-bound mode takes priority over run duration.

Expected exported fields include:
- `service_name`
- `source_node`
- `scenario_tag`
- `telemetry_profile`
- all current feature contract fields
- timestamps

### Pilot Export and Audit
Recommended pilot flow before a large `1B` export:
1. Run an export-enabled smoke or medium-duration controlled run.
2. Generate a short audit from the exported CSV.
3. Review:
   - service coverage balance
   - `normal` vs `anomalous` mix
   - feature ranges and percentiles
   - top correlations
   - burst indicators
   - early drift signals

Example pilot run:
```bash
cd /mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_v0_1
TELEMETRY_PROFILE=market_aware_v1 TELEMETRY_SCENARIO=validation_mixed_v1 TELEMETRY_EXPORT_ENABLED=true TELEMETRY_RUN_DURATION_MINUTES=20 docker compose up --build
```

Example count-bound training export:
```bash
cd /mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_v0_1
TELEMETRY_PROFILE=market_aware_v1 TELEMETRY_SCENARIO=training_normal_v1 TELEMETRY_EXPORT_ENABLED=true TELEMETRY_MAX_EVENTS=72000 TELEMETRY_INTERVAL_SECONDS=0 docker compose up --build
```

When the run finishes, the generator prints the exact `export_path` that was written, for example:
```json
{"status":"completed","completion_mode":"count_bound","events_published":72000,"target_events":72000,"run_duration_minutes":60.0,"telemetry_profile":"market_aware_v1","telemetry_scenario":"training_normal_v1","export_path":"/app/data/synthetic/telemetry_events_20260419T101500-0400.csv"}
```

Example audit:
```bash
cd /mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_v0_1
python3 scripts/audit_telemetry_export.py data/synthetic/telemetry_events_YYYYMMDDTHHMMSS-0400.csv
```

## Promoted Detector Policy
The current shadow runtime in `1A` must consume the detector policy promoted from `1B` instead of recalibrating locally.

Promotion rule:
- `1B` discovers and validates.
- `1A` executes the validated detector policy.

The active runtime contract is loaded through `DETECTOR_POLICY_PATH` and points to `../shared_artifacts/detector_policy/active_detector_policy.json`.

Architectural runtime rule:
- `1A` loads the alias, the resolved detector policy, and the promoted model once at service startup.
- runtime inference uses the in-memory cached objects only.
- `1A` must not reread policy or model artifacts on each inference.
- controlled reload is allowed only through service restart or the internal manual reload path.

The current promoted profile is `shadow_threshold_service_v1` with:
- scoring policy: `score_samples`
- threshold mode: `service_specific`
- `checkout-api`: `0.691832591180323`
- `orders-api`: `0.6712653569641552`
- `payments-api`: `0.7016270755997039`
- `min_flag_window`: `3`

`1A` must not hardcode replacement thresholds, switch score type independently, retrain the detector at runtime, or consult detector policy files per inference.

## 1A vs 1B Separation
### 1A covers
- pipeline robustness
- smoke tests
- duration control
- Redis transport
- health checks
- operational anomaly thresholds

### 1B will cover
- dataset use for training
- Isolation Forest tuning
- evaluation
- model artifact persistence
- reintegration of a trained artifact into the detector

## Target Metrics
- Stack startup time.
- End-to-end event to score latency.
- Events processed per minute.
- Error rate per service.
- Detector consistency over synthetic anomaly scenarios.
- Total stack memory footprint.

## Runtime Baseline
Docker Compose is the baseline runtime for Project 1. The stack uses one internal bridge network, bind mounts for artifacts/reports, and one named Redis volume.

## Future WASM Variant
Candidate workloads for WASM comparison:
- telemetry transformers
- feature extraction and preprocessing
- policy/filter engine
- lightweight inference if the model footprint allows it

## Future Unikernel Variant
Candidate workloads for unikernel comparison:
- specialized gateway/collector
- ultra-contained scoring service
- edge observability appliance

## Governance Notes
This project follows a spec-driven and contract-oriented approach. The contracts in `/contracts` define the minimum telemetry, anomaly, and observability expectations for the baseline and refined iterations.
