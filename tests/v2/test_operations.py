"""Tests for Operation IR — frozen dataclasses, OpClass correctness."""

import pytest
from core.v2.ir.operations import (
    OpClass, FilterOp, SortOp, LimitOp, ChartPatchOp, Operation
)


class TestFilterOp:
    def test_creation(self):
        f = FilterOp("column_range", "年份", {"min": 2010, "max": 2015})
        assert f.filter_type == "column_range"
        assert f.column == "年份"
        assert f.params == {"min": 2010, "max": 2015}

    def test_op_class_is_append(self):
        f = FilterOp("value_match", "品类", {"value": "手机"})
        assert f.op_class == OpClass.APPEND

    def test_has_unique_id(self):
        f1 = FilterOp("expression", "x", {"op": ">", "value": 0})
        f2 = FilterOp("expression", "x", {"op": ">", "value": 0})
        assert f1.op_id != f2.op_id

    def test_frozen(self):
        f = FilterOp("column_range", "x")
        with pytest.raises(Exception):
            f.column = "y"  # type: ignore

    def test_defaults(self):
        f = FilterOp("value_match")
        assert f.column is None
        assert f.params == {}
        assert f.op_version == 1


class TestSortOp:
    def test_creation(self):
        s = SortOp("销售额", "desc")
        assert s.column == "销售额"
        assert s.direction == "desc"

    def test_default_direction(self):
        s = SortOp("x")
        assert s.direction == "desc"

    def test_op_class_is_replace(self):
        s = SortOp("x")
        assert s.op_class == OpClass.REPLACE

    def test_frozen(self):
        s = SortOp("x")
        with pytest.raises(Exception):
            s.column = "y"  # type: ignore


class TestLimitOp:
    def test_creation(self):
        l = LimitOp(10)
        assert l.n == 10

    def test_op_class_is_replace(self):
        l = LimitOp(5)
        assert l.op_class == OpClass.REPLACE

    def test_frozen(self):
        l = LimitOp(3)
        with pytest.raises(Exception):
            l.n = 5  # type: ignore


class TestChartPatchOp:
    def test_creation(self):
        c = ChartPatchOp(chart_type="bar", x_column="品类",
                         y_columns=("销售额",), title="分析")
        assert c.chart_type == "bar"
        assert c.x_column == "品类"
        assert c.y_columns == ("销售额",)
        assert c.title == "分析"

    def test_partial(self):
        c = ChartPatchOp(chart_type="pie")
        assert c.chart_type == "pie"
        assert c.x_column is None
        assert c.y_columns is None

    def test_all_none(self):
        c = ChartPatchOp()
        assert c.chart_type is None

    def test_op_class_is_replace(self):
        c = ChartPatchOp()
        assert c.op_class == OpClass.REPLACE

    def test_frozen(self):
        c = ChartPatchOp(chart_type="bar")
        with pytest.raises(Exception):
            c.chart_type = "line"  # type: ignore


class TestOperationUnion:
    def test_union_accepts_all(self):
        ops: list[Operation] = [
            FilterOp("value_match"),
            SortOp("x"),
            LimitOp(5),
            ChartPatchOp(),
        ]
        assert len(ops) == 4
