"""Phase 0 tests — IR construction, immutability, serialization roundtrip."""

import json
import pytest

from core.ir import (
    DatasetProfile, ColumnProfile, ContextualProfile,
    AnalysisIntent, FilterCondition, FilterSpec, CapabilityResult, ChartDecision,
    ChartFacts,
    DecisionStep, DecisionLedger, FilterContext,
    ExplicitFailure,
)


class TestColumnProfile:
    def test_construction(self):
        cp = ColumnProfile(name="日期", semantic_type="temporal", raw_dtype="datetime64",
                           null_rate=0.0, unique_count=50, cardinality="high")
        assert cp.name == "日期"
        assert cp.semantic_type == "temporal"
        assert cp.cardinality == "high"

    def test_defaults(self):
        cp = ColumnProfile(name="x", semantic_type="UNKNOWN", raw_dtype="object",
                           null_rate=0.0, unique_count=0, cardinality="low")
        assert cp.distribution is None
        assert cp.mean is None

    def test_immutability(self):
        cp = ColumnProfile(name="x", semantic_type="UNKNOWN", raw_dtype="object",
                           null_rate=0.0, unique_count=0, cardinality="low")
        with pytest.raises(Exception):
            cp.name = "y"  # frozen dataclass

    def test_roundtrip(self):
        cp = ColumnProfile(name="销售额", semantic_type="numeric", raw_dtype="float64",
                           null_rate=0.02, unique_count=48, cardinality="medium",
                           distribution="right_skewed", min=100.0, max=50000.0,
                           mean=27000.0, median=25000.0)
        d = cp.to_dict()
        assert json.dumps(d)  # JSON serializable
        restored = ColumnProfile.from_dict(d)
        assert restored.name == cp.name
        assert restored.semantic_type == cp.semantic_type
        assert restored.mean == cp.mean
        assert restored.distribution == cp.distribution


class TestDatasetProfile:
    def test_construction(self):
        dp = DatasetProfile(version="1.0", hash="abc123", row_count=100, column_count=3)
        assert dp.version == "1.0"
        assert dp.temporal_cols == []

    def test_roundtrip(self):
        cp = ColumnProfile(name="日期", semantic_type="temporal", raw_dtype="datetime64",
                           null_rate=0.0, unique_count=50, cardinality="high")
        dp = DatasetProfile(version="1.0", hash="abc", row_count=50, column_count=1,
                            columns={"日期": cp}, temporal_cols=["日期"],
                            numeric_cols=[], categorical_cols=[])
        d = dp.to_dict()
        assert json.dumps(d)
        restored = DatasetProfile.from_dict(d)
        assert restored.version == dp.version
        assert restored.temporal_cols == ["日期"]
        assert restored.columns["日期"].semantic_type == "temporal"


class TestAnalysisIntent:
    def test_roundtrip(self):
        ai = AnalysisIntent(type="trend", confidence=0.92, explicit_chart="line",
                            entities={"metrics": ["销售额"]})
        d = ai.to_dict()
        assert json.dumps(d)
        restored = AnalysisIntent.from_dict(d)
        assert restored.type == "trend"
        assert restored.explicit_chart == "line"


class TestFilterSpec:
    def test_roundtrip(self):
        fc = FilterCondition(column="姓名", operator="in", value=["张三", "李四"])
        fs = FilterSpec(conditions=[fc], persist=True)
        assert fs.is_empty() is False
        d = fs.to_dict()
        assert json.dumps(d)
        restored = FilterSpec.from_dict(d)
        assert restored.persist is True
        assert restored.conditions[0].column == "姓名"

    def test_empty(self):
        fs = FilterSpec()
        assert fs.is_empty() is True


class TestChartDecision:
    def test_roundtrip(self):
        cd = ChartDecision(chart_type="line", x_column="日期", y_columns=["销售额"],
                           title="趋势图", decision_source="profile_rule")
        d = cd.to_dict()
        assert json.dumps(d)
        restored = ChartDecision.from_dict(d)
        assert restored.chart_type == "line"
        assert restored.decision_source == "profile_rule"

    def test_none_sentinel(self):
        cd = ChartDecision.none()
        assert cd.is_none()
        d = cd.to_dict()
        restored = ChartDecision.from_dict(d)
        assert restored.is_none()


class TestChartFacts:
    def test_roundtrip(self):
        cf = ChartFacts(chart_type="line", x_label="日期", y_labels=["销售额"],
                        row_count=50, filter_description="(全部数据)",
                        trend_direction="upward",
                        entity_ids_used=["e_001", "e_002"],
                        peak_entity_id="e_002", peak_value=46961,
                        stats={"销售额": {"mean": 27000, "median": 25000}},
                        decision_source="profile_rule")
        d = cf.to_dict()
        assert json.dumps(d)
        restored = ChartFacts.from_dict(d)
        assert restored.trend_direction == "upward"
        assert restored.peak_entity_id == "e_002"
        assert restored.peak_value == 46961
        assert restored.entity_ids_used == ["e_001", "e_002"]


class TestDecisionLedger:
    def test_roundtrip(self):
        ds = DecisionStep(stage="chart_type", rule_applied="时序+数值→趋势", output="line")
        dl = DecisionLedger(profile_hash="abc", steps=[ds])
        d = dl.to_dict()
        assert json.dumps(d)
        restored = DecisionLedger.from_dict(d)
        assert restored.steps[0].rule_applied == "时序+数值→趋势"


class TestFilterContext:
    def test_apply_sticky_replaces(self):
        ctx = FilterContext()
        fs1 = FilterSpec(conditions=[FilterCondition("x", "eq", 1)], persist=True)
        fs2 = FilterSpec(conditions=[FilterCondition("y", "eq", 2)], persist=True)

        ctx.apply_new(fs1)
        assert ctx.active_filter() == fs1
        ctx.apply_new(fs2)
        assert ctx.active_filter() == fs2  # replaced, not stacked

    def test_one_shot_does_not_affect_sticky(self):
        ctx = FilterContext()
        fs_sticky = FilterSpec(conditions=[FilterCondition("x", "eq", 1)], persist=True)
        fs_shot = FilterSpec(conditions=[FilterCondition("y", "eq", 2)], persist=False)

        ctx.apply_new(fs_sticky)
        ctx.apply_new(fs_shot)
        assert ctx.active_filter() == fs_shot  # one_shot wins
        assert ctx.sticky_filter == fs_sticky  # sticky preserved

    def test_clear(self):
        ctx = FilterContext()
        ctx.apply_new(FilterSpec(conditions=[FilterCondition("x", "eq", 1)], persist=True))
        ctx.clear()
        assert ctx.active_filter() is None
        assert ctx.sticky_filter is None


class TestExplicitFailure:
    def test_roundtrip(self):
        ef = ExplicitFailure(code="empty_data", message="筛选后无数据",
                             recoverable=True, stage="execution")
        d = ef.to_dict()
        assert json.dumps(d)
        restored = ExplicitFailure.from_dict(d)
        assert restored.code == "empty_data"
        assert restored.recoverable is True
