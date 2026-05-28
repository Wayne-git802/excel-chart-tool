"""Tests for serialization — ops ↔ JSON round-trip."""

from core.v2.ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp
from core.v2.serialization.ops_json import ops_to_json, json_to_ops


class TestSerialization:
    def test_filter_roundtrip(self):
        ops = (FilterOp("column_range", "年份", {"min": 2010, "max": 2015}),)
        ops2 = json_to_ops(ops_to_json(ops))
        assert len(ops2) == 1
        assert isinstance(ops2[0], FilterOp)
        assert ops2[0].filter_type == "column_range"
        assert ops2[0].column == "年份"
        assert ops2[0].params == {"min": 2010, "max": 2015}

    def test_sort_roundtrip(self):
        ops = (SortOp("销售额", "desc"),)
        ops2 = json_to_ops(ops_to_json(ops))
        assert isinstance(ops2[0], SortOp)
        assert ops2[0].column == "销售额"
        assert ops2[0].direction == "desc"

    def test_limit_roundtrip(self):
        ops = (LimitOp(5),)
        ops2 = json_to_ops(ops_to_json(ops))
        assert ops2[0].n == 5

    def test_chart_roundtrip(self):
        ops = (ChartPatchOp(chart_type="bar", x_column="x",
                            y_columns=("a", "b"), title="test"),)
        ops2 = json_to_ops(ops_to_json(ops))
        assert isinstance(ops2[0], ChartPatchOp)
        assert ops2[0].chart_type == "bar"
        assert ops2[0].y_columns == ("a", "b")

    def test_mixed_roundtrip(self):
        ops = (
            FilterOp("value_match", "品类", {"value": "手机"}),
            SortOp("销售额", "desc"),
            LimitOp(10),
            ChartPatchOp(chart_type="line"),
        )
        ops2 = json_to_ops(ops_to_json(ops))
        assert len(ops2) == 4
        assert isinstance(ops2[0], FilterOp)
        assert isinstance(ops2[1], SortOp)
        assert isinstance(ops2[2], LimitOp)
        assert isinstance(ops2[3], ChartPatchOp)
