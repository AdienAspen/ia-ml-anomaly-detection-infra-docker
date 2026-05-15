# Observability Snapshot v0.1

## Minimum Logs
- telemetry event publication summary
- anomaly scoring summary
- detector policy version/path in anomaly decision logs
- Redis connectivity errors
- collector export status

## Minimum Metrics
- generated events per minute
- scored events per minute
- anomaly flag count
- end-to-end latency estimate
- detector startup load duration
- inference latency per scored event
- decision freshness from generated event to scored event
- process memory by service
- Redis queue transport errors

## Health Checks
- Redis responds to `PING`
- `anomaly-detector` returns `200 OK` on `/health`
- `telemetry-generator` updates heartbeat state
- `otel-collector` answers on `13133`

## Baseline SLO Observations
- event to score latency must be measurable
- throughput must be measurable per minute
- service error rate must be observable
- collector status must be inspectable locally before external backends are added
