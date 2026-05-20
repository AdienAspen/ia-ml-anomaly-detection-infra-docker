"""Context engine package."""

from src.context_engine.contracts import ValidationError, validate_context_slice
from src.context_engine.builder import build_context_slice
from src.context_engine.consumer import (
    EventBusRuntimeSettings,
    build_event_consumer,
    build_redis_client,
    consume_enriched_anomaly_events,
    load_event_bus_settings,
)
from src.context_engine.service import run_context_engine_service, run_context_service_iteration

__all__ = [
    "EventBusRuntimeSettings",
    "ValidationError",
    "build_context_slice",
    "build_event_consumer",
    "build_redis_client",
    "consume_enriched_anomaly_events",
    "load_event_bus_settings",
    "run_context_engine_service",
    "run_context_service_iteration",
    "validate_context_slice",
]
