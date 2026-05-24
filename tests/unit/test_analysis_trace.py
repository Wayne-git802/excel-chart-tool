"""Tests for TraceEntry / summarize_old_traces / AgentState.analysis_trace."""

import time
import pytest
from models.agent_state import (
    AgentState, TraceEntry, PlanStep, MAX_TRACE_ENTRIES, summarize_old_traces
)


# ── TraceEntry construction ────────────────────────────────────

def test_trace_entry_construct():
    """TraceEntry 构造: 所有字段正常赋值."""
    ts = time.time()
    entry = TraceEntry(
        step_id="s1",
        goal="整体趋势",
        tool="chart_builder",
        observation_summary="销售额月均增长12%",
        chart_type="line",
        timestamp=ts,
    )
    assert entry.step_id == "s1"
    assert entry.goal == "整体趋势"
    assert entry.tool == "chart_builder"
    assert entry.observation_summary == "销售额月均增长12%"
    assert entry.chart_type == "line"
    assert entry.timestamp == ts


def test_trace_entry_defaults():
    """TraceEntry 构造: chart_type / timestamp 默认值."""
    entry = TraceEntry(step_id="s2", goal="数据概览", tool="data_query", observation_summary="共50行")
    assert entry.chart_type is None
    assert entry.timestamp == 0.0


# ── summarize_old_traces ───────────────────────────────────────

def _make_entries(n: int) -> list[TraceEntry]:
    """Helper: create n trace entries s0...s{n-1}."""
    return [
        TraceEntry(
            step_id=f"s{i}",
            goal=f"步骤{i}",
            tool="chart_builder" if i % 2 == 0 else "data_query",
            observation_summary=f"观察结果第{i}项: 发现重要数据特征需要进一步分析验证",
            chart_type="line" if i % 2 == 0 else None,
            timestamp=float(i),
        )
        for i in range(n)
    ]


def test_summarize_over_limit():
    """summarize_old_traces: 9 条 → 返回摘要，保留最后 8 条."""
    entries = _make_entries(9)
    summary = summarize_old_traces(entries)
    # 9 > 8, 所以返回非空摘要
    assert summary != ""
    assert "早期分析摘要" in summary
    # 保留最后 MAX_TRACE_ENTRIES (8) 条
    assert len(entries) == MAX_TRACE_ENTRIES
    # 保留的是后面的条目
    assert entries[0].step_id == "s1"  # 最早的被移除，s1 变成第一个
    assert entries[-1].step_id == "s8"


def test_summarize_at_limit():
    """summarize_old_traces: ≤8 条 → 返回空字符串."""
    entries = _make_entries(8)
    summary = summarize_old_traces(entries)
    assert summary == ""
    assert len(entries) == 8  # 列表不变


def test_summarize_under_limit():
    """summarize_old_traces: 3 条 → 返回空字符串."""
    entries = _make_entries(3)
    summary = summarize_old_traces(entries)
    assert summary == ""
    assert len(entries) == 3


def test_summarize_empty():
    """summarize_old_traces: 空列表 → 返回 ""."""
    entries = []
    summary = summarize_old_traces(entries)
    assert summary == ""
    assert entries == []


def test_max_trace_entries_constant():
    """MAX_TRACE_ENTRIES 常量存在且为整数."""
    assert isinstance(MAX_TRACE_ENTRIES, int)
    assert MAX_TRACE_ENTRIES > 0


# ── AgentState.analysis_trace 序列化 ──────────────────────────

def test_analysis_trace_roundtrip():
    """AgentState.analysis_trace 序列化 → to_dict/from_dict 往返."""
    state = AgentState()
    entries = _make_entries(3)
    state.analysis_trace = entries

    d = state.to_dict()
    restored = AgentState.from_dict(d)

    assert len(restored.analysis_trace) == 3
    for orig, restored_entry in zip(entries, restored.analysis_trace):
        assert restored_entry.step_id == orig.step_id
        assert restored_entry.goal == orig.goal
        assert restored_entry.tool == orig.tool
        assert restored_entry.observation_summary == orig.observation_summary
        assert restored_entry.chart_type == orig.chart_type


# ── _write_trace 模式：超过上限时插入 _summary entry ──────────

def test_write_trace_inserts_summary_on_overflow():
    """超过 MAX_TRACE_ENTRIES 时插入 _summary entry."""
    state = AgentState()
    # 填满到 MAX_TRACE_ENTRIES
    for i in range(MAX_TRACE_ENTRIES):
        entry = TraceEntry(
            step_id=f"s{i}",
            goal=f"步骤{i}",
            tool="chart_builder",
            observation_summary=f"结果{i}",
            timestamp=float(i),
        )
        state.analysis_trace.append(entry)

    assert len(state.analysis_trace) == MAX_TRACE_ENTRIES

    # 再添加一条，触发 _write_trace 逻辑
    new_entry = TraceEntry(
        step_id=f"s{MAX_TRACE_ENTRIES}",
        goal=f"步骤{MAX_TRACE_ENTRIES}",
        tool="data_query",
        observation_summary=f"结果{MAX_TRACE_ENTRIES}",
        timestamp=float(MAX_TRACE_ENTRIES),
    )
    state.analysis_trace.append(new_entry)

    # 超过上限：调用 summarize_old_traces 来触发压缩
    if len(state.analysis_trace) > MAX_TRACE_ENTRIES:
        old_summary = summarize_old_traces(state.analysis_trace)
        if old_summary:
            summary_entry = TraceEntry(
                step_id="_summary",
                goal="早期分析摘要",
                tool="",
                observation_summary=old_summary[:200],
                timestamp=time.time(),
            )
            state.analysis_trace.insert(0, summary_entry)

    # 现在列表以 _summary 开头，不超过 MAX_TRACE_ENTRIES+1
    assert state.analysis_trace[0].step_id == "_summary"
    assert state.analysis_trace[0].goal == "早期分析摘要"
    assert len(state.analysis_trace) <= MAX_TRACE_ENTRIES + 1


def test_trace_order_preserved():
    """trace 顺序保持 — 插入 _summary 后其余条目顺序不变."""
    state = AgentState()
    entries = _make_entries(5)
    state.analysis_trace = entries[:]

    # 验证顺序
    assert [e.step_id for e in state.analysis_trace] == ["s0", "s1", "s2", "s3", "s4"]
