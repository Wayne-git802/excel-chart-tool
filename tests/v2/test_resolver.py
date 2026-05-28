"""Tests for ChartResolver."""

import pandas as pd
from core.v2.ir.operations import ChartPatchOp
from core.v2.ir.view_spec import ViewSpec
from core.v2.ir.column_info import ColumnInfo
from core.v2.engine.resolver import resolve_chart


def make_cols(*names):
    return [ColumnInfo(name=n, dtype="int64", dtype_cn="整数") for n in names]


class TestResolveChart:
    def test_no_preference_fallback(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        vs = ViewSpec()
        chart = resolve_chart(df, vs, make_cols("a", "b"))
        assert chart["source"] == "v10_fallback"
        assert chart["chart_type"] == "bar"
        assert not chart["degraded"]

    def test_preference_valid(self):
        df = pd.DataFrame({"x": [1], "y": [2]})
        vs = ViewSpec().apply(ChartPatchOp(chart_type="line", x_column="x",
                                           y_columns=("y",)))
        chart = resolve_chart(df, vs, make_cols("x", "y"))
        assert chart["source"] == "preference"
        assert chart["chart_type"] == "line"
        assert not chart["degraded"]

    def test_preference_invalid_degraded(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        vs = ViewSpec().apply(ChartPatchOp(chart_type="pie", x_column="不存在"))
        chart = resolve_chart(df, vs, make_cols("a", "b"))
        assert chart["degraded"]
        assert chart["source"] == "v10_fallback"

    def test_partial_chart_autofill(self):
        df = pd.DataFrame({"x": [1], "y": [2]})
        vs = ViewSpec().apply(ChartPatchOp(chart_type="scatter"))
        chart = resolve_chart(df, vs, make_cols("x", "y"))
        assert chart["chart_type"] == "scatter"
        assert chart["x_column"] is not None
        assert len(chart["y_columns"]) > 0

    def test_single_column_fallback(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        vs = ViewSpec()
        chart = resolve_chart(df, vs, make_cols("a"))
        assert chart["chart_type"] == "table"
