"""Unit tests for PlanStep (v8) and plan-related AgentState methods."""

import dataclasses
import pytest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from models.agent_state import PlanStep, AgentState


# ═══════════════════════════════════════════════════════════════
# PlanStep construction and serialization
# ═══════════════════════════════════════════════════════════════

class TestPlanStepConstruction:
    """Tests for PlanStep dataclass construction and defaults."""

    def test_planstep_full(self):
        ps = PlanStep(
            id="s1",
            goal="找出月度销售趋势",
            tool="chart_builder",
            depends_on=["s0"],
            chart_hint="line",
            narrative_hint="销售额随时间变化",
            status="running",
        )
        assert ps.id == "s1"
        assert ps.goal == "找出月度销售趋势"
        assert ps.tool == "chart_builder"
        assert ps.depends_on == ["s0"]
        assert ps.chart_hint == "line"
        assert ps.narrative_hint == "销售额随时间变化"
        assert ps.status == "running"

    def test_planstep_minimal(self):
        ps = PlanStep(id="s1", goal="概览", tool="data_query")
        assert ps.id == "s1"
        assert ps.goal == "概览"
        assert ps.tool == "data_query"
        assert ps.depends_on == []
        assert ps.chart_hint is None
        assert ps.narrative_hint is None
        assert ps.status == "pending"

    def test_planstep_dataclass_asdict(self):
        ps = PlanStep(
            id="s3",
            goal="检测异常值",
            tool="chart_builder",
            chart_hint="boxplot",
            depends_on=["s1", "s2"],
            status="completed",
        )
        d = dataclasses.asdict(ps)
        assert d["id"] == "s3"
        assert d["goal"] == "检测异常值"
        assert d["tool"] == "chart_builder"
        assert d["chart_hint"] == "boxplot"
        assert d["depends_on"] == ["s1", "s2"]
        assert d["status"] == "completed"

    def test_planstep_dataclass_roundtrip(self):
        original = PlanStep(
            id="s5",
            goal="分析趋势",
            tool="chart_builder",
            chart_hint="line",
            depends_on=["s3"],
            status="running",
        )
        d = dataclasses.asdict(original)
        restored = PlanStep(**d)
        assert restored.id == original.id
        assert restored.goal == original.goal
        assert restored.tool == original.tool
        assert restored.chart_hint == original.chart_hint
        assert restored.depends_on == original.depends_on
        assert restored.status == original.status
        assert restored.narrative_hint == original.narrative_hint

    def test_planstep_status_values(self):
        for status in ("pending", "running", "completed", "failed", "skipped"):
            ps = PlanStep(id="s1", goal="test", tool="data_query", status=status)
            assert ps.status == status


# ═══════════════════════════════════════════════════════════════
# AgentState plan_progress roundtrip
# ═══════════════════════════════════════════════════════════════

class TestAgentStatePlanRoundtrip:
    """Tests for AgentState plan_progress serialization."""

    def test_agentstate_plan_progress_roundtrip(self):
        state = AgentState(session_id="test-session")
        steps = [
            PlanStep(id="s1", goal="概览", tool="data_query", status="completed"),
            PlanStep(id="s2", goal="趋势", tool="chart_builder", chart_hint="line", status="running"),
            PlanStep(id="s3", goal="结论", tool="annotation_engine", status="pending"),
        ]
        state.set_plan_steps(steps)

        restored = AgentState.from_dict(state.to_dict())
        assert len(restored.plan_progress) == 3
        assert restored.plan_progress[0].id == "s1"
        assert restored.plan_progress[0].goal == "概览"
        assert restored.plan_progress[0].status == "completed"
        assert restored.plan_progress[1].chart_hint == "line"
        assert restored.plan_progress[2].tool == "annotation_engine"

    def test_agentstate_empty_plan_progress(self):
        state = AgentState(session_id="empty-plan")
        restored = AgentState.from_dict(state.to_dict())
        assert restored.plan_progress == []


# ═══════════════════════════════════════════════════════════════
# AgentState plan management methods
# ═══════════════════════════════════════════════════════════════

class TestPlanStepManagement:
    """Tests for AgentState plan progress management."""

    def test_set_plan_steps(self):
        state = AgentState()
        steps = [
            PlanStep(id="s1", goal="概览", tool="data_query", status="completed"),
            PlanStep(id="s2", goal="趋势", tool="chart_builder", status="pending"),
        ]
        state.set_plan_steps(steps)
        assert len(state.plan_progress) == 2
        assert state.plan_progress[0].id == "s1"
        assert state.plan_progress[1].status == "pending"

    def test_get_current_step_returns_first_not_completed(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id="s1", goal="done", tool="data_query", status="completed"),
            PlanStep(id="s2", goal="pending", tool="chart_builder", status="pending"),
            PlanStep(id="s3", goal="also", tool="chart_builder", status="pending"),
        ])
        current = state.get_current_step()
        assert current is not None
        assert current.id == "s2"

    def test_get_current_step_returns_running(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id="s1", goal="done", tool="data_query", status="completed"),
            PlanStep(id="s2", goal="running", tool="chart_builder", status="running"),
            PlanStep(id="s3", goal="pending", tool="chart_builder", status="pending"),
        ])
        current = state.get_current_step()
        assert current is not None
        assert current.id == "s2"

    def test_get_current_step_none_when_all_done(self):
        state = AgentState()
        state.set_plan_steps([
            PlanStep(id="s1", goal="a", tool="data_query", status="completed"),
            PlanStep(id="s2", goal="b", tool="chart_builder", status="completed"),
        ])
        current = state.get_current_step()
        assert current is None


# ═══════════════════════════════════════════════════════════════
# validate_plan_graph (v8 replacement for old validate_plan)
# ═══════════════════════════════════════════════════════════════

class TestValidatePlanGraph:
    """Tests for plan graph validation."""

    def test_valid_plan_no_errors(self):
        from services.plan_validator import validate_plan_graph
        plan = [
            PlanStep(id="s1", goal="概览", tool="data_query", depends_on=[]),
            PlanStep(id="s2", goal="趋势", tool="chart_builder", chart_hint="line", depends_on=["s1"]),
        ]
        errors = validate_plan_graph(plan)
        assert errors == []

    def test_empty_plan(self):
        from services.plan_validator import validate_plan_graph
        errors = validate_plan_graph([])
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_duplicate_ids_detected(self):
        from services.plan_validator import validate_plan_graph
        plan = [
            PlanStep(id="s1", goal="a", tool="data_query"),
            PlanStep(id="s1", goal="b", tool="chart_builder"),
        ]
        errors = validate_plan_graph(plan)
        assert len(errors) >= 1
