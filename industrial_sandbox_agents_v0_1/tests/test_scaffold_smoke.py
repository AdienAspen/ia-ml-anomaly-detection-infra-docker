from src.agentic_core.triage import main as triage_main
from src.context_engine.builder import main as context_main


def test_scaffold_entrypoints_return_success() -> None:
    assert triage_main() == 0
    assert context_main() == 0
