"""Tests for validate_plan_graph."""

import pytest
from services.plan_validator import validate_plan_graph


def _dict_steps(*steps: dict) -> list[dict]:
    """Helper: return list of dict-based plan steps."""
    return list(steps)


# ── Empty / edge cases ──────────────────────────────────────────

def test_validate_empty_plan():
    """validate_plan_graph: 空计划 → error."""
    errors = validate_plan_graph([])
    assert len(errors) >= 1
    assert any("empty" in e.lower() for e in errors)


def test_validate_single_step_no_deps():
    """validate_plan_graph: 单步无依赖 → 返回 []."""
    steps = _dict_steps({"id": "s1"})
    errors = validate_plan_graph(steps)
    assert errors == []


# ── Duplicate id ────────────────────────────────────────────────

def test_validate_duplicate_id():
    """validate_plan_graph: 重复 id → "Duplicate"."""
    steps = _dict_steps(
        {"id": "s1"},
        {"id": "s1"},  # duplicate
    )
    errors = validate_plan_graph(steps)
    assert any("Duplicate" in e or "duplicate" in e.lower() for e in errors)


# ── Unknown dependency ──────────────────────────────────────────

def test_validate_unknown_dependency():
    """validate_plan_graph: 依赖缺失的 id → "depends on unknown"."""
    steps = _dict_steps(
        {"id": "s1"},
        {"id": "s2", "depends_on": ["s9"]},  # s9 doesn't exist
    )
    errors = validate_plan_graph(steps)
    assert any("unknown" in e.lower() for e in errors)


# ── Self-dependency ─────────────────────────────────────────────

def test_validate_self_dependency():
    """validate_plan_graph: 自依赖 → "depends on itself"."""
    steps = _dict_steps(
        {"id": "s1", "depends_on": ["s1"]},
    )
    errors = validate_plan_graph(steps)
    assert any("itself" in e.lower() for e in errors)


# ── Cycle detection ─────────────────────────────────────────────

def test_validate_cycle():
    """validate_plan_graph: 循环 s1→s2→s1 → "Cyclic"."""
    steps = _dict_steps(
        {"id": "s1", "depends_on": ["s2"]},
        {"id": "s2", "depends_on": ["s1"]},
    )
    errors = validate_plan_graph(steps)
    assert any("Cyclic" in e or "cyclic" in e.lower() for e in errors)


# ── Too many steps ──────────────────────────────────────────────

def test_validate_too_many_steps():
    """validate_plan_graph: >10 steps → "Too many"."""
    steps = _dict_steps(*[{"id": f"s{i}"} for i in range(11)])
    errors = validate_plan_graph(steps)
    assert any("Too many" in e for e in errors)


# ── Valid DAG ───────────────────────────────────────────────────

def test_validate_valid_dag():
    """validate_plan_graph: 正常 DAG → 返回 []."""
    steps = _dict_steps(
        {"id": "s1"},
        {"id": "s2", "depends_on": ["s1"]},
        {"id": "s3", "depends_on": ["s1", "s2"]},
        {"id": "s4", "depends_on": ["s3"]},
    )
    errors = validate_plan_graph(steps)
    assert errors == []


def test_validate_diamond_dag():
    """validate_plan_graph: 菱形依赖 DAG → 返回 []."""
    steps = _dict_steps(
        {"id": "s1"},
        {"id": "s2a", "depends_on": ["s1"]},
        {"id": "s2b", "depends_on": ["s1"]},
        {"id": "s3", "depends_on": ["s2a", "s2b"]},
    )
    errors = validate_plan_graph(steps)
    assert errors == []
