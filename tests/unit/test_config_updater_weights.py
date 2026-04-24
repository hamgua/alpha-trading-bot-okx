"""ConfigUpdater 融合权重动态更新测试。"""

import tempfile

from alpha_trading_bot.ai.optimizer.config_updater import ConfigUpdater


def test_apply_weight_param_updates_and_normalizes_multiple_providers() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = f"{temp_dir}/config.json"
        updater = ConfigUpdater(config_path=config_path)

        ok = updater.apply_optimized_params({"ai_weight_gemini": 0.7}, reason="test")
        assert ok

        weights = updater.get("ai.fusion_weights", {})
        providers = updater.get("ai.fusion_providers", [])

        assert "gemini" in weights
        assert "gemini" in providers
        assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_apply_full_fusion_weights_payload_is_normalized() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = f"{temp_dir}/config.json"
        updater = ConfigUpdater(config_path=config_path)

        ok = updater.apply_optimized_params(
            {"ai_fusion_weights": {"deepseek": 2.0, "kimi": 1.0, "gemini": 1.0}},
            reason="test-full",
        )
        assert ok

        weights = updater.get("ai.fusion_weights", {})
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert weights["deepseek"] > weights["kimi"]
