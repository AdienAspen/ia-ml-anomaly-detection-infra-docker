# Shadow First Pass v1

## Purpose
Run the first operational shadow pass in `1A` against the promoted detector policy coming from `1B`.

This first pass is intentionally controlled and count-bound so we can validate runtime behavior before moving to longer or more realistic runs.

## Fixed Run Profile
- mode: `count-bound`
- target events: `5000`
- telemetry profile: `market_aware_v1`
- telemetry scenario: `validation_mixed_v1`
- telemetry interval seconds: `0`
- detector policy path: `/app/shared_artifacts/detector_policy/active_detector_policy.json`
- model version: `shadow_threshold_service_v1`
- scoring policy: `score_samples`
- threshold mode: `service_specific`
- min flag window: `3`

## Why This First Pass
- it keeps continuity with the earlier 1A audited baseline size
- it is fast enough for a first operational validation on the new node
- it gives a controlled read on residual service imbalance across:
  - `payments-api`
  - `orders-api`
  - `checkout-api`

## Primary Question
Determine whether the residual imbalance observed after promotion is mainly explained by:
- generator behavior
- model behavior
- or realistic service heterogeneity

## Recommended Launch
```bash
cd /home/adien-i7-remote/workspace/anomaly-detection-iforest-docker/industrial_sandbox_v0_1
cp .env.shadow_first_pass_5000 .env
docker compose up --build
```

## Expected Outputs To Review After The Run
- `reports/detector_decisions.jsonl`
- exported telemetry under `data/synthetic/`
- container logs for:
  - `telemetry-generator`
  - `anomaly-detector`
  - `otel-collector`

## Operational Note
Do not change the detector policy locally in `1A` for this pass.
The goal is to validate the promoted runtime path exactly as it was handed off from `1B`.
