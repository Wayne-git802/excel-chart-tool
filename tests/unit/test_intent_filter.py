"""Phase 2 tests — CapabilityGate, IntentExtractor, FilterSpecBuilder, Validator."""

import pytest

from core.ir.contract import AnalysisIntent, CapabilityResult, FilterSpec, FilterCondition
from core.ir.profile import DatasetProfile, ColumnProfile
from core.ir.failure import ExplicitFailure
from core.routing.capability_gate import layer_a_check, layer_b_check
from core.filtering.validator import validate_filter, _fuzzy_match_column


class TestCapabilityGateLayerA:
    def test_allowed(self):
        r = layer_a_check("帮我分析销售趋势")
        assert r.allowed is True

    def test_reject_forecast(self):
        r = layer_a_check("预测明年销售额")
        assert r.allowed is False
        assert "预测" in r.reason

    def test_reject_cluster(self):
        r = layer_a_check("聚类分析客户")
        assert r.allowed is False

    def test_reject_regression(self):
        r = layer_a_check("训练一个回归模型")
        assert r.allowed is False


class TestCapabilityGateLayerB:
    def test_trend_allowed(self):
        intent = AnalysisIntent(type="trend", confidence=0.9)
        r = layer_b_check(intent)
        assert r.allowed is True

    def test_unknown_downgraded(self):
        intent = AnalysisIntent(type="UNKNOWN", confidence=0.3)
        r = layer_b_check(intent)
        assert r.allowed is True  # not rejected, just low confidence

    def test_unsupported_rejected(self):
        intent = AnalysisIntent(type="forecasting", confidence=0.8)
        r = layer_b_check(intent)
        assert r.allowed is False


class TestIntentExtractor:
    @pytest.mark.asyncio
    async def test_extract_trend(self):
        from core.routing.intent_extractor import IntentExtractor

        async def mock_llm(sys, query):
            return '{"type":"trend","explicit_chart":null,"entities":{"metrics":["销售额"]}}'

        extractor = IntentExtractor(mock_llm)
        intent = await extractor.extract("销售额变化趋势")
        assert intent.type == "trend"
        assert intent.explicit_chart is None

    @pytest.mark.asyncio
    async def test_extract_explicit_chart(self):
        from core.routing.intent_extractor import IntentExtractor

        async def mock_llm(sys, query):
            return '{"type":"trend","explicit_chart":"line","entities":{"metrics":["销量"]}}'

        extractor = IntentExtractor(mock_llm)
        intent = await extractor.extract("用折线图展示销量")
        assert intent.explicit_chart == "line"

    @pytest.mark.asyncio
    async def test_extract_fallback(self):
        from core.routing.intent_extractor import IntentExtractor

        async def mock_llm(sys, query):
            raise RuntimeError("simulated failure")

        extractor = IntentExtractor(mock_llm)
        intent = await extractor.extract("???")
        assert intent.type == "UNKNOWN"
        assert intent.confidence == 0.3


class TestFilterSpecBuilder:
    @pytest.mark.asyncio
    async def test_build_filter(self):
        from core.filtering.builder import FilterSpecBuilder

        async def mock_llm(sys, query):
            return '{"conditions":[{"column":"姓名","operator":"in","value":["张三","李四"]}],"persist":true}'

        profile = DatasetProfile(version="1.0", hash="abc", row_count=10, column_count=2,
                                 columns={"姓名": ColumnProfile(name="姓名", semantic_type="categorical",
                                         raw_dtype="object", null_rate=0, unique_count=4, cardinality="low"),
                                          "销售额": ColumnProfile(name="销售额", semantic_type="numeric",
                                         raw_dtype="float64", null_rate=0, unique_count=10, cardinality="medium")})
        builder = FilterSpecBuilder(mock_llm)
        fs = await builder.build("只看张三和李四", profile)
        assert len(fs.conditions) == 1
        assert fs.conditions[0].column == "姓名"
        assert fs.conditions[0].value == ["张三", "李四"]
        assert fs.persist is True

    @pytest.mark.asyncio
    async def test_build_no_filter(self):
        from core.filtering.builder import FilterSpecBuilder

        async def mock_llm(sys, query):
            return '{"conditions":[],"persist":false}'

        profile = DatasetProfile(version="1.0", hash="abc", row_count=10, column_count=1,
                                 columns={"x": ColumnProfile(name="x", semantic_type="numeric",
                                         raw_dtype="int64", null_rate=0, unique_count=10, cardinality="medium")})
        builder = FilterSpecBuilder(mock_llm)
        fs = await builder.build("画柱状图", profile)
        assert fs.is_empty()


class TestFilterValidator:
    def _profile(self):
        return DatasetProfile(version="1.0", hash="abc", row_count=10, column_count=2,
                             columns={
                                 "姓名": ColumnProfile(name="姓名", semantic_type="categorical",
                                     raw_dtype="object", null_rate=0, unique_count=4, cardinality="low"),
                                 "销售额": ColumnProfile(name="销售额", semantic_type="numeric",
                                     raw_dtype="float64", null_rate=0, unique_count=10, cardinality="medium"),
                             })

    def test_empty_filter(self):
        fs = FilterSpec()
        failures = validate_filter(fs, self._profile())
        assert failures == []

    def test_exact_match(self):
        fs = FilterSpec(conditions=[FilterCondition("姓名", "in", ["张三"])])
        failures = validate_filter(fs, self._profile())
        assert failures == []

    def test_fuzzy_match(self):
        profile = self._profile()
        fs = FilterSpec(conditions=[FilterCondition("名字", "in", ["张三"])])
        failures = validate_filter(fs, profile)
        assert failures == []  # fuzzy match "名字" → "姓名"

    def test_no_match(self):
        fs = FilterSpec(conditions=[FilterCondition("xyz", "eq", 1)])
        failures = validate_filter(fs, self._profile())
        assert len(failures) == 1
        assert failures[0].code == "invalid_filter_column"

    def test_invalid_operator(self):
        profile = DatasetProfile(version="1.0", hash="abc", row_count=10, column_count=1,
                                columns={"x": ColumnProfile(name="x", semantic_type="numeric",
                                        raw_dtype="int64", null_rate=0, unique_count=10, cardinality="medium")})
        fs = FilterSpec(conditions=[FilterCondition("x", "invalid_op", 1)])
        failures = validate_filter(fs, profile)
        assert len(failures) == 1
        assert failures[0].code == "invalid_filter_operator"

    def test_fuzzy_match_column_utility(self):
        profile = self._profile()
        assert _fuzzy_match_column("姓名", profile) == "姓名"
        assert _fuzzy_match_column("名字", profile) == "姓名"
        assert _fuzzy_match_column("xyz", profile) is None
