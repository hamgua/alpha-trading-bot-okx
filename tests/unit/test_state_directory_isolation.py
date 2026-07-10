from pathlib import Path

from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceTracker
from alpha_trading_bot.core.state_persistence import StatePersistence


def test_state_persistence_uses_environment_override(tmp_path, monkeypatch):
    state_dir = tmp_path / "runtime-state"
    monkeypatch.setenv("TRADING_STATE_DIR", str(state_dir))

    persistence = StatePersistence()

    assert persistence.data_dir == state_dir


def test_explicit_state_directory_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_STATE_DIR", str(tmp_path / "environment"))
    explicit = tmp_path / "explicit"

    persistence = StatePersistence(explicit)

    assert persistence.data_dir == explicit


def test_performance_tracker_uses_isolated_sibling_directory(tmp_path, monkeypatch):
    state_dir = tmp_path / "trading-state"
    monkeypatch.setenv("TRADING_STATE_DIR", str(state_dir))

    tracker = PerformanceTracker()

    assert Path(tracker.data_dir) == tmp_path / "adaptive-performance"
