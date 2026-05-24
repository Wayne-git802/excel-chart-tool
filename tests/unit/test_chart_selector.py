"""Tests for ChartSelector v4.1 — intent-preserving arbitration.

Key behavioral contract:
  - Intent ALWAYS wins when hard-feasible (drawable).
  - Schema scores are used ONLY when no intent is present.
  - Semantic scoring informs annotation, never overrides intent.
"""

import pytest
from services.chart_selector import select_chart_type


# ── Helpers ──────────────────────────────────────────────────

def _col(name, dtype="float64", dtype_cn="数值"):
    return {"name": name, "dtype": dtype, "dtype_cn": dtype_cn}


# ═══════════════════════════════════════════════════════════════
# Intent preservation: user intent wins when drawable
# ═══════════════════════════════════════════════════════════════

def test_trend_intent_with_time_column_is_line():
    """趋势 + 时间列 → line."""
    cols = [_col("日期", dtype_cn="日期"), _col("销售额")]
    assert select_chart_type(cols, query="分析销售趋势") == "line"


def test_trend_intent_with_two_numeric_no_time_is_still_line():
    """趋势 + 身高/体重(无时间列) → line. Intent preserved, index as pseudo-time.

    This is the core fix of v4 over v3: schema cannot override user intent.
    """
    cols = [_col("身高"), _col("体重")]
    assert select_chart_type(cols, query="看看趋势") == "line"


def test_trend_intent_with_single_numeric_is_line():
    """趋势 + 单数值列 → line (index-based)."""
    cols = [_col("销售额")]
    assert select_chart_type(cols, query="展示趋势") == "line"


def test_comparison_intent_is_bar():
    cols = [
        {"name": "城市", "dtype": "object", "dtype_cn": "分类"},
        _col("销售额"),
    ]
    assert select_chart_type(cols, query="对比各城市") == "bar"


def test_scatter_intent_is_scatter():
    cols = [_col("身高"), _col("体重")]
    assert select_chart_type(cols, query="看相关关系") == "scatter"


def test_distribution_intent_is_histogram():
    cols = [_col("成绩"), _col("年龄"), _col("收入")]
    assert select_chart_type(cols, query="数据分布") == "histogram"


def test_pie_intent_is_pie():
    cols = [
        {"name": "类别", "dtype": "object", "dtype_cn": "分类"},
        _col("金额"),
    ]
    assert select_chart_type(cols, query="占比分析") == "pie"


# ═══════════════════════════════════════════════════════════════
# Multi-intent: primary always wins when feasible
# ═══════════════════════════════════════════════════════════════

def test_multi_intent_primary_wins():
    """趋势+对比 → primary=line wins (feasible with time col)."""
    cols = [_col("月份", dtype_cn="日期"), _col("销售额")]
    assert select_chart_type(cols, query="分析销售趋势并对比各类别") == "line"


def test_multi_intent_primary_wins_even_without_time():
    """趋势+对比 → primary=line, feasible (1+ numeric) → line wins.

    Secondary 'bar' is also feasible but primary intent takes priority.
    """
    cols = [
        {"name": "城市", "dtype": "object", "dtype_cn": "分类"},
        _col("销售额"),
    ]
    assert select_chart_type(cols, query="分析趋势并对比") == "line"


# ═══════════════════════════════════════════════════════════════
# Secondary kicks in when primary NOT feasible
# ═══════════════════════════════════════════════════════════════

def test_scatter_not_feasible_with_one_numeric():
    """scatter needs 2 numeric. With only 1 numeric + scatter intent → secondary."""
    cols = [
        {"name": "城市", "dtype": "object", "dtype_cn": "分类"},
        _col("销售额"),
    ]
    # scatter not feasible (n_numeric=1 < 2), no secondary → schema fallback → bar
    assert select_chart_type(cols, query="看关系") == "bar"


def test_pie_not_feasible_without_category():
    """pie needs category + numeric. 2 numeric only → pie infeasible → schema fallback."""
    cols = [_col("身高"), _col("体重")]
    # pie infeasible, no secondary → schema: scatter 0.8 wins
    assert select_chart_type(cols, query="占比例") == "scatter"


# ═══════════════════════════════════════════════════════════════
# No intent: schema decides
# ═══════════════════════════════════════════════════════════════

def test_no_intent_two_numeric_is_scatter():
    cols = [_col("身高"), _col("体重")]
    assert select_chart_type(cols, query="") == "scatter"


def test_no_intent_category_plus_numeric_is_bar():
    cols = [
        {"name": "城市", "dtype": "object", "dtype_cn": "分类"},
        _col("销售额"),
    ]
    assert select_chart_type(cols, query="") == "bar"


def test_no_intent_time_plus_numeric_is_line():
    cols = [_col("date", dtype_cn="日期"), _col("revenue")]
    assert select_chart_type(cols, query="") == "line"


def test_no_intent_three_plus_numeric_is_histogram():
    cols = [_col("a"), _col("b"), _col("c")]
    assert select_chart_type(cols, query="") == "histogram"


# ═══════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════

def test_empty_columns_falls_back_to_bar():
    assert select_chart_type([], query="") == "bar"


def test_empty_query_empty_columns():
    assert select_chart_type([], query="") == "bar"


def test_chinese_column_types():
    cols = [
        {"name": "城市", "dtype": "object", "dtype_cn": "分类"},
        {"name": "销量", "dtype": "int32", "dtype_cn": "整数"},
    ]
    assert select_chart_type(cols, query="") == "bar"


def test_no_intent_with_query_no_match():
    """Query with no chart keywords → no intent → schema decides."""
    cols = [_col("身高"), _col("体重")]
    assert select_chart_type(cols, query="看看数据") == "scatter"
