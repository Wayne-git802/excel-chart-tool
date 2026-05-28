"""Tests for replay engine — canonical_order, replay determinism."""

import pandas as pd
import pytest
from core.v2.ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp
from core.v2.ir.view_spec import ViewSpec
from core.v2.backends.pandas_backend import PandasBackend
from core.v2.engine.replay import canonical_order, replay


@pytest.fixture
def df():
    return pd.DataFrame({
        "年份": [2020, 2021, 2019, 2022, 2018],
        "品类": ["手机", "电脑", "手机", "电脑", "平板"],
        "销售额": [100, 300, 200, 400, 150],
    })


@pytest.fixture
def be():
    return PandasBackend()


class TestCanonicalOrder:
    def test_filter_sort_limit(self):
        vs = (ViewSpec()
              .apply(FilterOp("column_range", "年份", {"min": 2019}))
              .apply(SortOp("销售额", "desc"))
              .apply(LimitOp(3)))
        ops = canonical_order(vs)
        types = [type(o).__name__ for o in ops]
        assert types == ["FilterOp", "SortOp", "LimitOp"]

    def test_limit_sort_reordered(self):
        """limit before sort → reordered to sort before limit."""
        vs = ViewSpec().apply(LimitOp(3)).apply(SortOp("销售额", "desc"))
        ops = canonical_order(vs)
        types = [type(o).__name__ for o in ops]
        assert types.index("SortOp") < types.index("LimitOp")

    def test_chart_excluded(self):
        vs = ViewSpec().apply(ChartPatchOp(chart_type="pie"))
        ops = canonical_order(vs)
        types = [type(o).__name__ for o in ops]
        assert "ChartPatchOp" not in types


class TestReplay:
    def test_filter_column_range(self, df, be):
        vs = ViewSpec().apply(FilterOp("column_range", "年份", {"min": 2020, "max": 2021}))
        result = replay(df, vs, be)
        assert be.row_count(result) == 2

    def test_filter_value_match(self, df, be):
        vs = ViewSpec().apply(FilterOp("value_match", "品类", {"value": "手机"}))
        result = replay(df, vs, be)
        assert be.row_count(result) == 2

    def test_filter_expression(self, df, be):
        vs = ViewSpec().apply(FilterOp("expression", "销售额", {"op": ">", "value": 200}))
        result = replay(df, vs, be)
        assert be.row_count(result) == 2

    def test_multiple_filters(self, df, be):
        vs = (ViewSpec()
              .apply(FilterOp("column_range", "年份", {"min": 2019}))
              .apply(FilterOp("expression", "销售额", {"op": ">", "value": 150})))
        result = replay(df, vs, be)
        assert be.row_count(result) == 3

    def test_sort(self, df, be):
        vs = ViewSpec().apply(SortOp("销售额", "desc"))
        result = replay(df, vs, be)
        assert int(result.iloc[0]["销售额"]) == 400

    def test_limit(self, df, be):
        vs = ViewSpec().apply(LimitOp(2))
        result = replay(df, vs, be)
        assert be.row_count(result) == 2

    def test_sort_then_limit(self, df, be):
        vs = ViewSpec().apply(SortOp("销售额", "desc")).apply(LimitOp(3))
        result = replay(df, vs, be)
        assert be.row_count(result) == 3
        assert int(result.iloc[0]["销售额"]) == 400

    def test_limit_then_sort_same_result(self, df, be):
        """Limit before sort → canonical_order ensures same result as sort then limit."""
        vs_a = ViewSpec().apply(SortOp("销售额", "desc")).apply(LimitOp(3))
        vs_b = ViewSpec().apply(LimitOp(3)).apply(SortOp("销售额", "desc"))
        result_a = replay(df, vs_a, be)
        result_b = replay(df, vs_b, be)
        assert result_a.equals(result_b)

    def test_chart_no_effect(self, df, be):
        vs_ref = ViewSpec().apply(SortOp("销售额", "desc"))
        vs_chart = vs_ref.apply(ChartPatchOp(chart_type="pie"))
        assert replay(df, vs_ref, be).equals(replay(df, vs_chart, be))

    def test_not_mutate_base(self, df, be):
        original_rows = be.row_count(df)
        vs = ViewSpec().apply(LimitOp(2))
        replay(df, vs, be)
        assert be.row_count(df) == original_rows
