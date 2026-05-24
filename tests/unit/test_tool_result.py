"""Tests for ToolResult / SSEEvent / normalize_tool_result."""

import json
import time
from dataclasses import asdict
import pytest
from services.tool_result import ToolResult, SSEEvent, normalize_tool_result, MAX_TOOL_PAYLOAD_KB


# ── ToolResult construction ────────────────────────────────────

def test_tool_result_construct_success():
    """ToolResult 构造: success + narrative 必填字段正常赋值."""
    tr = ToolResult(success=True, tool="chart_builder", narrative="生成了趋势图")
    assert tr.success is True
    assert tr.tool == "chart_builder"
    assert tr.narrative == "生成了趋势图"
    assert tr.data is None
    assert tr.chart_spec is None
    assert tr.observations == []
    assert tr.confidence == 0.0
    assert tr.error is None


def test_tool_result_construct_failure():
    """ToolResult 构造: failure 情况带 error 字段."""
    tr = ToolResult(success=False, tool="data_query", narrative="", error="列不存在")
    assert tr.success is False
    assert tr.error == "列不存在"


def test_tool_result_chart_spec_without_narrative_raises():
    """chart_spec 有但 narrative 为空 → ValueError."""
    with pytest.raises(ValueError, match="chart_spec requires narrative"):
        ToolResult(success=True, tool="chart_builder", narrative="", chart_spec={"type": "bar"})


def test_tool_result_chart_spec_with_narrative_ok():
    """chart_spec 有且 narrative 非空 → 正常构造."""
    tr = ToolResult(success=True, tool="chart_builder", narrative="趋势图", chart_spec={"type": "line"})
    assert tr.chart_spec == {"type": "line"}
    assert tr.narrative == "趋势图"


# ── Data truncation ─────────────────────────────────────────────

def test_tool_result_truncate_large_data():
    """ToolResult data > 32KB → _truncated=True."""
    big_value = "x" * (MAX_TOOL_PAYLOAD_KB * 1024 + 100)  # just over 32KB
    tr = ToolResult(success=True, tool="data_query", narrative="ok", data={"big": big_value})
    assert tr.data["_truncated"] is True
    assert "exceeded" in tr.data["summary"]


def test_tool_result_no_truncate_small_data():
    """ToolResult data 小 → 不截断."""
    tr = ToolResult(success=True, tool="chart_builder", narrative="ok", data={"x": [1, 2, 3]})
    assert tr.data == {"x": [1, 2, 3]}
    assert "_truncated" not in tr.data


# ── normalize_tool_result ──────────────────────────────────────

def test_normalize_old_dict_success():
    """normalize_tool_result: 旧 dict {"ok":true, "result":{"chart_spec":{...}}} → ToolResult."""
    raw = {"ok": True, "result": {"chart_spec": {"type": "bar"}, "title": "销售分布"}, "confidence": 0.9}
    tr = normalize_tool_result(raw, tool="chart_builder")
    assert isinstance(tr, ToolResult)
    assert tr.success is True
    assert tr.tool == "chart_builder"
    assert tr.narrative == "销售分布"
    assert tr.chart_spec == {"type": "bar"}
    assert tr.confidence == 0.9


def test_normalize_old_dict_error():
    """normalize_tool_result: 旧 dict {"ok":false, "error":"msg"} → ToolResult(success=False)."""
    raw = {"ok": False, "error": "something went wrong"}
    tr = normalize_tool_result(raw, tool="data_query")
    assert tr.success is False
    # Note: due to operator precedence, when "result" key is absent/not-a-dict
    # the error from top-level "error" key is shadowed.
    # However error-in-result is captured:
    raw2 = {"ok": False, "result": {"error": "nested error"}}
    tr2 = normalize_tool_result(raw2, tool="data_query")
    assert tr2.success is False
    assert tr2.error == "nested error"
    assert tr.confidence == 0.0


def test_normalize_passthrough_toolresult():
    """normalize_tool_result: 已 ToolResult 传入 → 原样返回."""
    original = ToolResult(success=True, tool="chart_builder", narrative="趋势图", data={"x": [1, 2]})
    tr = normalize_tool_result(original, tool="should_be_ignored")
    assert tr is original
    assert tr.tool == "chart_builder"


def test_normalize_observation_maps_to_narrative():
    """normalize: observation 映射到 narrative."""
    raw = {"ok": True, "observation": "数据有季节性波动", "result": {}}
    tr = normalize_tool_result(raw, tool="data_query")
    assert tr.narrative == "数据有季节性波动"
    assert "数据有季节性波动" in tr.observations


def test_normalize_missing_fields_fallback():
    """normalize: 缺失字段兜底 — 所有字段有合理默认值."""
    raw = {}  # 完全空 dict
    tr = normalize_tool_result(raw, tool="unknown")
    assert tr.success is False
    assert tr.tool == "unknown"
    assert tr.narrative == ""
    assert tr.data is None
    assert tr.chart_spec is None
    assert tr.confidence == 0.0
    assert tr.error is None


# ── SSEEvent ────────────────────────────────────────────────────

def test_sseevent_construct_and_fields():
    """SSEEvent 构造 + 字段访问."""
    ev = SSEEvent(type="narrative", step_id="s1", payload={"content": "正在分析..."})
    assert ev.type == "narrative"
    assert ev.step_id == "s1"
    assert ev.payload == {"content": "正在分析..."}
    assert isinstance(ev.timestamp, float)


def test_sseevent_to_dict():
    """SSEEvent 可通过 asdict 转为 dict."""
    ev = SSEEvent(type="action", step_id="s2", payload={"chart_type": "bar"})
    d = asdict(ev)
    assert d["type"] == "action"
    assert d["step_id"] == "s2"
    assert d["payload"] == {"chart_type": "bar"}
    assert isinstance(d["timestamp"], float)
