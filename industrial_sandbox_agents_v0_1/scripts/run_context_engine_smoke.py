"""Smoke entrypoint for the context engine scaffold."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event


def main() -> int:
    context_slice = build_context_slice(build_sample_enriched_anomaly_event())
    if context_slice["schema_version"] != "context_slice_v0_1":
        return 1
    print(
        "Context engine smoke passed for "
        f"{context_slice['event_id']} -> {context_slice['primary_service']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
