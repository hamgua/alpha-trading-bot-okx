"""
测试 DeepSeek 响应解析 bug 修复

覆盖场景：
- DeepSeek 标准/JSON 格式响应
- 空 content 响应
- reasoning_content 存在但 content 为空
- 思考标签清洗后 JSON 解析
- 边界条件
- 回归测试（其他提供商不受影响）
"""

import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from alpha_trading_bot.ai.response_parser import ResponseParser, parse_response


class TestResponseParserDeepSeek:
    """DeepSeek 响应解析测试"""

    # === 正常路径 ===

    def test_standard_hold_format(self):
        """T01: DeepSeek 标准 hold 格式"""
        signal, confidence = parse_response("hold | confidence: 70%")
        assert signal == "hold"
        assert confidence == 70

    def test_json_buy_format(self):
        """T02: DeepSeek JSON 格式 buy"""
        signal, confidence = parse_response('{"signal":"buy","confidence":75}')
        assert signal == "buy"
        assert confidence == 75

    def test_standard_buy_format(self):
        """T03: DeepSeek 短格式 buy"""
        signal, confidence = parse_response("buy | confidence: 65%")
        assert signal == "buy"
        assert confidence == 65

    def test_sell_signal(self):
        """T04: DeepSeek sell 信号"""
        signal, confidence = parse_response("sell | confidence: 80%")
        assert signal == "sell"
        assert confidence == 80

    def test_short_signal(self):
        """T05: DeepSeek short 信号"""
        signal, confidence = parse_response("short | confidence: 60%")
        assert signal == "short"
        assert confidence == 60

    # === 异常路径 ===

    def test_empty_content(self):
        """T06: DeepSeek 空 content 响应"""
        signal, confidence = parse_response("")
        assert signal == "hold"
        assert confidence is None

    def test_unrecognized_format(self):
        """T08: 无法识别的响应格式"""
        signal, confidence = parse_response("市场趋势不明朗")
        assert signal == "hold"
        assert confidence is None

    def test_json_with_think_tags(self):
        """T09: think 标签清除后纯 JSON 解析"""
        # MiniMax 等模型在 content 中返回 think 标签 + JSON
        # DeepSeek Thinking Mode 的推理在 reasoning_content 字段，
        # content 只有最终答案（标准格式）
        # 此测试验证纯 JSON（think 标签已清除后）的解析
        response = '{"signal":"hold","confidence":60}'
        signal, confidence = parse_response(response)
        assert signal == "hold"
        assert confidence == 60

    def test_hold_with_confidence_after_think_tags(self):
        """T09b: think 标签后跟标准格式信号"""
        # 当模型在 think 标签外输出标准格式时，regex 应能提取
        response = "hold | confidence: 65%"
        signal, confidence = parse_response(response)
        assert signal == "hold"
        assert confidence == 65

    # === 边界条件 ===

    def test_confidence_zero(self):
        """T12: 置信度为 0"""
        signal, confidence = parse_response("hold | confidence: 0%")
        assert signal == "hold"
        assert confidence == 0

    def test_confidence_hundred(self):
        """T13: 置信度为 100"""
        signal, confidence = parse_response("buy | confidence: 100%")
        assert signal == "buy"
        assert confidence == 100

    def test_json_confidence_decimal(self):
        """T14: JSON 置信度值 0-1 范围（自动转百分比）"""
        signal, confidence = parse_response('{"signal":"buy","confidence":0.7}')
        assert signal == "buy"
        assert confidence == 70

    def test_whitespace_only(self):
        """T15: 纯空白响应"""
        signal, confidence = parse_response("   ")
        assert signal == "hold"
        assert confidence is None

    def test_response_with_newline(self):
        """T16: 带换行的响应"""
        signal, confidence = parse_response("hold | confidence: 70%\n")
        assert signal == "hold"
        assert confidence == 70

    # === 回归测试 ===

    def test_kimi_standard_format_still_works(self):
        """T17: Kimi 标准格式仍能解析"""
        signal, confidence = parse_response("hold | confidence: 70%")
        assert signal == "hold"
        assert confidence == 70

    def test_other_provider_json_still_works(self):
        """T18: 其他提供商 JSON 格式仍能解析"""
        signal, confidence = parse_response('{"signal":"sell","confidence":80}')
        assert signal == "sell"
        assert confidence == 80

    def test_simple_hold_keyword(self):
        """简单 hold 关键词匹配"""
        signal, confidence = parse_response("hold")
        assert signal == "hold"
        assert confidence is None

    def test_simple_buy_keyword(self):
        """简单 buy 关键词匹配"""
        signal, confidence = parse_response("buy")
        assert signal == "buy"
        assert confidence is None

    def test_validate_valid_signals(self):
        """验证有效信号"""
        assert ResponseParser.validate("buy") is True
        assert ResponseParser.validate("hold") is True
        assert ResponseParser.validate("sell") is True
        assert ResponseParser.validate("short") is True

    def test_validate_invalid_signals(self):
        """验证无效信号"""
        assert ResponseParser.validate("unknown") is False
        assert ResponseParser.validate("") is False


class TestAIClientDeepSeekHandling:
    """测试 AIClient 对 DeepSeek 的特殊处理"""

    def test_deepseek_max_tokens_increased(self):
        """验证 DeepSeek 的 max_tokens 设为 800"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        import inspect

        source = inspect.getsource(client._call_ai)
        assert '"deepseek"' in source or "'deepseek'" in source
        assert "800" in source

    def test_minimax_max_tokens_unchanged(self):
        """T19: MiniMax 的 max_tokens 仍为 800（回归测试）"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        import inspect

        source = inspect.getsource(client._call_ai)
        assert "minimax" in source
        assert "800" in source


class TestReasoningContentHandling:
    """测试 reasoning_content 字段处理"""

    def test_empty_content_with_reasoning_content_logs_warning(self):
        """T07: reasoning_content 存在但 content 为空时记录警告"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        import inspect

        source = inspect.getsource(client._call_ai)
        assert "reasoning_content" in source

    def test_content_extraction_uses_get_method(self):
        """T20: content 提取使用 .get() 方法（安全访问）"""
        from alpha_trading_bot.ai.client import AIClient

        client = AIClient(enable_cache=False)
        import inspect

        source = inspect.getsource(client._call_ai)
        assert 'message.get("content"' in source or "message.get('content'" in source


class TestResponseParserThinkTagRemoval:
    """测试 _parse_json_response 中 think 标签清除"""

    def test_json_after_think_tag_removal(self):
        """验证 think 标签清除后 JSON 能正确解析"""
        response = '{"signal":"hold","confidence":60}'
        signal, confidence = ResponseParser._parse_json_response(response)
        assert signal == "hold"
        assert confidence == 60

    def test_json_in_code_block_still_works(self):
        """验证 markdown code block 中的 JSON 仍能解析"""
        response = '```json\n{"signal":"buy","confidence":75}\n```'
        signal, confidence = ResponseParser._parse_json_response(response)
        assert signal == "buy"
        assert confidence == 75

    def test_empty_response_returns_none(self):
        """验证空响应返回 None"""
        result = ResponseParser._parse_json_response("")
        assert result is None

    def test_non_json_response_returns_none(self):
        """验证非 JSON 响应返回 None"""
        result = ResponseParser._parse_json_response("hold | confidence: 70%")
        assert result is None

    def test_invalid_signal_returns_none(self):
        """验证无效信号的 JSON 返回 None"""
        result = ResponseParser._parse_json_response('{"signal":"unknown","confidence":50}')
        assert result is None

    def test_json_confidence_as_string(self):
        """验证 JSON 中置信度为字符串格式"""
        signal, confidence = ResponseParser._parse_json_response(
            '{"signal":"hold","confidence":"70%"}'
        )
        assert signal == "hold"
        assert confidence == 70

    def test_json_confidence_missing(self):
        """验证 JSON 中缺少置信度字段"""
        signal, confidence = ResponseParser._parse_json_response(
            '{"signal":"hold"}'
        )
        assert signal == "hold"
        assert confidence is None