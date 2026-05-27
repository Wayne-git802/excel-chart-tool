"""Tests for Contract Kernel v1.2 — contract_entry and its internal functions."""

import pytest
import pandas as pd
from services.execution_contract import (
    contract_entry,
    _validate_complete,
    _build_candidates,
    _schema_rank,
    _resolve,
    ValidationFailure,
    CandidateSet,
)
from services.column_registry import build_column_registry


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def basic_df():
    return pd.DataFrame({
        "category": ["A", "B", "C", "D", "E"],
        "value1": [10, 20, 30, 40, 50],
        "value2": [1.5, 2.5, 3.5, 4.5, 5.5],
    })


@pytest.fixture
def basic_columns():
    return [
        {"name": "category", "dtype": "object", "dtype_cn": "分类"},
        {"name": "value1", "dtype": "int64", "dtype_cn": "数值"},
        {"name": "value2", "dtype": "float64", "dtype_cn": "数值"},
    ]


@pytest.fixture
def basic_registry(basic_columns):
    return build_column_registry(basic_columns)


# ── _validate_complete ────────────────────────────────────

class TestValidateComplete:

    def test_valid_args_pass(self, basic_df, basic_registry):
        args = {"type": "bar", "x": "category", "y": ["value1"], "title": "Test"}
        failures, warnings = _validate_complete(args, basic_df, basic_registry)
        assert len(failures) == 0

    def test_empty_x_is_fatal(self, basic_df, basic_registry):
        args = {"type": "bar", "x": "", "y": ["value1"], "title": "Test"}
        failures, _ = _validate_complete(args, basic_df, basic_registry)
        x_failures = [f for f in failures if f.field == "x_column"]
        assert any(f.severity == "fatal" for f in x_failures)

    def test_empty_y_is_fatal(self, basic_df, basic_registry):
        args = {"type": "bar", "x": "category", "y": [], "title": "Test"}
        failures, _ = _validate_complete(args, basic_df, basic_registry)
        y_failures = [f for f in failures if f.field == "y_columns"]
        assert any(f.severity == "fatal" for f in y_failures)

    def test_missing_column_fuzzy_match(self, basic_df, basic_registry):
        args = {"type": "bar", "x": "categry", "y": ["value1"], "title": "Test"}
        failures, _ = _validate_complete(args, basic_df, basic_registry)
        x_failures = [f for f in failures if f.field == "x_column"]
        assert any(f.suggestion == "category" for f in x_failures)

    def test_invalid_chart_type(self, basic_df, basic_registry):
        args = {"type": "radar", "x": "category", "y": ["value1"], "title": "Test"}
        failures, _ = _validate_complete(args, basic_df, basic_registry)
        assert any(f.field == "chart_type" for f in failures)

    def test_empty_title_warns_not_fails(self, basic_df, basic_registry):
        args = {"type": "bar", "x": "category", "y": ["value1"], "title": ""}
        failures, warnings = _validate_complete(args, basic_df, basic_registry)
        assert len(failures) == 0
        assert len(warnings) >= 1


# ── _build_candidates ─────────────────────────────────────

class TestBuildCandidates:

    def test_with_category_and_numeric(self, basic_registry):
        cs = _build_candidates(basic_registry)
        assert "bar" in cs.valid_charts
        assert "line" in cs.valid_charts
        assert "scatter" in cs.valid_charts  # 2 numeric
        assert "histogram" in cs.valid_charts

    def test_bar_needs_numeric(self):
        """bar needs at least 1 numeric column to be feasible."""
        r = build_column_registry([{"name": "cat", "dtype": "object", "dtype_cn": "分类"}])
        cs = _build_candidates(r)
        assert cs.valid_charts == [], "0 numeric → no valid charts at all"

        r2 = build_column_registry([
            {"name": "cat", "dtype": "object", "dtype_cn": "分类"},
            {"name": "val", "dtype": "int64", "dtype_cn": "数值"},
        ])
        cs2 = _build_candidates(r2)
        assert "bar" in cs2.valid_charts, "1 numeric → bar is feasible"

    def test_pie_needs_category_and_single_numeric(self, basic_registry):
        cs = _build_candidates(basic_registry)
        # Has category + 2 numeric → pie NOT in valid (needs exactly 1 numeric)
        assert "pie" not in cs.valid_charts

    def test_scatter_needs_two_numeric(self):
        r = build_column_registry([
            {"name": "cat", "dtype": "object", "dtype_cn": "分类"},
            {"name": "val1", "dtype": "int64", "dtype_cn": "数值"},
        ])
        cs = _build_candidates(r)
        assert "scatter" not in cs.valid_charts, "scatter needs >= 2 numeric"

    def test_exclusion_reasons(self, basic_registry):
        cs = _build_candidates(basic_registry)
        # Pie should be excluded (2 numeric, not 1)
        assert "pie" in cs.exclusion_reasons


# ── _schema_rank ──────────────────────────────────────────

class TestSchemaRank:

    def test_line_with_time_is_perfect(self):
        r = build_column_registry([
            {"name": "日期", "dtype": "datetime64", "dtype_cn": "日期"},
            {"name": "sales", "dtype": "int64", "dtype_cn": "数值"},
        ])
        assert _schema_rank("line", r) == 0

    def test_line_without_time(self, basic_registry):
        assert _schema_rank("line", basic_registry) == 1

    def test_bar_with_category(self, basic_registry):
        assert _schema_rank("bar", basic_registry) == 0

    def test_bar_without_category(self):
        r = build_column_registry([
            {"name": "val1", "dtype": "int64", "dtype_cn": "数值"},
            {"name": "val2", "dtype": "int64", "dtype_cn": "数值"},
        ])
        assert _schema_rank("bar", r) == 1

    def test_scatter_perfect(self):
        r = build_column_registry([
            {"name": "val1", "dtype": "int64", "dtype_cn": "数值"},
            {"name": "val2", "dtype": "int64", "dtype_cn": "数值"},
        ])
        assert _schema_rank("scatter", r) == 0

    def test_scatter_one_numeric(self):
        r = build_column_registry([
            {"name": "val1", "dtype": "int64", "dtype_cn": "数值"},
        ])
        assert _schema_rank("scatter", r) == 3

    def test_histogram_rich(self):
        r = build_column_registry([
            {"name": f"v{i}", "dtype": "int64", "dtype_cn": "数值"}
            for i in range(5)
        ])
        assert _schema_rank("histogram", r) == 0


# ── _resolve (deterministic rank) ─────────────────────────

class TestResolve:

    def test_intent_match_wins(self, basic_registry):
        cs = CandidateSet(valid_charts=["bar", "line", "scatter"])
        result = _resolve({}, cs, "帮我分析趋势变化", basic_registry)
        assert result["chart_type"] == "line", "intent=趋势 should pick line"

    def test_no_intent_defaults_to_bar(self, basic_registry):
        cs = CandidateSet(valid_charts=["bar", "line", "scatter", "histogram"])
        result = _resolve({}, cs, "展示数据", basic_registry)
        assert result["chart_type"] == "bar", "no intent + bar priority 0"

    def test_deterministic_same_input(self, basic_registry):
        cs = CandidateSet(valid_charts=["bar", "line", "scatter"])
        r1 = _resolve({}, cs, "分析趋势变化", basic_registry)
        r2 = _resolve({}, cs, "分析趋势变化", basic_registry)
        assert r1["chart_type"] == r2["chart_type"], "same input must produce same output"

    def test_limited_candidates(self):
        r = build_column_registry([
            {"name": "val1", "dtype": "int64", "dtype_cn": "数值"},
        ])
        cs = CandidateSet(valid_charts=["bar", "line", "histogram", "boxplot"])
        result = _resolve({}, cs, "分析分布情况", r)
        assert result["chart_type"] in ["histogram", "bar"]


# ── contract_entry integration ────────────────────────────

class TestContractEntry:

    EXPECTED_KEYS = {"chart_type", "x", "y", "title", "status", "trace_id", "narratives", "explanation", "_locked"}

    def test_schema_lock(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "category", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "展示数据",
            "policy": "exploratory",
        })
        assert set(result.keys()) == self.EXPECTED_KEYS

    def test_normalize_y_string_to_list(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "category", "y": "value1", "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "展示数据",
            "policy": "exploratory",
        })
        assert result["status"] == "approved"
        assert result["y"] == ["value1"]

    def test_empty_x_degraded(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "展示数据",
            "policy": "exploratory",
        })
        assert result["status"] == "degraded"

    def test_empty_y_degraded(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "category", "y": [], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "展示数据",
            "policy": "exploratory",
        })
        assert result["status"] == "degraded"

    def test_strict_policy_rejected(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "展示数据",
            "policy": "strict",
        })
        assert result["status"] == "rejected"

    def test_intent_preserved(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "category", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "分析趋势变化",
            "policy": "exploratory",
        })
        assert result["chart_type"] == "line", "intent=趋势 should pick line"

    def test_no_intent_default(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "category", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "展示数据",
            "policy": "exploratory",
        })
        assert result["chart_type"] == "bar", "default when no intent"

    def test_deterministic(self, basic_df, basic_columns):
        inp = {
            "args": {"type": "bar", "x": "category", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "分析趋势变化",
            "policy": "exploratory",
        }
        r1 = contract_entry(inp)
        r2 = contract_entry(inp)
        assert r1["chart_type"] == r2["chart_type"]

    def test_narratives_on_type_change(self, basic_df, basic_columns):
        result = contract_entry({
            "args": {"type": "bar", "x": "category", "y": ["value1"], "title": "Test"},
            "df": basic_df,
            "columns": basic_columns,
            "message": "分析趋势变化",
            "policy": "exploratory",
        })
        # "bar" → "line" change should produce narrative
        assert len(result["narratives"]) >= 1
