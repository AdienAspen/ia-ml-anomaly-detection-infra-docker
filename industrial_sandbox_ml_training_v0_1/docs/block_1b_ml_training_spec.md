# Block 1B - ML Training Spec

## Scope
Block `1B` converts the validated synthetic telemetry behavior from `1A` into an offline MLDevOps lane for `Isolation Forest`.

This repository does not replace or move:

- `/mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_v0_1`

It extends the project by providing:

- reproducible dataset-generation assets
- dataset audit assets
- training and evaluation assets
- threshold calibration assets
- packaged model artifacts
- persistent engineering documentation

## Scaffold Decision
The suggested folder name `ml_training_iforest/` is not used as a new repo root.

Instead, the scaffold is implemented directly inside:

- `/mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_ml_training_v0_1`

This is now the canonical repository root for block `1B`.

## Notebook Policy
Notebooks are mandatory engineering assets in this block.

Use this policy:

- shell commands for ephemeral investigation, one-off validation, and temporary debugging
- source code, scripts, contracts, markdown docs, and Jupyter notebooks for logic that must persist, be audited, or be reused

This rule exists to avoid losing durable engineering logic inside transient shell history.

## Environment Note
This repository runs from WSL against a `/mnt/e/...` workspace.

In this filesystem layout, local virtual environments under the repo root may fail because venv creation tries to create symlinks that are not permitted on the mounted drive.

Operational workaround:

- use `uv` as the primary Python workflow tool
- create the execution venv under `/tmp`
- keep the project source, datasets, manifests, reports, and notebooks inside the repository
- keep `pyproject.toml` as the authoritative dependency definition for the block

## Alignment with 1A
The block `1B` feature contract is aligned with the current `1A` telemetry contract and `market_aware_v1` implementation.

Frozen numeric model features:

1. `cpu_pct`
2. `memory_pct`
3. `latency_ms`
4. `disk_io_pct`
5. `net_error_rate`
6. `queue_length`
7. `throughput_rate`
8. `http_5xx_rate`

Context and label fields retained for auditability:

- `service_name`
- `source_node`
- `generated_at`
- `status_code`
- `scenario_tag`
- `telemetry_profile`

## Dataset Targets
### Training
- dataset name: `training_normal_v1`
- target volume: `~72k` rows
- dominant class: `normal`
- balanced coverage across:
  - `payments-api`
  - `orders-api`
  - `checkout-api`

### Validation
- dataset name: `validation_mixed_v1`
- target volume: `~18k` rows
- controlled mix of:
  - normal
  - anomalous
  - bursts
  - drift
  - gradual degradation

## Delivery Expectations
This scaffold phase must leave behind:

- project layout
- environment defaults
- dependency lock surface through `requirements.txt`
- contracts and manifests
- starter configs
- script entrypoints
- starter notebooks

The next phase will implement the actual offline generator logic and the full training pipeline on top of this base.

## Current Calibration Note
The repository now includes:

- a persisted `shadow` threshold candidate based on the `balanced` operating profile
- a formal threshold sweep asset
- a formal contamination sweep asset

Important implementation detail:

- the current evaluation path uses `score_samples` plus an external anomaly threshold
- under this design, changing `contamination` does not materially affect the evaluated operating metrics
- therefore, future retuning must focus on thresholding policy, score policy, or model inputs, not on `contamination` alone

Current diagnostic result:

- global thresholding is the dominant source of cross-service imbalance in the current baseline
- switching from `score_samples` to `decision_function` did not materially change the operating metrics once thresholds were matched by false-positive target
- service-specific thresholding materially improved service homogeneity and anomaly recall in the current validation lane

## Promotion Rule To 1A
The next formal handoff from `1B` to `1A` follows an artifact-promotion pattern:

- `1B` discovers and validates the detector policy.
- `1A` consumes that policy as-is at runtime.
- `1A` must not hardcode new thresholds, recalibrate locally, or reinterpret the scoring policy.

The promoted runtime contract is versioned as `iforest_detector_policy_v1.json` and exposed through the canonical alias `active_detector_policy.json`.

The current promoted shadow profile is `shadow_threshold_service_v1` with:
- scoring policy: `score_samples`
- threshold mode: `service_specific`
- `checkout-api`: `0.691832591180323`
- `orders-api`: `0.6712653569641552`
- `payments-api`: `0.7016270755997039`
- `min_flag_window`: `3`

The stable promoted zone is `../shared_artifacts/detector_policy/`.

Architectural runtime rule for `1A`:
- consume promoted artifacts at startup
- cache model + policy in memory for runtime scoring
- never reread policy/model artifacts per inference
- allow only controlled reload through restart or explicit manual reload
