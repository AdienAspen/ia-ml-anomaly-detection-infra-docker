# Anomaly Propagation Detection System – ML Correlation Engine

[![Python](https://img.shields.io/badge/python-3.9+-blue?logo=python)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-%2320232a?logo=docker&logoColor=%2361DAFB)](https://www.docker.com/)
[![Redis](https://img.shields.io/badge/redis-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Machine Learning](https://img.shields.io/badge/ML-Anomaly%20Detection-orange)](https://scikit-learn.org/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-419EDA?logo=opentelemetry&logoColor=white)](https://opentelemetry.io/)

## Overview

This repository contains a **proof-of-concept anomaly propagation detection system** for simulated distributed services, focused on `payments`, `checkout`, `orders`, and `Redis`. It combines an **Isolation Forest** for anomaly scoring with a **temporal HDBSCAN correlation engine** for identifying propagation signatures across services. The platform is built around synthetic telemetry, Redis-based event flow, containerized runtime services, and an agentic layer for contextual reasoning and auditability.

The project demonstrates a **contract-driven pipeline** that starts with reproducible synthetic telemetry, scores anomalous behavior per service, correlates temporal propagation patterns, and emits enriched events that can be consumed by higher-level reasoning components. It is designed as the first stage of a broader roadmap that will continue evolving in observability depth, runtime maturity, orchestration, and resilience.

This phase is nearing completion and now includes not only the core ML correlation path, but also the first stable version of the **event bus, context engine, reasoning layer, audit/policy layer, and runtime container leveling**. The next immediate focus is to close this stage by incorporating the most important technical audit recommendations and strengthening OpenTelemetry so it becomes a true first-class observability component rather than a lightly wired foundation.

---

## Key Features

- **Dual ML pipeline**  
  Isolation Forest scores anomalous service behavior, while temporal HDBSCAN clusters correlated propagation behavior across windows and services.

- **Synthetic telemetry generator**  
  The system generates deterministic synthetic telemetry scenarios with configurable causal rules, lag, jitter, intensity, and recovery behavior.

- **Feature engineering evolution**  
  The HDBSCAN pipeline evolved from a broader feature space toward a more refined and interpretable feature set, improving practical detection quality while exposing the trade-off between precision/recall and cluster stability.

- **Event-driven runtime**  
  Redis is used as the runtime bus with a mix of Pub/Sub and Streams:
  - raw telemetry ingress
  - detector signal streaming
  - enriched anomaly event streaming
  - context slice publication

- **Agentic layer MVP**  
  The repository includes an MVP implementation of:
  - event bus abstraction
  - context engine
  - reasoning outputs
  - tool/skill layer
  - audit and policy bundle generation

- **Containerized runtime topology**  
  Long-running operational services run through Docker Compose:
  - `telemetry-generator`
  - `redis`
  - `anomaly-detector`
  - `correlation-bridge`
  - `agentic-layer`
  - `otel-collector`

- **Observability foundation**  
  OpenTelemetry, Jaeger-oriented observability patterns, and a future Temporal-style orchestration direction are part of the intended architecture and are being incorporated progressively as the project matures.

- **Contract-driven development**  
  JSON Schemas and explicit runtime contracts are used to validate major payloads such as enriched events, context slices, incident outputs, confidence vectors, and audit traces.

---

## Repository Structure

### Active Branches

- **`main`**  
  The current canonical branch. It reflects the latest integrated state of the project, including the completed 1C agentic-layer sprint, runtime leveling, and end-to-end validation work.

- **`feature/refactor-hdbscan-v_02`**  
  Historical branch preserved intentionally. It captures the HDBSCAN refactor and experimentation cycle that materially improved the ML correlation engine and led to one of the most important technical outcomes of this project: **high precision and high recall at the cost of still-limited cluster stability**.

### Why the Historical Branch Is Preserved

This branch remains available because it documents a meaningful transition in the project’s ML evolution rather than a disposable feature branch. It preserves the experimentation path that produced the refined correlation artifacts and the operating point that later fed the agentic runtime.

It also serves as a reproducible historical reference for understanding how the project moved from earlier HDBSCAN iterations into the current shared-artifact and correlation-engine packaging model. For technical reviewers, it is the clearest record of the refactor that turned the correlation engine into a more credible and reusable subsystem.

---

## Key Results and Trade-offs

| Metric | Value | Notes |
|---|---:|---|
| Recall (propagation detection) | 0.85 | Maintained at a strong level after post-filtering |
| Precision | 0.68 | Significant improvement after post-filtering |
| Cluster stability | 0.36 | Still a known weakness and an explicit next-step target |
| Propagation order accuracy | 0.52 | Functional, but still in need of temporal refinement |
| Training eligible windows | 413 | Based on filtered, quality-gated windows |
| Validation eligible windows | 215 | Derived from the selected operating point |

The project demonstrates that a combined **Isolation Forest + HDBSCAN + post-filtering** approach is viable for anomaly propagation detection in distributed systems. The current trade-off is clear: **strong precision and recall were achieved before solving stability as a first-class concern**. That trade-off is intentional, visible, and documented.

---

## Runtime Architecture

The current runtime flow is:

`telemetry-generator -> redis telemetry.raw -> anomaly-detector -> telemetry.anomaly.stream -> correlation-bridge -> enriched.correlation.stream -> agentic-layer`

This leveled runtime architecture separates:
- **live operational services**, which run in containers
- **offline training and artifact generation**, which remain outside the runtime path

That distinction keeps the runtime simpler, more observable, and easier to validate end-to-end.

---

## Getting Started

### 1. Clone the repository

```bash
git clone git@github.com:AdienAspen/ia-ml-anomaly-detection-infra-docker.git
cd ia-ml-anomaly-detection-infra-docker
```

### 2. Start the runtime environment

```bash
cd industrial_sandbox_v0_1
docker compose up --build
```

This starts the current long-running runtime services:
- telemetry generator
- Redis
- anomaly detector
- correlation bridge
- agentic layer
- OpenTelemetry collector

### 3. Run the offline HDBSCAN training workflow

```bash
cd ../industrial_sandbox_HDBSCAN_training_v0_1
python3 scripts/train_hdbscan_temporal_v_02.py
```

Artifacts are written to the corresponding `artifacts/` directories.

### 4. Run the runtime validation smoke

```bash
cd ../industrial_sandbox_v0_1
python3 scripts/run_runtime_flow_smoke.py
```

### 5. Run the golden-path end-to-end scenario

```bash
python3 scripts/run_golden_path_e2e.py
```

This validates a short, deterministic end-to-end path from raw telemetry publication to:
- detector signal
- enriched anomaly event
- final context slice

---

## Technology Stack

- **Language**
  - Python

- **Machine Learning**
  - scikit-learn
  - HDBSCAN
  - NumPy

- **Observability**
  - OpenTelemetry
  - Jaeger-oriented observability path

- **Messaging and Runtime State**
  - Redis Pub/Sub
  - Redis Streams

- **Orchestration Direction**
  - Docker Compose
  - Temporal-oriented future workflow integration

- **Validation and Testing**
  - `unittest`
  - JSON Schema validation
  - runtime smoke tests
  - golden-path end-to-end validation

- **Version Control / Delivery**
  - GitHub
  - GitLab

---

## Audit Status

This project has undergone a multi-layer technical audit covering:
- ML detection
- context engine
- reasoning layer
- tools layer
- audit and policy
- chaos readiness

The audit outcome was **conditionally approved as a POC**, with the strongest maturity in the ML and correlation layers and the most important pending work concentrated in:
- reasoning integrity
- orchestration completeness
- graceful error handling
- observability hardening
- stronger enforcement in policy/runtime layers

Those findings are now part of the planned closing work for this stage.

---

## Roadmap

The next milestones include:

- strengthening OpenTelemetry as a first-class observability layer
- addressing the highest-priority audit findings
- improving graceful shutdown and runtime error handling
- refining correlation quality and clustering evaluation
- expanding orchestration and agent runtime maturity
- preparing future stages with richer streaming and distributed execution patterns

---

## Contributing

This repository is part research platform, part engineering sandbox, and part architectural learning artifact. Contributions, discussions, and technical review are welcome.

If you want to collaborate, review the current branch structure, inspect the runtime topology, and open an issue or discussion with concrete suggestions.

---

Built with curiosity, reproducibility, and engineering discipline.
