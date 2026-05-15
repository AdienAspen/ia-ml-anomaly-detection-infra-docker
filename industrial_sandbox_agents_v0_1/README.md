# Industrial Sandbox Agents v0.1

## Purpose
This repository hosts block `1C` of the industrial anomaly-detection sandbox: the agentic observability layer that consumes enriched anomaly events, prepares minimal context slices, reasons over operational evidence, and emits auditable recommendations.

## Design Intent
- keep detection in classical ML and deterministic components
- keep reasoning, explanation, confidence estimation, and recommendations in the agentic layer
- consume events through an abstraction layer, not through direct Redis calls spread across the codebase
- enforce read-only, allowlisted, human-in-the-loop operation in the MVP
- leave the tool layer `MCP-compatible` even when initial tools are local or mock-first

## MVP Boundaries
- no auto-remediation
- no destructive tools
- no free-form shell execution by the agent
- no secrets access
- no production mutations

## Repository Layout
```text
industrial_sandbox_agents_v0_1/
├── README.md
├── configs/
├── contracts/
├── docs/
├── reports/
├── scripts/
├── src/
└── tests/
```
