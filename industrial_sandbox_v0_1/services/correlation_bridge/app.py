import json
import os
import pickle
import threading
import time
from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis
from flask import Flask, jsonify

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
ANOMALY_STREAM = os.getenv("ANOMALY_STREAM", "telemetry.anomaly.stream")
ENRICHED_STREAM = os.getenv("ENRICHED_STREAM", "enriched.correlation.stream")
STREAM_START_ID = os.getenv("CORRELATION_STREAM_START_ID", "$")
STREAM_BLOCK_MS = int(os.getenv("CORRELATION_STREAM_BLOCK_MS", "5000"))
WINDOW_SIZE = int(os.getenv("CORRELATION_WINDOW_SIZE", "12"))
HEARTBEAT_PATH = Path(os.getenv("CORRELATION_HEARTBEAT_PATH", "/tmp/correlation_bridge_heartbeat"))
REPORT_PATH = Path(os.getenv("CORRELATION_REPORT_PATH", "/app/reports/enriched_correlation_events.jsonl"))
ALIAS_PATH = Path(
    os.getenv(
        "CORRELATION_ALIAS_PATH",
        "/app/shared_artifacts/correlation_engine/active_correlation_engine.json",
    )
)
SERVICE_ORDER = ["payments-api", "orders-api", "checkout-api"]
TOPOLOGY_SERVICE_MAP = {
    "payments": "payments-api",
    "orders": "orders-api",
    "checkout": "checkout-api",
}

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
app = Flask(__name__)
state_lock = threading.RLock()
service_buffers: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
state: dict[str, Any] = {
    "status": "starting",
    "redis_connected": False,
    "model_loaded": False,
    "events_seen": 0,
    "events_published": 0,
    "last_input_id": None,
    "last_output_id": None,
    "last_event_id": None,
    "last_signature_id": None,
    "last_policy_reload_at": None,
    "policy_name": None,
    "policy_path": None,
}


class CorrelationRuntime:
    def __init__(self, alias_path: Path) -> None:
        self.alias_path = alias_path
        self.policy: dict[str, Any] = {}
        self.policy_path: Path | None = None
        self.feature_contract: dict[str, Any] = {}
        self.topology: dict[str, Any] = {}
        self.model_package: dict[str, Any] = {}
        self.scenario_profiles: dict[str, dict[str, Any]] = {}
        self.post_filter_threshold = 0.3
        self.post_filter_aggregation = "percentile_25"
        self.kept_cluster_ids: set[int] = set()

    def load(self) -> None:
        alias_payload = _load_json(self.alias_path)
        if alias_payload.get("schema_version") == "correlation_engine_alias_v1":
            policy_path = (self.alias_path.parent / alias_payload["active_policy_path"]).resolve()
        else:
            policy_path = self.alias_path.resolve()
        self.policy = _load_json(policy_path)
        self.policy_path = policy_path
        package_root = policy_path.parent
        self.feature_contract = _load_json(package_root / self.policy["feature_contract"])
        self.topology = _load_json(package_root / "topology_graph_v_02.json")
        with (package_root / self.policy["model_artifact"]).open("rb") as handle:
            self.model_package = pickle.load(handle)
        post_filter = self.policy.get("post_filter", {})
        self.post_filter_threshold = float(post_filter.get("effective_threshold", 0.3))
        self.post_filter_aggregation = str(post_filter.get("aggregation", "percentile_25"))
        self.kept_cluster_ids = {int(item) for item in post_filter.get("kept_cluster_ids", [])}
        self.scenario_profiles = _build_scenario_profiles(
            assignments=self.model_package.get("assignments", []),
            kept_cluster_ids=self.kept_cluster_ids,
        )
        with state_lock:
            state["model_loaded"] = True
            state["policy_name"] = self.policy.get("policy_name")
            state["policy_path"] = str(self.policy_path)
            state["last_policy_reload_at"] = _utc_now_iso()
            state["status"] = "ready"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _percentile_25(values: list[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = 0.25 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _build_scenario_profiles(assignments: list[dict[str, Any]], kept_cluster_ids: set[int]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in assignments:
        cluster_id = item.get("cluster_id")
        scenario_tag = item.get("scenario_tag")
        if cluster_id is None or scenario_tag is None:
            continue
        if kept_cluster_ids and int(cluster_id) not in kept_cluster_ids:
            continue
        grouped[str(scenario_tag)].append(item)

    profiles: dict[str, dict[str, Any]] = {}
    for scenario_tag, items in grouped.items():
        cluster_counts = Counter(int(item["cluster_id"]) for item in items)
        dominant_cluster, sample_count = cluster_counts.most_common(1)[0]
        strengths = [float(item.get("cluster_strength", 0.0)) for item in items if int(item["cluster_id"]) == dominant_cluster]
        mean_strength = sum(strengths) / len(strengths) if strengths else 0.0
        profiles[scenario_tag] = {
            "cluster_id": dominant_cluster,
            "cluster_strength": round(mean_strength, 6),
            "sample_count": sample_count,
        }
    return profiles


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _touch_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _service_snapshot() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for service_name, buffer in service_buffers.items():
        if buffer:
            latest[service_name] = buffer[-1]
    return latest


def _observed_services(snapshot: dict[str, dict[str, Any]]) -> list[str]:
    observed = [service for service in SERVICE_ORDER if service in snapshot]
    if observed:
        observed.append("redis")
    return observed


def _window_quality(snapshot: dict[str, dict[str, Any]]) -> float:
    coverage = len(snapshot) / len(SERVICE_ORDER)
    timestamps = [
        _parse_dt(item.get("scored_at") or item.get("generated_at"))
        for item in snapshot.values()
    ]
    timestamps = [value for value in timestamps if value is not None]
    if len(timestamps) >= 2:
        freshness_span = (max(timestamps) - min(timestamps)).total_seconds()
        freshness_score = 1.0 if freshness_span <= 45 else 0.75 if freshness_span <= 90 else 0.5
    else:
        freshness_score = 0.7
    return round(_clamp((coverage * 0.65) + (freshness_score * 0.35), 0.0, 1.0), 6)


def _lag_pattern(snapshot: dict[str, dict[str, Any]], primary_service: str, scenario_tag: str) -> dict[str, int]:
    latest_times = {
        service: _parse_dt(item.get("scored_at") or item.get("generated_at"))
        for service, item in snapshot.items()
    }
    primary_dt = latest_times.get(primary_service)

    def seconds_between(left: str, right: str, default: int = 15) -> int:
        left_dt = latest_times.get(left)
        right_dt = latest_times.get(right)
        if left_dt is None or right_dt is None:
            return default
        return max(0, int(abs((right_dt - left_dt).total_seconds()))) or default

    if scenario_tag == "S2_SERVICE_TO_REDIS_PROPAGATION":
        queue_proxy = max(
            float(item.get("telemetry_snapshot", {}).get("queue_length") or 0.0)
            for item in snapshot.values()
        )
        return {f"{primary_service}_to_redis": max(10, min(90, int(queue_proxy)))}
    if scenario_tag == "S3_REDIS_TO_MULTISERVICE_PROPAGATION":
        return {
            f"{primary_service}_to_redis": 20,
            "redis_to_checkout-api": seconds_between(primary_service, "checkout-api", 30),
        }
    if scenario_tag == "S4_INTERSERVICE_CHAIN":
        return {
            f"{primary_service}_to_redis": 20,
            "redis_to_checkout-api": seconds_between(primary_service, "checkout-api", 25),
            "checkout-api_to_orders-api": seconds_between("checkout-api", "orders-api", 20),
        }
    if primary_dt is None:
        return {}
    return {}


def _infer_scenario(snapshot: dict[str, dict[str, Any]], anomalous_services: list[str]) -> str:
    queue_proxy = max(
        float(item.get("telemetry_snapshot", {}).get("queue_length") or 0.0)
        for item in snapshot.values()
    ) if snapshot else 0.0

    if {"payments-api", "checkout-api", "orders-api"}.issubset(set(anomalous_services)):
        return "S4_INTERSERVICE_CHAIN"
    if "payments-api" in anomalous_services and "checkout-api" in anomalous_services:
        return "S3_REDIS_TO_MULTISERVICE_PROPAGATION"
    if "payments-api" in anomalous_services and queue_proxy >= 30.0:
        return "S2_SERVICE_TO_REDIS_PROPAGATION"
    if len(anomalous_services) == 1:
        return "S1_LOCAL_ANOMALY_ONLY"
    return "S6_NOISE_FALSE_POSITIVE"


def _build_enriched_event(signal: dict[str, Any], message_id: str) -> dict[str, Any] | None:
    snapshot = _service_snapshot()
    if not snapshot:
        return None

    anomalous_services = [
        service
        for service, item in snapshot.items()
        if item.get("anomaly_flag") or item.get("candidate_flag") or item.get("iforest_label") == "anomalous"
    ]
    if not anomalous_services:
        return None

    iforest_scores = {service: round(float(item.get("anomaly_score", 0.0)), 6) for service, item in snapshot.items()}
    iforest_labels = {
        service: "anomalous" if service in anomalous_services else "normal"
        for service in snapshot
    }
    primary_service = max(iforest_scores, key=iforest_scores.get)
    scenario_tag = _infer_scenario(snapshot, anomalous_services)
    post_filter_score = _percentile_25(list(iforest_scores.values()))
    post_filter_pass = post_filter_score >= runtime.post_filter_threshold
    propagation_detected = post_filter_pass and scenario_tag in runtime.scenario_profiles and scenario_tag not in {"S1_LOCAL_ANOMALY_ONLY", "S6_NOISE_FALSE_POSITIVE"}
    scenario_profile = runtime.scenario_profiles.get(scenario_tag, {})
    cluster_id = scenario_profile.get("cluster_id") if propagation_detected else None
    confidence = round(
        _clamp(
            ((float(scenario_profile.get("cluster_strength", 0.35)) + min(1.0, post_filter_score)) / 2.0),
            0.0,
            1.0,
        ),
        6,
    )
    severity_seed = max(iforest_scores.values())
    if propagation_detected and severity_seed >= 0.85 and len(anomalous_services) >= 2:
        severity = "critical"
    elif propagation_detected or severity_seed >= 0.7:
        severity = "high"
    elif severity_seed >= 0.45:
        severity = "medium"
    else:
        severity = "low"

    raw_refs = [f"redis-stream://{ANOMALY_STREAM}/{message_id}"]
    raw_refs.extend(
        item.get("raw_event_ref")
        for item in snapshot.values()
        if item.get("raw_event_ref")
    )
    evidence_refs = [
        f"policy://detector/{snapshot[primary_service].get('detector_policy_name', 'unknown')}",
        f"policy://correlation/{runtime.policy.get('policy_name', 'unknown')}",
        f"scenario://{scenario_tag}",
    ]
    signature_id = None
    if cluster_id is not None:
        signature_id = f"prop_sig_cluster_{cluster_id}_{signal['event_id']}"

    timestamps = [
        _parse_dt(item.get("scored_at") or item.get("generated_at"))
        for item in snapshot.values()
    ]
    timestamps = [value for value in timestamps if value is not None]
    effective_timestamp = max(timestamps).isoformat().replace("+00:00", "Z") if timestamps else _utc_now_iso()

    return {
        "schema_version": "enriched_anomaly_event_v0_1",
        "event_id": signal["event_id"],
        "timestamp": effective_timestamp,
        "source": "correlation_bridge_hdbscan_v1",
        "services_observed": _observed_services(snapshot),
        "primary_service": primary_service,
        "iforest_scores": iforest_scores,
        "iforest_labels": iforest_labels,
        "correlation_engine": {
            "enabled": True,
            "model": runtime.policy.get("policy_name", "hdbscan_production_v1"),
            "propagation_signature_id": signature_id,
            "propagation_detected": propagation_detected,
            "lag_pattern_seconds": _lag_pattern(snapshot, primary_service, scenario_tag),
            "confidence": confidence,
        },
        "window_data_quality_score": _window_quality(snapshot),
        "severity_preliminary": severity,
        "evidence_refs": evidence_refs,
        "raw_event_refs": [item for item in raw_refs if item],
    }


def consume() -> None:
    last_id = STREAM_START_ID
    with state_lock:
        state["redis_connected"] = True
    while True:
        response = redis_client.xread({ANOMALY_STREAM: last_id}, count=1, block=STREAM_BLOCK_MS)
        if not response:
            _touch_heartbeat(HEARTBEAT_PATH)
            continue

        for _, messages in response:
            for message_id, fields in messages:
                payload = json.loads(fields["payload"])
                last_id = str(message_id)
                service_name = payload.get("service_name")
                if service_name in SERVICE_ORDER:
                    service_buffers[service_name].append(payload)
                with state_lock:
                    state["events_seen"] += 1
                    state["last_input_id"] = str(message_id)
                    state["last_event_id"] = payload.get("event_id")
                enriched = _build_enriched_event(payload, str(message_id))
                if enriched is None:
                    _touch_heartbeat(HEARTBEAT_PATH)
                    continue
                output_id = redis_client.xadd(ENRICHED_STREAM, {"payload": json.dumps(enriched, sort_keys=True)})
                _append_jsonl(REPORT_PATH, enriched)
                with state_lock:
                    state["events_published"] += 1
                    state["last_output_id"] = str(output_id)
                    state["last_signature_id"] = enriched["correlation_engine"]["propagation_signature_id"]
                _touch_heartbeat(HEARTBEAT_PATH)
                print(json.dumps(enriched), flush=True)


@app.get("/health")
def health() -> tuple:
    redis_ok = False
    try:
        redis_ok = bool(redis_client.ping())
    except redis.RedisError:
        redis_ok = False

    with state_lock:
        payload = {
            "status": "ok" if redis_ok and state["model_loaded"] else "degraded",
            "redis_connected": state["redis_connected"],
            "redis_ping": redis_ok,
            "model_loaded": state["model_loaded"],
            "events_seen": state["events_seen"],
            "events_published": state["events_published"],
            "last_input_id": state["last_input_id"],
            "last_output_id": state["last_output_id"],
            "last_event_id": state["last_event_id"],
            "last_signature_id": state["last_signature_id"],
            "policy_name": state["policy_name"],
            "policy_path": state["policy_path"],
            "input_stream": ANOMALY_STREAM,
            "output_stream": ENRICHED_STREAM,
            "window_size": WINDOW_SIZE,
            "post_filter_threshold": runtime.post_filter_threshold,
            "post_filter_aggregation": runtime.post_filter_aggregation,
            "observed_services": sorted(service_buffers.keys()),
        }
    return jsonify(payload), 200 if payload["status"] == "ok" else 503


runtime = CorrelationRuntime(ALIAS_PATH)
runtime.load()

threading.Thread(target=consume, daemon=True).start()
app.run(host="0.0.0.0", port=8081)
