"""Testing helpers for local event-bus smoke validation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class FakeRedisStreams:
    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
        self._counter = 0

    def xadd(self, name: str, fields: dict[str, str]) -> str:
        self._counter += 1
        message_id = f"{self._counter}-0"
        self._streams[name].append((message_id, fields))
        return message_id

    def xread(
        self,
        streams: dict[str, str],
        count: int = 1,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
        del block
        results: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
        for stream_name, start_id in streams.items():
            messages = self._streams.get(stream_name, [])
            selected = [
                (message_id, fields)
                for message_id, fields in messages
                if _message_id_gt(message_id, start_id)
            ][:count]
            if selected:
                results.append((stream_name, selected))
        return results


def build_sample_enriched_anomaly_event(event_id: str = "evt-001") -> dict[str, Any]:
    return {
        "schema_version": "enriched_anomaly_event_v0_1",
        "event_id": event_id,
        "timestamp": "2026-05-19T10:00:00Z",
        "source": "event_intake_ml_detection",
        "services_observed": ["payments-api", "orders-api", "checkout-api", "redis"],
        "primary_service": "payments-api",
        "iforest_scores": {
            "payments-api": 0.91,
            "orders-api": 0.22,
            "checkout-api": 0.31,
        },
        "iforest_labels": {
            "payments-api": "anomalous",
            "orders-api": "normal",
            "checkout-api": "normal",
        },
        "correlation_engine": {
            "enabled": True,
            "model": "hdbscan_temporal",
            "propagation_signature_id": "prop_sig_001",
            "propagation_detected": True,
            "lag_pattern_seconds": {
                "payments-api_to_redis": 40,
                "redis_to_checkout-api": 30,
            },
            "confidence": 0.82,
        },
        "window_data_quality_score": 0.94,
        "severity_preliminary": "high",
        "evidence_refs": ["report://iforest/payments-api/evt-001"],
        "raw_event_refs": ["redis-stream://telemetry/1001-0"],
    }


def _message_id_gt(left: str, right: str) -> bool:
    return _parse_message_id(left) > _parse_message_id(right)


def _parse_message_id(value: str) -> tuple[int, int]:
    major, minor = value.split("-", maxsplit=1)
    return int(major), int(minor)
