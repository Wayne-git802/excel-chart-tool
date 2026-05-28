"""Property tests for determinism guarantees."""

import pandas as pd
from core.v2.ir.operations import FilterOp, SortOp, LimitOp
from core.v2.ir.view_spec import ViewSpec
from core.v2.backends.pandas_backend import PandasBackend
from core.v2.engine.replay import replay
from core.v2.serialization.ops_json import ops_to_json, json_to_ops


def make_df():
    return pd.DataFrame({
        "年份": [2020, 2021, 2019, 2022, 2018],
        "品类": ["手机", "电脑", "手机", "电脑", "平板"],
        "销售额": [100, 300, 200, 400, 150],
    })


be = PandasBackend()


def test_serialization_determinism():
    """P1: replay result identical after serialize → deserialize."""
    df = make_df()
    vs = (ViewSpec()
          .apply(FilterOp("column_range", "年份", {"min": 2019}))
          .apply(SortOp("销售额", "desc"))
          .apply(LimitOp(3)))

    result1 = replay(df, vs, be)

    ops_json = ops_to_json(vs.operations)
    ops2 = json_to_ops(ops_json)
    vs2 = ViewSpec(operations=ops2)
    result2 = replay(df, vs2, be)

    assert result1.equals(result2), "Serialization round-trip broke determinism"


def test_undo_append_reverts():
    """P2: undo(apply(state, filter)) → materialize matches original."""
    df = make_df()
    vs_orig = ViewSpec()
    vs_after = vs_orig.apply(FilterOp("value_match", "品类", {"value": "手机"}))
    vs_undone, _ = vs_after.undo()

    result_orig = replay(df, vs_orig, be)
    result_undone = replay(df, vs_undone, be)
    assert result_orig.equals(result_undone), "Undo APPEND did not revert to original"


def test_undo_replace_with_prev():
    """P3: undo(apply(apply(state, sortA), sortB)) → matches apply(state, sortA)."""
    df = make_df()
    vs_base = ViewSpec()
    vs_a = vs_base.apply(SortOp("销售额", "asc"))
    vs_b = vs_a.apply(SortOp("年份", "desc"))
    vs_undone, removed = vs_b.undo()

    assert removed.column == "年份"
    result_a = replay(df, vs_a, be)
    result_undone = replay(df, vs_undone, be)
    assert result_a.equals(result_undone), "Undo REPLACE with prev did not restore"


def test_sort_limit_order_independent():
    """P4: sort+limit and limit+sort produce same result after canonical_order."""
    df = make_df()
    vs_a = ViewSpec().apply(SortOp("销售额", "desc")).apply(LimitOp(3))
    vs_b = ViewSpec().apply(LimitOp(3)).apply(SortOp("销售额", "desc"))

    result_a = replay(df, vs_a, be)
    result_b = replay(df, vs_b, be)
    assert result_a.equals(result_b), "Sort+limit order dependence — canonical_order broken"


def test_full_undo_returns_to_original():
    """P5: apply N ops → undo N times → result equals original."""
    df = make_df()
    vs = ViewSpec()
    ops_applied = [
        FilterOp("column_range", "年份", {"min": 2019}),
        SortOp("销售额", "desc"),
        LimitOp(2),
    ]

    for op in ops_applied:
        vs = vs.apply(op)

    # undo all
    for _ in range(len(ops_applied)):
        vs, _ = vs.undo()

    result_orig = replay(df, ViewSpec(), be)
    result_undone = replay(df, vs, be)
    assert result_orig.equals(result_undone), "Full undo did not return to original"
