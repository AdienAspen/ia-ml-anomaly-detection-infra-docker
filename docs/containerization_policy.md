# Containerization Policy

## Scope

This repository separates long-running operational runtime from offline training and research workflows.

## Runtime Services

The following components should run as containerized services inside the shared `docker-compose` topology when they participate in the live observability flow:

- `telemetry-generator`
- `redis`
- `anomaly-detector`
- `correlation-bridge`
- `agentic-layer`
- `otel-collector`

A component belongs in the runtime container set when it:

- runs continuously
- consumes or publishes network events
- requires health monitoring
- participates in shadow, pre-production, or operator-facing flows

## Offline / Training Components

The following components remain outside the runtime compose by design:

- iForest training and validation jobs
- HDBSCAN training and validation labs
- feature engineering experiments
- artifact promotion workflows
- ad hoc reports and notebooks

These components are reproducible, but they are not required to stay alive as network services.

## Design Rule

Runtime services should communicate at the same operational level.
If one live service feeds another, both sides should expose stable runtime contracts, health checks, and predictable container networking.

## Current Runtime Flow

`telemetry-generator -> redis telemetry.raw -> anomaly-detector -> telemetry.anomaly.stream -> correlation-bridge -> enriched.correlation.stream -> agentic-layer`

## Notes

- Redis Pub/Sub may remain acceptable for raw synthetic telemetry ingress.
- Redis Streams are the preferred transport for downstream detector, correlation, and agentic handoff.
- Shared artifacts under `shared_artifacts/` are treated as read-only runtime inputs.
- Continuous runtime outputs such as `jsonl` and `csv` logs should stay out of Git unless they are curated snapshots.
- Evidence worth preserving should be promoted into `reports/archive/` or summarized in Markdown.
## Validation

Use the runtime smoke to validate container health plus end-to-end stream advancement:

```bash
cd industrial_sandbox_v0_1
python3 scripts/run_runtime_flow_smoke.py
```
