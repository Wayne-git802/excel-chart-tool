"""Phase 3 tests — StateTransformer, Contract DSL, apply_filter, replay."""

import pandas as pd
import json
import pytest

from core.ir.profile import DatasetProfile, ColumnProfile, ContextualProfile
from core.ir.contract import AnalysisIntent, FilterSpec, FilterCondition, ChartDecision
from core.ir.failure import ExplicitFailure
from core.profiling.profiler import DataProfiler
from core.profiling.transformer import StateTransformer
from core.contract.v10_contract import resolve
from core.filtering.executor import apply_filter


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _make_test_df():
    return pd.DataFrame({
        "日期": pd.date_range("2025-01-01", periods=5),
        "销售额": [100.0, 200.0, 150.0, 300.0, 250.0],
        "类别": ["A", "B", "A", "C", "B"],
        "姓名": ["张三", "李四", "王五", "张三", "李四"],
    })


def _make_profile(df):
    columns = [
        {"name": "日期", "dtype": "datetime64", "dtype_cn": "日期", "unique_count": len(df), "null_pct": 0,
         "min": None, "max": None, "mean": None},
        {"name": "销售额", "dtype": "float64", "dtype_cn": "数值", "unique_count": len(df), "null_pct": 0,
         "min": float(df["销售额"].min()), "max": float(df["销售额"].max()), "mean": float(df["销售额"].mean())},
        {"name": "类别", "dtype": "object", "dtype_cn": "分类", "unique_count": df["类别"].nunique(), "null_pct": 0,
         "min": None, "max": None, "mean": None},
        {"name": "姓名", "dtype": "object", "dtype_cn": "文本", "unique_count": df["姓名"].nunique(), "null_pct": 0,
         "min": None, "max": None, "mean": None},
    ]
    return DataProfiler.enhance(columns, df)


# ═══════════════════════════════════════════════════════════════
# StateTransformer
# ═══════════════════════════════════════════════════════════════

class TestStateTransformer:
    def test_no_filter_same_as_global(self):
        df = _make_test_df()
        profile = _make_profile(df)
        ctx = StateTransformer.transform(profile, None, df)
        assert ctx.row_count == 5
        assert ctx.temporal_cols == ["日期"]
        assert ctx.numeric_cols == ["销售额"]

    def test_filter_reduces_cardinality(self):
        df = _make_test_df()
        profile = _make_profile(df)
        fs = FilterSpec(conditions=[FilterCondition("姓名", "in", ["张三"])])
        df_f = df[df["姓名"] == "张三"]
        ctx = StateTransformer.transform(profile, fs, df_f)
        assert ctx.row_count == 2
        assert ctx.filter_applied is True

    def test_filter_collapses_categorical(self):
        """Category with only 1 unique after filter → demoted."""
        df = _make_test_df()
        profile = _make_profile(df)
        fs = FilterSpec(conditions=[FilterCondition("类别", "eq", "B")])
        df_f = df[df["类别"] == "B"]
        ctx = StateTransformer.transform(profile, fs, df_f)
        # "类别" should be demoted from categorical
        assert "类别" not in ctx.categorical_cols


# ═══════════════════════════════════════════════════════════════
# apply_filter
# ═══════════════════════════════════════════════════════════════

class TestApplyFilter:
    def test_empty_filter_returns_df(self):
        df = _make_test_df()
        result = apply_filter(df, FilterSpec())
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5

    def test_eq_filter(self):
        df = _make_test_df()
        fs = FilterSpec(conditions=[FilterCondition("类别", "eq", "A")])
        result = apply_filter(df, fs)
        assert len(result) == 2

    def test_in_filter(self):
        df = _make_test_df()
        fs = FilterSpec(conditions=[FilterCondition("姓名", "in", ["张三", "李四"])])
        result = apply_filter(df, fs)
        assert len(result) == 4

    def test_gt_filter(self):
        df = _make_test_df()
        fs = FilterSpec(conditions=[FilterCondition("销售额", "gt", 200)])
        result = apply_filter(df, fs)
        assert len(result) == 2

    def test_empty_result(self):
        df = _make_test_df()
        fs = FilterSpec(conditions=[FilterCondition("姓名", "eq", "不存在")])
        result = apply_filter(df, fs)
        assert isinstance(result, ExplicitFailure)
        assert result.code == "empty_data"

    def test_missing_column(self):
        df = _make_test_df()
        fs = FilterSpec(conditions=[FilterCondition("xyz", "eq", 1)])
        result = apply_filter(df, fs)
        assert isinstance(result, ExplicitFailure)
        assert result.code == "invalid_filter_column"


# ═══════════════════════════════════════════════════════════════
# Contract DSL
# ═══════════════════════════════════════════════════════════════

class TestContractV10:
    def test_trend_intent_gives_line(self):
        df = _make_test_df()
        profile = _make_profile(df)
        ctx = StateTransformer.transform(profile, None, df)
        intent = AnalysisIntent(type="trend", confidence=0.9)
        decision, ledger = resolve(ctx, intent)
        assert decision.chart_type == "line"
        assert decision.decision_source == "profile_rule"
        assert len(ledger.steps) == 2

    def test_explicit_chart_overrides(self):
        df = _make_test_df()
        profile = _make_profile(df)
        ctx = StateTransformer.transform(profile, None, df)
        intent = AnalysisIntent(type="trend", confidence=0.9, explicit_chart="scatter")
        decision, ledger = resolve(ctx, intent)
        assert decision.chart_type == "scatter"
        assert decision.decision_source == "explicit_user"

    def test_comparison_gives_bar(self):
        df = _make_test_df()
        profile = _make_profile(df)
        ctx = StateTransformer.transform(profile, None, df)
        intent = AnalysisIntent(type="comparison", confidence=0.9)
        decision, _ = resolve(ctx, intent)
        assert decision.chart_type == "bar"

    def test_fallback_when_no_match(self):
        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
        columns = [
            {"name": "x", "dtype": "int64", "dtype_cn": "数值", "unique_count": 3, "null_pct": 0,
             "min": 1, "max": 3, "mean": 2.0},
            {"name": "y", "dtype": "int64", "dtype_cn": "数值", "unique_count": 3, "null_pct": 0,
             "min": 4, "max": 6, "mean": 5.0},
        ]
        profile = DataProfiler.enhance(columns, df)
        ctx = StateTransformer.transform(profile, None, df)
        intent = AnalysisIntent(type="UNKNOWN", confidence=0.3)
        decision, _ = resolve(ctx, intent)
        assert decision.chart_type == "bar"
        assert decision.decision_source == "fallback"

    def test_ledger_serializable(self):
        df = _make_test_df()
        profile = _make_profile(df)
        ctx = StateTransformer.transform(profile, None, df)
        intent = AnalysisIntent(type="trend", confidence=0.9)
        _, ledger = resolve(ctx, intent)
        d = ledger.to_dict()
        assert json.dumps(d)


# ═══════════════════════════════════════════════════════════════
# Replay test — determinism
# ═══════════════════════════════════════════════════════════════

class TestReplay:
    """Same (profile, intent) → same (chart_type, x_col, y_cols)."""

    def test_deterministic_output(self):
        df = _make_test_df()
        profile = _make_profile(df)
        ctx = StateTransformer.transform(profile, None, df)
        intent = AnalysisIntent(type="trend", confidence=0.9)

        decision1, _ = resolve(ctx, intent)
        decision2, _ = resolve(ctx, intent)

        assert decision1.chart_type == decision2.chart_type
        assert decision1.x_column == decision2.x_column
        assert decision1.y_columns == decision2.y_columns

    def test_deterministic_with_filter(self):
        df = _make_test_df()
        profile = _make_profile(df)
        fs = FilterSpec(conditions=[FilterCondition("姓名", "in", ["张三"])])
        df_f = df[df["姓名"] == "张三"]
        ctx = StateTransformer.transform(profile, fs, df_f)
        intent = AnalysisIntent(type="comparison", confidence=0.9)

        d1, _ = resolve(ctx, intent)
        d2, _ = resolve(ctx, intent)

        assert d1.chart_type == d2.chart_type
        assert d1.x_column == d2.x_column
