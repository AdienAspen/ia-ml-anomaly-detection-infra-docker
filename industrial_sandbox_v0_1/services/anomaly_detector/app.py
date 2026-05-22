import json
import os
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import joblib
import redis
from flask import Flask, jsonify, request

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "telemetry.raw")
ANOMALY_STREAM = os.getenv("ANOMALY_STREAM", "telemetry.anomaly.stream")
WINDOW_SIZE = int(os.getenv("DETECTOR_WINDOW_SIZE", "32"))
MODEL_NAME = os.getenv("MODEL_NAME", "isolation_forest")
MODEL_VERSION = os.getenv("MODEL_VERSION", "shadow_threshold_service_v1")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", os.getenv("TZ", "America/Santiago"))
DETECTOR_POLICY_PATH = Path(
    os.getenv("DETECTOR_POLICY_PATH", "/app/shared_artifacts/detector_policy/active_detector_policy.json")
)
DECISION_LOG_PATH = Path(os.getenv("DETECTOR_DECISION_LOG_PATH", "/app/reports/detector_decisions.jsonl"))
DETECTOR_RELOAD_TOKEN = os.getenv("DETECTOR_RELOAD_TOKEN", "")
DEFAULT_FEATURE_COLUMNS = (
    "cpu_pct",
    "memory_pct",
    "latency_ms",
    "disk_io_pct",
    "net_error_rate",
    "queue_length",
    "throughput_rate",
    "http_5xx_rate",
)

try:
    APP_TZ = ZoneInfo(APP_TIMEZONE)
except ZoneInfoNotFoundError:
    APP_TZ = ZoneInfo("UTC")


@dataclass(frozen=True)
class RuntimeSnapshot:
    policy: dict
    policy_path: Path
    model_path: Path
    model: object
    feature_columns: tuple[str, ...]
    service_thresholds: dict[str, float]
    min_flag_window: int
    schema_version: str
    loaded_at: str
    load_duration_ms: float
    load_count: int


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_policy(path: Path) -> tuple[dict, Path]:
    policy_ref = load_json(path)
    if policy_ref.get("schema_version") == "detector_policy_alias_v1":
        policy_path = (path.parent / policy_ref["active_policy_path"]).resolve()
        return load_json(policy_path), policy_path
    return policy_ref, path


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


class DetectorRuntimeCache:
    def __init__(self, policy_reference_path: Path) -> None:
        self.policy_reference_path = policy_reference_path
        self._lock = threading.RLock()
        self._snapshot: RuntimeSnapshot | None = None
        self._load_count = 0

    def load(self) -> RuntimeSnapshot:
        started = perf_counter()
        policy, policy_path = resolve_policy(self.policy_reference_path)
        model_path = (policy_path.parent / policy["model_path"]).resolve()
        model = joblib.load(model_path)
        load_duration_ms = (perf_counter() - started) * 1000
        self._load_count += 1
        snapshot = RuntimeSnapshot(
            policy=policy,
            policy_path=policy_path,
            model_path=model_path,
            model=model,
            feature_columns=tuple(policy.get("expected_features", DEFAULT_FEATURE_COLUMNS)),
            service_thresholds={key: float(value) for key, value in policy["threshold_by_service"].items()},
            min_flag_window=int(policy["min_flag_window"]),
            schema_version=policy["schema_version"],
            loaded_at=datetime.now(APP_TZ).isoformat(),
            load_duration_ms=load_duration_ms,
            load_count=self._load_count,
        )
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def get(self) -> RuntimeSnapshot:
        with self._lock:
            if self._snapshot is None:
                raise RuntimeError("Detector runtime has not been loaded.")
            return self._snapshot


runtime_cache = DetectorRuntimeCache(DETECTOR_POLICY_PATH)
runtime_snapshot = runtime_cache.load()

app = Flask(__name__)
state_lock = threading.RLock()
state = {
    "redis_connected": False,
    "events_seen": 0,
    "last_event_id": None,
    "last_scored_at": None,
    "policy_reference_path": str(DETECTOR_POLICY_PATH),
    "startup_loaded_at": runtime_snapshot.loaded_at,
    "startup_load_duration_ms": round(runtime_snapshot.load_duration_ms, 6),
    "last_policy_reload_at": runtime_snapshot.loaded_at,
    "last_policy_reload_duration_ms": round(runtime_snapshot.load_duration_ms, 6),
    "reload_count": runtime_snapshot.load_count,
    "inference_count": 0,
    "last_inference_latency_ms": None,
    "avg_inference_latency_ms": 0.0,
    "max_inference_latency_ms": 0.0,
    "last_decision_freshness_ms": None,
    "avg_decision_freshness_ms": None,
    "freshness_count": 0,
}
recent_flags_by_service = defaultdict(deque)
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
DECISION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def trim_window(window: deque, max_size: int) -> None:
    while len(window) > max_size:
        window.popleft()


def to_vector(event: dict, feature_columns: tuple[str, ...]) -> list[float]:
    return [float(event[column]) for column in feature_columns]


def record_metrics(inference_latency_ms: float, decision_freshness_ms: float | None) -> None:
    with state_lock:
        state["inference_count"] += 1
        count = state["inference_count"]
        previous_avg = state["avg_inference_latency_ms"]
        state["avg_inference_latency_ms"] = round(
            ((previous_avg * (count - 1)) + inference_latency_ms) / count,
            6,
        )
        state["last_inference_latency_ms"] = round(inference_latency_ms, 6)
        state["max_inference_latency_ms"] = round(
            max(state["max_inference_latency_ms"], inference_latency_ms),
            6,
        )
        if decision_freshness_ms is not None:
            freshness_count = state["freshness_count"] + 1
            previous_freshness_avg = state["avg_decision_freshness_ms"] or 0.0
            state["avg_decision_freshness_ms"] = round(
                ((previous_freshness_avg * state["freshness_count"]) + decision_freshness_ms) / freshness_count,
                6,
            )
            state["last_decision_freshness_ms"] = round(decision_freshness_ms, 6)
            state["freshness_count"] = freshness_count


def score_event(event: dict) -> dict:
    snapshot = runtime_cache.get()
    infer_started = perf_counter()
    vector = [to_vector(event, snapshot.feature_columns)]
    score = float(-snapshot.model.score_samples(vector)[0])
    inference_latency_ms = (perf_counter() - infer_started) * 1000

    service_name = event.get("service_name", "unknown-service")
    threshold = snapshot.service_thresholds.get(service_name, max(snapshot.service_thresholds.values()))
    window_limit = max(WINDOW_SIZE, snapshot.min_flag_window * 4)

    with state_lock:
        recent_flags = recent_flags_by_service[service_name]
        candidate_flag = score >= threshold
        recent_flags.append(candidate_flag)
        trim_window(recent_flags, window_limit)
        trailing_window = list(recent_flags)[-snapshot.min_flag_window:]

    persistent_flag = len(trailing_window) >= snapshot.min_flag_window and all(trailing_window)

    if len(trailing_window) < snapshot.min_flag_window:
        reasons = ["stabilizing_window"]
    elif persistent_flag:
        reasons = ["service_threshold_breach", "persistent_window"]
    elif candidate_flag:
        reasons = ["service_threshold_breach", "awaiting_window_confirmation"]
    else:
        reasons = ["within_expected_range"]

    scored_at_dt = datetime.now(APP_TZ)
    generated_at_dt = parse_datetime(event.get("generated_at"))
    decision_freshness_ms = None
    if generated_at_dt is not None:
        decision_freshness_ms = max(0.0, (scored_at_dt - generated_at_dt).total_seconds() * 1000)

    record_metrics(inference_latency_ms, decision_freshness_ms)

    signal = {
        "schema_version": "detector_signal_v0_1",
        "event_id": event["event_id"],
        "service_name": service_name,
        "source_stream": ANOMALY_STREAM,
        "scenario_tag": event.get("scenario_tag"),
        "generated_at": event.get("generated_at"),
        "scored_at": scored_at_dt.isoformat(),
        "anomaly_score": round(score, 6),
        "anomaly_flag": persistent_flag,
        "candidate_flag": candidate_flag,
        "service_threshold": round(threshold, 6),
        "min_flag_window": snapshot.min_flag_window,
        "window_size": len(recent_flags_by_service[service_name]),
        "window_fill": len(trailing_window),
        "reason_codes": reasons,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "detector_policy_name": snapshot.policy["policy_name"],
        "detector_policy_version": snapshot.policy["policy_version"],
        "detector_policy_path": str(snapshot.policy_path),
        "feature_schema_version": snapshot.schema_version,
        "expected_features": list(snapshot.feature_columns),
        "scoring_policy": snapshot.policy["scoring_policy"],
        "threshold_mode": snapshot.policy["threshold_mode"],
        "policy_loaded_at": snapshot.loaded_at,
        "inference_latency_ms": round(inference_latency_ms, 6),
        "decision_freshness_ms": round(decision_freshness_ms, 6) if decision_freshness_ms is not None else None,
        "iforest_label": "anomalous" if persistent_flag else "normal",
        "telemetry_snapshot": {field: event.get(field) for field in [*DEFAULT_FEATURE_COLUMNS, "status_code"]},
        "raw_event_ref": f"redis-pubsub://{REDIS_CHANNEL}//{event['event_id']}",
    }
    with DECISION_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(signal) + "\n")
    return signal


def consume() -> None:
    pubsub.subscribe(REDIS_CHANNEL)
    with state_lock:
        state["redis_connected"] = True
    for message in pubsub.listen():
        payload = json.loads(message["data"])
        signal = score_event(payload)
        redis_client.xadd(ANOMALY_STREAM, {"payload": json.dumps(signal, sort_keys=True)})
        with state_lock:
            state["events_seen"] += 1
            state["last_event_id"] = payload["event_id"]
            state["last_scored_at"] = signal["scored_at"]
        print(json.dumps(signal), flush=True)


@app.get("/health")
def health() -> tuple:
    snapshot = runtime_cache.get()
    with state_lock:
        service_fill = {service: len(window) for service, window in recent_flags_by_service.items()}
        service_means = {
            service: round(mean(int(value) for value in window), 4) if window else 0.0
            for service, window in recent_flags_by_service.items()
        }
        payload = {
            "status": "ok",
            "redis_connected": state["redis_connected"],
            "anomaly_stream": ANOMALY_STREAM,
            "events_seen": state["events_seen"],
            "last_event_id": state["last_event_id"],
            "last_scored_at": state["last_scored_at"],
            "policy_reference_path": state["policy_reference_path"],
            "policy_path": str(snapshot.policy_path),
            "model_path": str(snapshot.model_path),
            "schema_version": snapshot.schema_version,
            "expected_features": list(snapshot.feature_columns),
            "scoring_policy": snapshot.policy["scoring_policy"],
            "threshold_mode": snapshot.policy["threshold_mode"],
            "service_thresholds": snapshot.service_thresholds,
            "min_flag_window": snapshot.min_flag_window,
            "startup_loaded_at": state["startup_loaded_at"],
            "startup_load_duration_ms": state["startup_load_duration_ms"],
            "last_policy_reload_at": state["last_policy_reload_at"],
            "last_policy_reload_duration_ms": state["last_policy_reload_duration_ms"],
            "reload_count": state["reload_count"],
            "policy_loaded_at": snapshot.loaded_at,
            "service_window_fill": service_fill,
            "service_candidate_rate": service_means,
            "inference_count": state["inference_count"],
            "last_inference_latency_ms": state["last_inference_latency_ms"],
            "avg_inference_latency_ms": state["avg_inference_latency_ms"],
            "max_inference_latency_ms": state["max_inference_latency_ms"],
            "last_decision_freshness_ms": state["last_decision_freshness_ms"],
            "avg_decision_freshness_ms": state["avg_decision_freshness_ms"],
        }
    return jsonify(payload), 200


@app.post("/internal/reload-policy")
def reload_policy() -> tuple:
    if not DETECTOR_RELOAD_TOKEN:
        return jsonify({"status": "disabled", "reason": "reload_token_not_configured"}), 403
    if request.headers.get("X-Reload-Token") != DETECTOR_RELOAD_TOKEN:
        return jsonify({"status": "forbidden"}), 403

    snapshot = runtime_cache.load()
    with state_lock:
        recent_flags_by_service.clear()
        state["last_policy_reload_at"] = snapshot.loaded_at
        state["last_policy_reload_duration_ms"] = round(snapshot.load_duration_ms, 6)
        state["reload_count"] = snapshot.load_count

    return jsonify(
        {
            "status": "reloaded",
            "policy_path": str(snapshot.policy_path),
            "model_path": str(snapshot.model_path),
            "schema_version": snapshot.schema_version,
            "expected_features": list(snapshot.feature_columns),
            "reload_count": snapshot.load_count,
            "load_duration_ms": round(snapshot.load_duration_ms, 6),
        }
    ), 200


threading.Thread(target=consume, daemon=True).start()
app.run(host="0.0.0.0", port=8080)
