# Industrial Sandbox ML Training v0.1

## Purpose
This repository hosts block `1B` of the industrial anomaly-detection sandbox: the offline, reproducible, and contract-oriented ML training lane for `Isolation Forest`.

It is intentionally separated from the operational baseline in:

- `/mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_v0_1`

The scope of this repository is to build the persistent assets required for dataset generation, dataset auditing, model training, evaluation, threshold calibration, artifact packaging, and future reintegration into the operational detector.

## Working Rules
- Preserve the validated `1A` runtime baseline and do not move its current scaffold.
- Build all `1B` work inside this repository: `/mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_ml_training_v0_1`.
- Keep the implementation `spec-driven` and `contract-oriented`.
- Use the validated `1A` datasets as the mandatory structural reference.
- Treat notebooks as persistent engineering assets, not optional scratchpads.
- Use shell commands for ephemeral work, but persist durable logic in source code, scripts, contracts, and notebooks.
- Use `uv` as the primary Python workflow tool for environment creation, dependency sync, and command execution.

## Reference Inputs from 1A
- Reference operational repo: `/mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_v0_1`
- Reference telemetry contract: `contracts/telemetry_event_v0_1.json`
- Reference export datasets: `data/synthetic/`
- Reference scenarios:
  - `training_normal_v1`
  - `validation_mixed_v1`

## Frozen Feature Contract
The `Isolation Forest` baseline in block `1B` is frozen to these eight numeric features:

- `cpu_pct`
- `memory_pct`
- `latency_ms`
- `disk_io_pct`
- `net_error_rate`
- `queue_length`
- `throughput_rate`
- `http_5xx_rate`

`scenario_tag` remains a label/audit field and is not part of the model feature vector.

## Repository Layout
```text
industrial_sandbox_ml_training_v0_1/
├── README.md
├── .env
├── .env.example
├── requirements.txt
├── configs/
│   ├── dataset_profiles/
│   ├── training/
│   └── evaluation/
├── contracts/
├── data/
│   ├── raw/
│   ├── interim/
│   ├── processed/
│   └── audits/
├── artifacts/
│   ├── models/
│   ├── metrics/
│   └── reports/
├── docs/
├── notebooks/
├── scripts/
└── src/
    └── utils/
```

## Python Workflow
This repository is now `uv-first`.

That means:
- `uv` is the primary tool for Python environment operations
- `pyproject.toml` is the authoritative dependency definition
- `requirements.txt` is kept only as a compatibility fallback surface

## Bootstrap
```bash
cd /mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_ml_training_v0_1
bash scripts/bootstrap_uv.sh
```

Note:
- on this WSL + `/mnt/e` filesystem, creating `.venv` inside the repo fails because virtualenv creation needs symlinks that are not permitted on the mounted drive
- the official operational pattern is therefore:
  - keep the repo, datasets, notebooks, manifests, and reports inside `/mnt/e/...`
  - keep the `uv` virtual environment and cache under `/tmp`

Equivalent manual bootstrap:
```bash
cd /mnt/e/CODING-2026-heavy/anomaly-detection-iforest-docker/industrial_sandbox_ml_training_v0_1
env UV_CACHE_DIR=/tmp/uv-cache uv venv /tmp/industrial_sandbox_ml_training_v0_1_venv --python 3.10
source /tmp/industrial_sandbox_ml_training_v0_1_venv/bin/activate
export UV_PROJECT_ENVIRONMENT=/tmp/industrial_sandbox_ml_training_v0_1_venv
env UV_CACHE_DIR=/tmp/uv-cache uv sync --active --no-install-project
```

Recommended shell state after activation:
```bash
export UV_CACHE_DIR=/tmp/uv-cache
export UV_PROJECT_ENVIRONMENT=/tmp/industrial_sandbox_ml_training_v0_1_venv
```

## First Commands
```bash
source /tmp/industrial_sandbox_ml_training_v0_1_venv/bin/activate
export UV_CACHE_DIR=/tmp/uv-cache
export UV_PROJECT_ENVIRONMENT=/tmp/industrial_sandbox_ml_training_v0_1_venv
uv run --active python scripts/generate_dataset.py --profile training_normal_v1
uv run --active python scripts/generate_dataset.py --profile validation_mixed_v1
```

These commands now generate real offline datasets, plus a manifest and a short generation report for each run.

## Calibration Commands
```bash
uv run --active python scripts/evaluate_iforest.py data/processed/validation_mixed_v1.parquet --threshold 0.695655885893105 --output-prefix validation_shadow_balanced
uv run --active python scripts/sweep_thresholds.py artifacts/metrics/validation_precalibration_scores.parquet
uv run --active python scripts/sweep_contamination.py
uv run --active python scripts/diagnose_decision_policy.py
```

Current note:
- `shadow_threshold_balanced_v1` is the active shadow candidate profile.
- the current pipeline uses `score_samples` plus an external threshold, so changing `contamination` alone does not move the evaluated operating metrics; it only changes persisted hyperparameter metadata unless the scoring policy changes too.
- current diagnostics show the biggest improvement comes from service-specific thresholding, not from switching `score_samples` to `decision_function`.

## Promotion To 1A
The current promoted detector policy lives under `artifacts/promoted/detector_policy/shadow_threshold_service_v1/`.

Promotion rule:
- `1B` discovers and validates.
- `1A` executes the validated detector policy.

The promoted bundle includes:
- `iforest_detector_policy_v1.json`
- `active_detector_policy.json`
- `model.joblib`
- `feature_contract.json`
- `training_manifest.json`
- `validation_metrics.json`
- `manifest.json`
- `promotion_notes.md`

The current runtime policy is:
- scoring policy: `score_samples`
- threshold mode: `service_specific`
- `checkout-api`: `0.691832591180323`
- `orders-api`: `0.6712653569641552`
- `payments-api`: `0.7016270755997039`
- `min_flag_window`: `3`

This promotion is intended to be consumed from the shared stable zone at `../shared_artifacts/detector_policy/`, with `active_detector_policy.json` acting as the canonical alias for future swaps.

Architectural runtime rule:
- `1A` loads the alias, resolved detector policy, and promoted model once at startup.
- runtime inference uses in-memory cached objects only.
- `1A` must not reread policy/model artifacts per inference.
- controlled reload is allowed only through restart or an explicit internal reload path.
