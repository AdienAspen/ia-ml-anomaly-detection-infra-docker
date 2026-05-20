"""Container entrypoint for the long-running 1C context engine."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.context_engine.service import run_context_engine_service


if __name__ == "__main__":
    raise SystemExit(run_context_engine_service())
