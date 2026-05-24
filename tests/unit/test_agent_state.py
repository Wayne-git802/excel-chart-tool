"""Tests for unified_analysis field on AgentState."""

from models.agent_state import AgentState


def test_unified_analysis_add_finding():
    state = AgentState()
    state.add_finding("insight", "销售额上升12%", "react", 0.9, "line")
    assert len(state.unified_analysis) == 1
    assert state.unified_analysis[0]["type"] == "insight"
    assert state.unified_analysis[0]["source"] == "react"
    assert state.unified_analysis[0]["chart_type"] == "line"
    assert state.unified_analysis[0]["confidence"] == 0.9


def test_unified_analysis_both_sources():
    state = AgentState()
    state.add_finding("chart", "趋势图", "react", 0.85, "line")
    state.add_finding("insight", "存在非线性", "explore", 0.7, "scatter")
    assert len(state.unified_analysis) == 2
    assert state.unified_analysis[0]["source"] == "react"
    assert state.unified_analysis[1]["source"] == "explore"


def test_unified_analysis_confidence_clamped():
    state = AgentState()
    state.add_finding("fact", "test", "react", 1.5)
    assert state.unified_analysis[0]["confidence"] == 1.0
    state.add_finding("fact", "test2", "react", -0.5)
    assert state.unified_analysis[1]["confidence"] == 0.0
