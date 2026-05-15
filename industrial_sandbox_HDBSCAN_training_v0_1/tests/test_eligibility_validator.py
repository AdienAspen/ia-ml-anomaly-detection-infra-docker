from pathlib import Path

from src.eligibility_validator import OUTPUT_PATH, REPORT_PATH, build_eligibility_report, main


def test_eligibility_validator_scaffold_returns_success() -> None:
    assert main() == 0


def test_eligibility_validator_emits_reports() -> None:
    reports = build_eligibility_report()
    assert reports
    sample = reports[0]
    assert sample["schema_version"] == "eligibility_report_v0_1"
    assert "eligibility_score" in sample
    assert "risk_score" in sample
    assert "recommended_status" in sample


def test_eligibility_validator_exports_artifacts() -> None:
    main()
    assert Path(OUTPUT_PATH).exists()
    assert Path(REPORT_PATH).exists()
