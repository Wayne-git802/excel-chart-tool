"""Unit tests for Phase 3: PlanStep, plan_validator, plan-aware features."""

import pytest
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from models.agent_state import PlanStep, AgentState
from services.plan_validator import validate_plan


# ═══════════════════════════════════════════════════════════════
# PlanStep serialization tests
# ═══════════════════════════════════════════════════════════════

class TestPlanStepSerialization:
    """Tests for PlanStep to_dict / from_dict round-trip."""

    def test_planstep_to_dict_full(self):
        """PlanStep.to_dict() includes all fields correctly."""
        ps = PlanStep(
            id=1,
            goal="找出月度销售趋势",
            node_type="trend_analysis",
            params={"columns": ["月份", "销售额"], "chart_type": "line"},
            depends_on=[0],
            status="running",
            result={"chart_id": "abc123"},
            confidence=0.85,
        )
        d = ps.to_dict()
        assert d["id"] == 1
        assert d["goal"] == "找出月度销售趋势"
        assert d["node_type"] == "trend_analysis"
        assert d["params"] == {"columns": ["月份", "销售额"], "chart_type": "line"}
        assert d["depends_on"] == [0]
        assert d["status"] == "running"
        assert d["result"] == {"chart_id": "abc123"}
        assert d["confidence"] == 0.85

    def test_planstep_to_dict_defaults(self):
        """PlanStep.to_dict() with default values produces valid dict."""
        ps = PlanStep(id=0)
        d = ps.to_dict()
        assert d["id"] == 0
        assert d["goal"] == ""
        assert d["node_type"] == "intent_response"
        assert d["params"] == {}
        assert d["depends_on"] == []
        assert d["status"] == "pending"
        assert d["result"] is None
        assert d["confidence"] == 0.0

    def test_planstep_from_dict_roundtrip(self):
        """from_dict(to_dict(x)) should produce equal PlanStep."""
        original = PlanStep(
            id=3,
            goal="检测异常值",
            node_type="anomaly_detection",
            params={"columns": ["订单数"], "chart_type": "boxplot"},
            depends_on=[1, 2],
            status="done",
            result={"outliers": 5},
            confidence=0.72,
        )
        restored = PlanStep.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.goal == original.goal
        assert restored.node_type == original.node_type
        assert restored.params == original.params
        assert restored.depends_on == original.depends_on
        assert restored.status == original.status
        assert restored.result == original.result
        assert restored.confidence == original.confidence

    def test_planstep_from_dict_partial(self):
        """from_dict() handles partial/missing keys gracefully."""
        d = {"id": 5, "goal": "只给了id和goal"}
        ps = PlanStep.from_dict(d)
        assert ps.id == 5
        assert ps.goal == "只给了id和goal"
        assert ps.node_type == "intent_response"
        assert ps.params == {}
        assert ps.status == "pending"
        assert ps.result is None
        assert ps.confidence == 0.0

    def test_agentstate_plan_progress_roundtrip(self):
        """AgentState.to_dict/from_dict correctly serializes plan_progress."""
        state = AgentState(session_id="test-session")
        steps = [
            PlanStep(id=1, goal="概览", node_type="overview", status="done", result={"rows": 50}),
            PlanStep(id=2, goal="趋势", node_type="trend_analysis", status="running"),
            PlanStep(id=3, goal="结论", node_type="conclusion", status="pending"),
        ]
        state.set_plan_steps(steps)

        # Serialize and deserialize
        restored = AgentState.from_dict(state.to_dict())
        assert len(restored.plan_progress) == 3
        assert restored.plan_progress[0].id == 1
        assert restored.plan_progress[0].goal == "概览"
        assert restored.plan_progress[0].status == "done"
        assert restored.plan_progress[0].result == {"rows": 50}
        assert restored.plan_progress[1].node_type == "trend_analysis"
        assert restored.plan_progress[2].confidence == 0.0

    def test_agentstate_empty_plan_progress(self):
        """AgentState with empty plan_progress roundtrips correctly."""
        state = AgentState(session_id="empty-plan")
        restored = AgentState.from_dict(state.to_dict())
        assert restored.plan_progress == []


# ═══════════════════════════════════════════════════════════════
# PlanStep management methods tests
# ═══════════════════════════════════════════════════════════════

class TestPlanStepManagement:
    """Tests for AgentState plan_progress management methods."""

    def test_get_current_step_returns_first_pending(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id=1, status="done"),
            PlanStep(id=2, status="pending"),
            PlanStep(id=3, status="pending"),
        ])
        current = state.get_current_step()
        assert current is not None
        assert current.id == 2

    def test_get_current_step_returns_running(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id=1, status="done"),
            PlanStep(id=2, status="running"),
            PlanStep(id=3, status="pending"),
        ])
        current = state.get_current_step()
        assert current is not None
        assert current.id == 2

    def test_get_current_step_none_when_all_done(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id=1, status="done"),
            PlanStep(id=2, status="done"),
        ])
        current = state.get_current_step()
        assert current is None

    def test_mark_step_done(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id=1, status="pending"),
        ])
        state.mark_step_done(1, {"chart_id": "xyz"})
        assert state.plan_progress[0].status == "done"
        assert state.plan_progress[0].result == {"chart_id": "xyz"}

    def test_mark_step_failed(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id=1, status="pending"),
        ])
        state.mark_step_failed(1, "数据列缺失")
        assert state.plan_progress[0].status == "failed"
        assert state.plan_progress[0].result == {"error": "数据列缺失"}

    def test_replan_steps_returns_pending_only(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id=1, status="done"),
            PlanStep(id=2, status="pending"),
            PlanStep(id=3, status="failed"),
            PlanStep(id=4, status="running"),
        ])
        remaining = state.replan_steps()
        assert len(remaining) == 2
        ids = {s.id for s in remaining}
        assert ids == {2, 4}


# ═══════════════════════════════════════════════════════════════
# validate_plan tests
# ═══════════════════════════════════════════════════════════════

class TestValidatePlan:
    """Tests for plan_validator.validate_plan()."""

    def test_valid_plan_no_errors(self):
        columns = [
            {"name": "月份"}, {"name": "销售额"}, {"name": "利润"},
        ]
        valid_chart_types = {"bar", "line", "pie"}
        node_tools = {"overview": ["data_query"], "trend_analysis": ["chart_builder"]}

        plan = [
            PlanStep(id=1, node_type="overview", params={"columns": ["销售额"]}),
            PlanStep(id=2, node_type="trend_analysis", params={"columns": ["销售额"], "chart_type": "line"}),
        ]
        errors = validate_plan(plan, columns, valid_chart_types, node_tools)
        assert errors == []

    def test_invalid_node_type_detected(self):
        columns = [{"name": "销售额"}]
        valid_chart_types = {"bar"}
        node_tools = {"overview": ["data_query"]}

        plan = [
            PlanStep(id=1, node_type="unknown_type", params={}),
        ]
        errors = validate_plan(plan, columns, valid_chart_types, node_tools)
        assert len(errors) >= 1
        assert any("unknown node_type" in e for e in errors)

    def test_invalid_column_detected(self):
        columns = [{"name": "月份"}]
        valid_chart_types = {"line"}
        node_tools = {"trend_analysis": ["chart_builder"]}

        plan = [
            PlanStep(id=1, node_type="trend_analysis", params={"columns": ["不存在的列"]}),
        ]
        errors = validate_plan(plan, columns, valid_chart_types, node_tools)
        assert len(errors) >= 1
        assert any("不存在的列" in e for e in errors)

    def test_invalid_chart_type_detected(self):
        columns = [{"name": "销售额"}]
        valid_chart_types = {"bar", "line"}
        node_tools = {"trend_analysis": ["chart_builder"]}

        plan = [
            PlanStep(id=1, node_type="trend_analysis", params={"chart_type": "heatmap"}),
        ]
        errors = validate_plan(plan, columns, valid_chart_types, node_tools)
        assert len(errors) >= 1
        assert any("heatmap" in e for e in errors)

    def test_dict_plan_also_validated(self):
        """validate_plan() also accepts list[dict] format."""
        columns = [{"name": "销售额"}]
        valid_chart_types = {"bar"}
        node_tools = {"overview": ["data_query"]}

        plan = [
            {"id": 1, "node_type": "overview", "params": {"columns": ["销售额"]}},
            {"id": 2, "node_type": "trend_analysis", "params": {}, "chart_type": "pie"},
        ]
        errors = validate_plan(plan, columns, valid_chart_types, node_tools)
        # Step 2: invalid node_type and invalid chart_type
        assert len(errors) >= 1
