"""Phase 4 tests — ChartFactsExtractor, trend rules, comparison rules, Narrator."""

import pandas as pd
import pytest

from core.ir.narration import ChartFacts
from core.ir.contract import ChartDecision, FilterSpec, FilterCondition
from core.ir.profile import ContextualProfile, ColumnProfile
from core.narration.trend_rules import detect_trend
from core.narration.comparison_rules import find_peak, compare_groups
from core.narration.chart_facts import ChartFactsExtractor
from core.narration.narrator import Narrator


# ═══════════════════════════════════════════════════════════════
# Trend detection
# ═══════════════════════════════════════════════════════════════

class TestTrendDetection:
    def test_upward(self):
        assert detect_trend([1, 2, 3, 4, 5]) == "upward"

    def test_downward(self):
        assert detect_trend([5, 4, 3, 2, 1]) == "downward"

    def test_unclear_noisy(self):
        assert detect_trend([1, 100, 2, 99, 3]) == "unclear"

    def test_insufficient(self):
        assert detect_trend([1, 2]) is None
        assert detect_trend([]) is None


# ═══════════════════════════════════════════════════════════════
# Comparison rules
# ═══════════════════════════════════════════════════════════════

class TestComparisonRules:
    def test_find_peak(self):
        x = ["a", "b", "c"]
        y = [1.0, 5.0, 3.0]
        peak = find_peak(x, y)
        assert peak == ("b", 5.0)

    def test_find_peak_empty(self):
        assert find_peak([], []) is None

    def test_compare_groups(self):
        df = pd.DataFrame({"name": ["A", "A", "B", "B"], "val": [10, 20, 5, 5]})
        result = compare_groups(df, "name", "val", ["A", "B"])
        assert "A" in result
        assert "B" in result
        assert "高" in result

    def test_compare_not_two_groups(self):
        df = pd.DataFrame({"name": ["A"], "val": [1]})
        assert compare_groups(df, "name", "val", ["A"]) is None


# ═══════════════════════════════════════════════════════════════
# ChartFactsExtractor
# ═══════════════════════════════════════════════════════════════

class TestChartFactsExtractor:
    def _profile(self, row_count=5, filter_applied=False):
        return ContextualProfile(
            version="1.0", global_hash="abc",
            filter_applied=filter_applied,
            row_count=row_count, column_count=2,
            columns={
                "日期": ColumnProfile(name="日期", semantic_type="temporal", raw_dtype="datetime64",
                                      null_rate=0, unique_count=5, cardinality="high"),
                "销售额": ColumnProfile(name="销售额", semantic_type="numeric", raw_dtype="float64",
                                        null_rate=0, unique_count=5, cardinality="medium"),
            },
            temporal_cols=["日期"], numeric_cols=["销售额"],
        )

    def test_extract_basic(self):
        df = pd.DataFrame({
            "日期": pd.date_range("2025-01-01", periods=5),
            "销售额": [100.0, 120.0, 110.0, 140.0, 160.0],
        })
        decision = ChartDecision("line", "日期", ["销售额"], "趋势", "profile_rule")
        facts = ChartFactsExtractor.extract(decision, self._profile(), df)
        assert facts.chart_type == "line"
        assert facts.x_label == "日期"
        assert facts.trend_direction == "upward"
        assert facts.peak_point is not None
        assert facts.filter_description == "(全部数据)"

    def test_extract_with_filter_and_comparison(self):
        df = pd.DataFrame({
            "类别": ["A", "A", "B", "B"],
            "销售额": [10.0, 20.0, 5.0, 5.0],
        })
        fs = FilterSpec(conditions=[FilterCondition("类别", "in", ["A", "B"])], persist=True)
        profile = ContextualProfile(
            version="1.0", global_hash="abc",
            filter_applied=True, filter_spec=fs,
            row_count=4, column_count=2,
            columns={
                "类别": ColumnProfile(name="类别", semantic_type="categorical", raw_dtype="object",
                                      null_rate=0, unique_count=2, cardinality="low"),
                "销售额": ColumnProfile(name="销售额", semantic_type="numeric", raw_dtype="float64",
                                        null_rate=0, unique_count=4, cardinality="low"),
            },
            categorical_cols=["类别"], numeric_cols=["销售额"],
        )
        decision = ChartDecision("bar", "类别", ["销售额"], "对比", "profile_rule")
        facts = ChartFactsExtractor.extract(decision, profile, df)
        assert facts.filter_description != "(全部数据)"
        assert facts.comparison is not None
        assert "销售额" in facts.stats

    def test_stats_computed(self):
        df = pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})
        profile = ContextualProfile(
            version="1.0", global_hash="abc", filter_applied=False,
            row_count=3, column_count=2,
            columns={"x": ColumnProfile(name="x", semantic_type="numeric", raw_dtype="int64",
                                        null_rate=0, unique_count=3, cardinality="low"),
                     "y": ColumnProfile(name="y", semantic_type="numeric", raw_dtype="int64",
                                        null_rate=0, unique_count=3, cardinality="low")},
            numeric_cols=["x", "y"],
        )
        decision = ChartDecision("scatter", "x", ["y"], "关系", "profile_rule")
        facts = ChartFactsExtractor.extract(decision, profile, df)
        assert "y" in facts.stats
        assert facts.stats["y"]["mean"] == 20.0
        assert facts.stats["y"]["min"] == 10.0
        assert facts.stats["y"]["max"] == 30.0


# ═══════════════════════════════════════════════════════════════
# Narrator
# ═══════════════════════════════════════════════════════════════

class TestNarrator:
    def test_fallback_narrate(self):
        facts = ChartFacts(
            chart_type="line", x_label="日期", y_labels=["销售额"],
            row_count=5, trend_direction="upward",
            peak_point=("2025-05", 160.0),
            filter_description="(全部数据)",
            decision_source="profile_rule",
        )
        narrator = Narrator(lambda s, q: "")
        text = narrator._fallback_narrate(facts)
        assert "line" in text or "图表" in text
        assert "上升" in text

    @pytest.mark.asyncio
    async def test_llm_narrate(self):
        async def mock_llm(sys, query):
            return "数据显示销售额在观察期内呈稳定上升趋势，最高点出现在2025年5月。"

        facts = ChartFacts(
            chart_type="line", x_label="日期", y_labels=["销售额"],
            row_count=5, trend_direction="upward",
            peak_point=("2025-05", 160.0),
            filter_description="(全部数据)",
            decision_source="profile_rule",
        )
        narrator = Narrator(mock_llm)
        text = await narrator.narrate(facts)
        assert "上升" in text
        assert len(text) > 10

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self):
        async def mock_llm(sys, query):
            raise RuntimeError("API error")

        facts = ChartFacts(
            chart_type="bar", x_label="类别", y_labels=["销售额"],
            row_count=4, filter_description="(全部数据)",
            decision_source="profile_rule",
        )
        narrator = Narrator(mock_llm)
        text = await narrator.narrate(facts)
        assert "bar" in text or "图表" in text
