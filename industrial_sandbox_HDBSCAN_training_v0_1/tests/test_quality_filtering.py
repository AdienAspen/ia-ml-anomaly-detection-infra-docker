from src.train_hdbscan_temporal import filter_windows_for_training, filter_windows_for_validation, load_training_config


def _window(window_id: str, quality: float, accepted: bool = True) -> dict:
    return {
        "window_id": window_id,
        "window_data_quality_score": quality,
        "training_metadata": {"accepted_for_training": accepted},
    }


def test_training_quality_filter_excludes_low_quality_windows() -> None:
    config = load_training_config()
    eligible, low_quality = filter_windows_for_training(
        [_window("w1", 0.91), _window("w2", 0.84), _window("w3", 0.90, accepted=False)],
        config,
    )
    assert [window["window_id"] for window in eligible] == ["w1"]
    assert {window["window_id"] for window in low_quality} == {"w2", "w3"}


def test_validation_quality_filter_uses_validation_threshold() -> None:
    config = load_training_config()
    eligible, low_quality = filter_windows_for_validation(
        [_window("w1", 0.85), _window("w2", 0.83)],
        config,
    )
    assert [window["window_id"] for window in eligible] == ["w1"]
    assert [window["window_id"] for window in low_quality] == ["w2"]
