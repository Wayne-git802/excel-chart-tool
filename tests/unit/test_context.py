"""Unit tests for ConversationContext prompt projection layer."""

import pytest
import pandas as pd
from dataclasses import dataclass, field

from core.context_builder import (
    ConversationContext,
    FilterContextView,
    DatasetContextView,
    AnalysisContextView,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_state(columns=None, row_count=100, filter_context=None,
                execution_artifacts=None, analysis_trace=None):
    """Minimal AgentState-like object for testing."""
    class FakeState:
        def __init__(self):
            self.columns = columns or []
            self.row_count = row_count
            self.filter_context = filter_context
            self.execution_artifacts = execution_artifacts or []
            self.analysis_trace = analysis_trace or []
    return FakeState()


def _make_filter_context(conditions=None, persist=False):
    """Build real FilterContext + FilterSpec for integration tests."""
    from core.ir.contract import FilterCondition, FilterSpec
    from core.ir.session import FilterContext
    conds = []
    if conditions:
        for c in conditions:
            conds.append(FilterCondition(**c))
    fs = FilterSpec(conditions=conds, persist=persist)
    fctx = FilterContext()
    fctx.apply_new(fs)
    return fctx


def _make_trace(goal="数据概览", tool="chart_builder", chart_type="bar"):
    """Build a TraceEntry-like object."""
    @dataclass
    class FakeTrace:
        step_id: str = "s1"
        goal: str = ""
        tool: str = ""
        observation_summary: str = ""
        chart_type: str | None = None
        timestamp: float = 0.0
    return FakeTrace(goal=goal, tool=tool, chart_type=chart_type)


def _make_artifact(chart_type="bar", x_column="月份", y_columns=None):
    """Build a ChartArtifact-like object."""
    @dataclass
    class FakeArtifact:
        step_id: str = "s1"
        chart_type: str = "bar"
        x_column: str = ""
        y_columns: list = field(default_factory=list)
        title: str = ""
        resolved_by: str = "v10_contract"
        source_step: str = "chart_builder"
        status: str = "approved"

        def to_prompt_context(self):
            return {"chart_type": self.chart_type, "x": self.x_column, "y": self.y_columns}
    return FakeArtifact(chart_type=chart_type, x_column=x_column,
                        y_columns=y_columns or [])


# ═══════════════════════════════════════════════════════════════
# FilterContextView tests
# ═══════════════════════════════════════════════════════════════

def test_filter_context_view_no_filter():
    state = _make_state()
    view = FilterContextView.from_state(state)
    assert view.is_filtered is False
    assert view.active_desc is None
    assert view.conditions == []


def test_filter_context_view_with_active_filter():
    fctx = _make_filter_context([
        {"column": "人物", "operator": "eq", "value": "小红"},
    ])
    state = _make_state(filter_context=fctx)
    view = FilterContextView.from_state(state)
    assert view.is_filtered is True
    assert view.active_desc == "人物 = 小红"
    assert len(view.conditions) == 1
    assert view.conditions[0]["column"] == "人物"
    assert view.conditions[0]["operator"] == "eq"


def test_filter_context_view_multi_condition():
    fctx = _make_filter_context([
        {"column": "人物", "operator": "eq", "value": "小红"},
        {"column": "年龄", "operator": "gt", "value": 18},
    ])
    state = _make_state(filter_context=fctx)
    view = FilterContextView.from_state(state)
    assert view.is_filtered is True
    assert "人物 = 小红" in view.active_desc
    assert "年龄 > 18" in view.active_desc
    assert len(view.conditions) == 2


def test_filter_context_view_none_fctx():
    state = _make_state(filter_context=None)
    view = FilterContextView.from_state(state)
    assert view.is_filtered is False


# ═══════════════════════════════════════════════════════════════
# DatasetContextView tests
# ═══════════════════════════════════════════════════════════════

def test_dataset_context_view_basic():
    columns = [
        {"name": "人物", "dtype_cn": "字符串"},
        {"name": "身高", "dtype_cn": "数值"},
        {"name": "体重", "dtype_cn": "数值"},
        {"name": "日期", "dtype_cn": "日期"},
    ]
    state = _make_state(columns=columns, row_count=100)
    df = pd.DataFrame({"人物": ["a"], "身高": [1.0], "体重": [2.0], "日期": ["2024"]})
    view = DatasetContextView.from_state(state, df, original_row_count=100)
    assert view.filtered_rows == 1
    assert view.total_rows == 100
    assert "人物(categorical)" in view.column_summary
    assert "身高(numeric)" in view.column_summary
    assert "日期(temporal)" in view.column_summary


def test_dataset_context_view_no_filtering():
    columns = [{"name": "x", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=50)
    df = pd.DataFrame({"x": range(50)})
    view = DatasetContextView.from_state(state, df, original_row_count=50)
    assert view.filtered_rows == 50
    assert view.total_rows == 50


def test_dataset_context_view_filtered():
    columns = [{"name": "x", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=100)
    df = pd.DataFrame({"x": range(30)})
    view = DatasetContextView.from_state(state, df, original_row_count=100)
    assert view.filtered_rows == 30
    assert view.total_rows == 100


def test_dataset_context_view_empty_columns():
    state = _make_state(columns=[], row_count=0)
    df = pd.DataFrame()
    view = DatasetContextView.from_state(state, df, original_row_count=0)
    assert "无列信息" in view.column_summary


# ═══════════════════════════════════════════════════════════════
# AnalysisContextView tests
# ═══════════════════════════════════════════════════════════════

def test_analysis_context_view_no_history():
    state = _make_state()
    view = AnalysisContextView.from_state(state)
    assert view.is_continuation is False
    assert view.last_intent is None
    assert view.last_chart_type is None


def test_analysis_context_view_with_artifact():
    artifact = _make_artifact(chart_type="line", x_column="月份", y_columns=["销售额"])
    state = _make_state(execution_artifacts=[artifact])
    view = AnalysisContextView.from_state(state)
    assert view.is_continuation is True
    assert view.last_chart_type == "line"
    assert view.last_x_column == "月份"
    assert view.last_y_columns == ["销售额"]


def test_analysis_context_view_with_trace_intent():
    trace = _make_trace(goal="对比各部门表现", tool="chart_builder")
    state = _make_state(analysis_trace=[trace])
    view = AnalysisContextView.from_state(state)
    assert view.is_continuation is True
    assert view.last_intent == "comparison"
    assert view.analysis_goal == "comparison"


def test_analysis_context_view_prev_message():
    state = _make_state()
    view = AnalysisContextView.from_state(state, prev_user_message="分析趋势")
    assert view.last_user_message == "分析趋势"


def test_analysis_context_view_no_intent_match():
    trace = _make_trace(goal="综合结论", tool="annotation_engine")
    state = _make_state(analysis_trace=[trace])
    view = AnalysisContextView.from_state(state)
    assert view.is_continuation is True
    assert view.last_intent is None  # no keyword matched


# ═══════════════════════════════════════════════════════════════
# ConversationContext.build() tests
# ═══════════════════════════════════════════════════════════════

def test_conversation_context_build_no_filter():
    columns = [{"name": "x", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=50)
    df = pd.DataFrame({"x": range(50)})
    ctx = ConversationContext.build(state, df, original_row_count=50)
    assert ctx.filter.is_filtered is False
    assert ctx.dataset.filtered_rows == 50
    assert ctx.dataset.total_rows == 50
    assert ctx.analysis.is_continuation is False


def test_conversation_context_build_with_filter():
    fctx = _make_filter_context([
        {"column": "人物", "operator": "eq", "value": "小红"},
    ])
    columns = [{"name": "人物", "dtype_cn": "字符串"}, {"name": "身高", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=100, filter_context=fctx)
    df = pd.DataFrame({"人物": ["小红"], "身高": [170.0]})
    ctx = ConversationContext.build(state, df, original_row_count=100, prev_user_message="看小红的数据")
    assert ctx.filter.is_filtered is True
    assert ctx.dataset.filtered_rows == 1
    assert ctx.dataset.total_rows == 100
    assert ctx.analysis.last_user_message == "看小红的数据"


def test_conversation_context_build_with_history():
    artifact = _make_artifact("pie", "类别", ["数量"])
    trace = _make_trace(goal="分布分析", tool="chart_builder")
    state = _make_state(execution_artifacts=[artifact], analysis_trace=[trace], row_count=200)
    df = pd.DataFrame({"类别": ["A"], "数量": [10]})
    ctx = ConversationContext.build(state, df, original_row_count=200)
    assert ctx.analysis.is_continuation is True
    assert ctx.analysis.last_chart_type == "pie"
    assert ctx.analysis.last_intent == "distribution"


# ═══════════════════════════════════════════════════════════════
# to_prompt_sections() tests
# ═══════════════════════════════════════════════════════════════

def test_to_prompt_sections_full_no_filter():
    columns = [{"name": "x", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=50)
    df = pd.DataFrame({"x": range(50)})
    ctx = ConversationContext.build(state, df, original_row_count=50)
    sections = ctx.to_prompt_sections("full")
    # Should have dataset section (no filter, no analysis for first turn)
    assert isinstance(sections, list)
    # dataset section always present
    dataset_found = any("[数据集状态]" in s for s in sections)
    assert dataset_found
    # No filter section when not filtered
    filter_found = any("[当前数据筛选]" in s for s in sections)
    assert not filter_found
    # No analysis section when no history
    analysis_found = any("[上一轮分析上下文]" in s for s in sections)
    assert not analysis_found


def test_to_prompt_sections_with_filter():
    fctx = _make_filter_context([
        {"column": "人物", "operator": "eq", "value": "小红"},
    ])
    columns = [{"name": "人物", "dtype_cn": "字符串"}]
    state = _make_state(columns=columns, row_count=100, filter_context=fctx)
    df = pd.DataFrame({"人物": ["小红"]})
    ctx = ConversationContext.build(state, df, original_row_count=100)
    sections = ctx.to_prompt_sections("full")
    filter_found = any("[当前数据筛选]" in s for s in sections)
    assert filter_found, f"Expected filter section, got: {sections}"
    # Check filtered row count
    dataset_found = any("筛选后" in s for s in sections)
    assert dataset_found


def test_to_prompt_sections_filter_only():
    fctx = _make_filter_context([
        {"column": "人物", "operator": "eq", "value": "小红"},
    ])
    state = _make_state(filter_context=fctx)
    ctx = ConversationContext.build(state, pd.DataFrame(), original_row_count=0)
    sections = ctx.to_prompt_sections("filter")
    assert len(sections) == 1
    assert "[当前数据筛选]" in sections[0]


def test_to_prompt_sections_dataset_only():
    columns = [{"name": "x", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=50)
    df = pd.DataFrame({"x": range(50)})
    ctx = ConversationContext.build(state, df, original_row_count=50)
    sections = ctx.to_prompt_sections("dataset")
    assert len(sections) == 1
    assert "[数据集状态]" in sections[0]
    assert "总行数: 50" in sections[0]


def test_to_prompt_sections_analysis_only():
    artifact = _make_artifact("line", "日期", ["值"])
    state = _make_state(execution_artifacts=[artifact])
    ctx = ConversationContext.build(state, pd.DataFrame(), original_row_count=0)
    sections = ctx.to_prompt_sections("analysis")
    assert len(sections) == 1
    assert "[上一轮分析上下文]" in sections[0]
    assert "line" in sections[0]


def test_to_prompt_sections_multi_layer():
    fctx = _make_filter_context([
        {"column": "人物", "operator": "eq", "value": "小红"},
    ])
    columns = [{"name": "人物", "dtype_cn": "字符串"}]
    state = _make_state(columns=columns, row_count=100, filter_context=fctx)
    df = pd.DataFrame({"人物": ["小红"]})
    ctx = ConversationContext.build(state, df, original_row_count=100)
    sections = ctx.to_prompt_sections("filter dataset")
    assert len(sections) == 2
    assert any("[当前数据筛选]" in s for s in sections)
    assert any("[数据集状态]" in s for s in sections)


def test_to_prompt_sections_returns_list_always():
    """to_prompt_sections() MUST return list[str], never raw string."""
    state = _make_state(row_count=0)
    ctx = ConversationContext.build(state, pd.DataFrame(), original_row_count=0)
    result = ctx.to_prompt_sections("full")
    assert isinstance(result, list)
    result2 = ctx.to_prompt_sections("filter")
    assert isinstance(result2, list)
    result3 = ctx.to_prompt_sections("analysis")
    assert isinstance(result3, list)


def test_to_prompt_sections_unknown_layer():
    """Unknown layer name should be silently ignored."""
    state = _make_state(row_count=0)
    ctx = ConversationContext.build(state, pd.DataFrame(), original_row_count=0)
    sections = ctx.to_prompt_sections("nonexistent")
    assert sections == []


# ═══════════════════════════════════════════════════════════════
# Frozen dataclass tests
# ═══════════════════════════════════════════════════════════════

def test_context_views_are_frozen():
    """All context views and ConversationContext must be immutable."""
    fv = FilterContextView(active_desc=None, is_filtered=False, conditions=[])
    with pytest.raises(Exception):
        fv.is_filtered = True  # type: ignore

    dv = DatasetContextView(filtered_rows=1, total_rows=10, column_summary="x")
    with pytest.raises(Exception):
        dv.filtered_rows = 2  # type: ignore

    av = AnalysisContextView(
        last_intent=None, analysis_goal=None, last_chart_type=None,
        last_x_column=None, last_y_columns=[], last_user_message=None,
        is_continuation=False,
    )
    with pytest.raises(Exception):
        av.is_continuation = True  # type: ignore

    ctx = ConversationContext(filter=fv, dataset=dv, analysis=av)
    with pytest.raises(Exception):
        ctx.filter = fv  # type: ignore


def test_conversation_context_build_frozen():
    columns = [{"name": "x", "dtype_cn": "数值"}]
    state = _make_state(columns=columns, row_count=50)
    df = pd.DataFrame({"x": range(50)})
    ctx = ConversationContext.build(state, df, original_row_count=50)
    assert isinstance(ctx.filter, FilterContextView)
    assert isinstance(ctx.dataset, DatasetContextView)
    assert isinstance(ctx.analysis, AnalysisContextView)
    # Verify it's truly frozen
    with pytest.raises(Exception):
        ctx.dataset.filtered_rows = 999  # type: ignore
