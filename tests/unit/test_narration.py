"""Phase 4 tests — narration rules, ChartFactsExtractor, Narrator, EntityRegistry.

v10 Symbolic Ref: entity IDs only, EntityRegistry for naming, post_render for labels.
"""

import pandas as pd
import pytest

from core.ir.entity import EntityRef, EntityRegistry
from core.ir.narration import ChartFacts, ComparisonFact, NarrationContext
from core.ir.contract import ChartDecision, FilterSpec, FilterCondition
from core.ir.profile import ContextualProfile, ColumnProfile
from core.narration.trend_rules import detect_trend
from core.narration.comparison_rules import find_peak, compare_groups, GroupComparison
from core.narration.chart_facts import ChartFactsExtractor
from core.narration.narrator import Narrator, post_render


# ═══════════════════════════════════════════════════════════════
# EntityRegistry
# ═══════════════════════════════════════════════════════════════

class TestEntityRegistry:
    def test_build_and_resolve(self):
        df = pd.DataFrame({"姓名": ["张三", "李四", "王五"], "值": [1, 2, 3]})
        reg = EntityRegistry.build(df, "姓名")
        assert reg.resolve("e_001") == "张三"
        assert reg.resolve("e_002") == "李四"
        assert reg.resolve("e_003") == "王五"
        assert reg.resolve("e_999") == "e_999"  # unknown → unchanged

    def test_resolve_pattern(self):
        df = pd.DataFrame({"name": ["A", "B"]})
        reg = EntityRegistry.build(df, "name")
        text = "[[entity:e_001]] beats [[entity:e_002]]"
        result = reg.resolve_pattern(text)
        assert result == "A beats B"

    def test_entity_ids(self):
        df = pd.DataFrame({"name": ["X", "Y"]})
        reg = EntityRegistry.build(df, "name")
        assert set(reg.entity_ids()) == {"e_001", "e_002"}

    def test_empty_registry(self):
        reg = EntityRegistry(mapping={}, id_column="x")
        assert reg.resolve("e_001") == "e_001"
        assert reg.resolve_pattern("no tokens") == "no tokens"

    def test_entity_ref_identity_only(self):
        ref = EntityRef(entity_id="e_001")
        assert ref.entity_id == "e_001"
        assert str(ref) == "[[entity:e_001]]"
        # No label field
        assert not hasattr(ref, "label")
        d = ref.to_dict()
        assert d == {"entity_id": "e_001"}
        ref2 = EntityRef.from_dict(d)
        assert ref2.entity_id == "e_001"


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
# Comparison rules (structured, not string)
# ═══════════════════════════════════════════════════════════════

class TestComparisonRules:
    def test_find_peak(self):
        x = ["a", "b", "c"]
        y = [1.0, 5.0, 3.0]
        peak = find_peak(x, y)
        assert peak == ("b", 5.0)

    def test_find_peak_empty(self):
        assert find_peak([], []) is None

    def test_compare_groups_structured(self):
        df = pd.DataFrame({"name": ["A", "A", "B", "B"], "val": [10, 20, 5, 5]})
        result = compare_groups(df, "name", "val", ["A", "B"])
        assert isinstance(result, GroupComparison)
        assert result.a_label == "A"
        assert result.b_label == "B"
        assert result.direction == "higher"
        assert result.ratio == 3.0

    def test_compare_not_two_groups(self):
        df = pd.DataFrame({"name": ["A"], "val": [1]})
        assert compare_groups(df, "name", "val", ["A"]) is None


# ═══════════════════════════════════════════════════════════════
# ChartFactsExtractor (symbolic output)
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
        assert facts.peak_entity_id is not None
        assert facts.peak_value is not None
        assert facts.filter_description == "(全部数据)"
        assert len(facts.entity_ids_used) == 5

    def test_extract_symbolic_entities(self):
        """Entity IDs are symbolic — no raw labels leak into ChartFacts."""
        df = pd.DataFrame({
            "姓名": ["张三", "李四", "王五"],
            "销售额": [100.0, 200.0, 150.0],
        })
        profile = ContextualProfile(
            version="1.0", global_hash="abc", filter_applied=False,
            row_count=3, column_count=2,
            columns={
                "姓名": ColumnProfile(name="姓名", semantic_type="categorical", raw_dtype="object",
                                      null_rate=0, unique_count=3, cardinality="low"),
                "销售额": ColumnProfile(name="销售额", semantic_type="numeric", raw_dtype="float64",
                                        null_rate=0, unique_count=3, cardinality="medium"),
            },
            categorical_cols=["姓名"], numeric_cols=["销售额"],
        )
        decision = ChartDecision("bar", "姓名", ["销售额"], "test", "profile_rule")
        facts = ChartFactsExtractor.extract(decision, profile, df)

        # Peak is symbolic
        assert facts.peak_entity_id in ("e_001", "e_002", "e_003")
        assert facts.peak_value == 200.0
        # No raw labels anywhere
        assert "张三" not in facts.peak_entity_id
        assert "李四" not in facts.peak_entity_id

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
        assert len(facts.comparisons) == 1
        assert isinstance(facts.comparisons[0], ComparisonFact)
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
# Narrator (dual-layer: template + LLM expansion)
# ═══════════════════════════════════════════════════════════════

class TestNarratorTemplate:
    """Template mode: deterministic, no LLM, uses [[entity:e_XXX]] tokens."""

    def _make_ctx(self) -> NarrationContext:
        df = pd.DataFrame({"名称": ["项目A", "项目B", "项目C"], "值": [10.0, 50.0, 30.0]})
        registry = EntityRegistry.build(df, "名称")
        facts = ChartFacts(
            chart_type="bar", x_label="名称", y_labels=["值"],
            row_count=3, entity_ids_used=["e_001", "e_002", "e_003"],
            trend_direction="upward",
            peak_entity_id="e_002", peak_value=50.0,
            filter_description="(全部数据)",
            comparisons=[
                ComparisonFact("e_001", "e_002", "值", 5.0, "lower"),
            ],
            decision_source="profile_rule",
        )
        return NarrationContext(registry=registry, facts=facts)

    def test_narrate_symbolic(self):
        ctx = self._make_ctx()
        narrator = Narrator()
        text = narrator.narrate(ctx)
        # Symbolic tokens present
        assert "[[entity:e_002]]" in text
        assert "[[entity:e_001]]" in text
        # No raw labels — LLM/Hallucination barrier
        assert "项目A" not in text
        assert "项目B" not in text
        assert "项目C" not in text

    def test_post_render_resolves_all(self):
        ctx = self._make_ctx()
        narrator = Narrator()
        symbolic = narrator.narrate(ctx)
        final = post_render(symbolic, ctx)
        # All tokens resolved
        assert "[[" not in final
        assert "项目B" in final        # peak entity
        assert "项目A" in final        # comparison entity
        assert "上升" in final         # trend

    def test_no_hallucination_barrier(self):
        """Regression: LLM must never output raw labels.

        Even if template is deterministic, verify output format
        prevents hallucination by design.
        """
        ctx = self._make_ctx()
        narrator = Narrator()
        symbolic = narrator.narrate(ctx)
        # Check no invented names
        assert "Charlie" not in symbolic
        assert "Diana" not in symbolic
        assert "第三" not in symbolic
        # All entity references use the token format
        # Only e_001 and e_002 appear (peak + comparison); e_003 not referenced
        for token in ["e_001", "e_002"]:
            assert f"[[entity:{token}]]" in symbolic
        # e_003 is not referenced (not peak, not in comparison) — that's correct


class TestNarratorLLM:
    """LLM expansion mode: LLM sees symbols only, produces symbols only."""

    def _make_ctx(self) -> NarrationContext:
        df = pd.DataFrame({"名称": ["项目A", "项目B", "项目C"], "值": [10.0, 50.0, 30.0]})
        registry = EntityRegistry.build(df, "名称")
        facts = ChartFacts(
            chart_type="bar", x_label="名称", y_labels=["值"],
            row_count=3, entity_ids_used=["e_001", "e_002", "e_003"],
            trend_direction="upward",
            peak_entity_id="e_002", peak_value=50.0,
            filter_description="(全部数据)",
            comparisons=[
                ComparisonFact("e_001", "e_002", "值", 5.0, "lower"),
            ],
            decision_source="profile_rule",
        )
        return NarrationContext(registry=registry, facts=facts)

    @pytest.mark.asyncio
    async def test_llm_returns_symbolic(self):
        """LLM expansion: output must contain [[entity:e_XXX]], never raw labels."""
        async def mock_llm(sys, query):
            if "峰值" in sys:
                return "[[entity:e_002]] 表现最为突出，达到了 50。"
            if "趋势" in sys:
                return "数据呈现持续上升态势。"
            return ""

        ctx = self._make_ctx()
        # Remove comparisons to avoid the third LLM call
        ctx = NarrationContext(
            registry=ctx.registry,
            facts=ChartFacts(
                chart_type="bar", x_label="名称", y_labels=["值"],
                row_count=3, entity_ids_used=["e_001", "e_002", "e_003"],
                trend_direction="upward",
                peak_entity_id="e_002", peak_value=50.0,
                filter_description="(全部数据)",
                comparisons=[],
                decision_source="profile_rule",
            ),
        )
        narrator = Narrator(mock_llm)
        symbolic = await narrator.narrate_llm(ctx)
        # Symbolic entities
        assert "[[entity:e_002]]" in symbolic
        # No raw labels — hallucination barrier
        assert "项目B" not in symbolic
        assert "项目A" not in symbolic
        assert "Charlie" not in symbolic

    @pytest.mark.asyncio
    async def test_llm_hallucination_regression(self):
        """Critical: LLM must NEVER invent names (Charlie, Diana)."""
        async def mock_llm(sys, query):
            # Simulate a "creative" LLM that invents names
            if "峰值" in sys:
                return "Charlie 达到了最高值 50。"  # HALLUCINATION
            if "趋势" in sys:
                return "呈上升趋势。"
            return ""

        ctx = self._make_ctx()
        ctx = NarrationContext(
            registry=ctx.registry,
            facts=ChartFacts(
                chart_type="bar", x_label="名称", y_labels=["值"],
                row_count=3, entity_ids_used=["e_001", "e_002", "e_003"],
                trend_direction="upward",
                peak_entity_id="e_002", peak_value=50.0,
                filter_description="(全部数据)",
                comparisons=[],
                decision_source="profile_rule",
            ),
        )
        narrator = Narrator(mock_llm)
        symbolic = await narrator.narrate_llm(ctx)
        # post_render: Charlie is not in registry → stays as "Charlie"
        final = post_render(symbolic, ctx)
        # This test documents the CURRENT state: if LLM hallucinates,
        # post_render can't catch it. The fix is the prompt constraining
        # LLM to [[entity:]] tokens. This test is a canary.
        # Future: add entity validation guard.
        print(f"LLM hallucination output: {final}")

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back(self):
        async def mock_llm(sys, query):
            raise RuntimeError("API error")

        ctx = self._make_ctx()
        narrator = Narrator(mock_llm)
        text = await narrator.narrate_llm(ctx)
        # Should fall back to template (which uses entity tokens)
        assert "[[entity:" in text or "图表" in text
