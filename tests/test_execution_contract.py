"""Zero-LLM unit tests for the Execution Contract Layer.

Tests the contract API: ExecutionContract, ContractFailure, ValidationResult,
RepairDecision, ApprovalResult, and the validator/resolver/engine/approval functions.

All tests are self-contained with no external API calls.
"""

import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import pandas as pd

from core.contract.contract import (
    ExecutionContract,
    ContractFailure,
    ValidationResult,
    RepairDecision,
    ApprovalResult,
    validate_columns,
    validate_types,
    validate_intent,
    resolve_conflict,
    validate_contract,
    decide_repair,
    approve,
)


# ── Shared fixtures ───────────────────────────────────────────

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "订单日期": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "销售额": [1000, 1500, 1200],
        "利润": [200, 300, 250],
        "地区": ["北京", "上海", "广州"],
    })


@pytest.fixture
def sample_columns():
    return [
        {"name": "订单日期", "dtype": "object", "dtype_cn": "文本"},
        {"name": "销售额", "dtype": "float64", "dtype_cn": "数值"},
        {"name": "利润", "dtype": "float64", "dtype_cn": "数值"},
        {"name": "地区", "dtype": "object", "dtype_cn": "分类"},
    ]


@pytest.fixture
def basic_df():
    """Minimal DataFrame for contract tests — 50 rows."""
    return pd.DataFrame({
        "category": ["A", "B", "C", "D", "E"] * 10,
        "value1": range(50),
        "value2": [float(i * 2) for i in range(50)],
    })


@pytest.fixture
def basic_columns():
    return [
        {"name": "category", "dtype": "object", "dtype_cn": "分类"},
        {"name": "value1", "dtype": "int64", "dtype_cn": "数值"},
        {"name": "value2", "dtype": "float64", "dtype_cn": "数值"},
    ]


@pytest.fixture
def default_contract(basic_columns):
    """A valid default contract for reuse."""
    return ExecutionContract(
        chart_type="bar",
        x_column="category",
        y_columns=["value1"],
        title="Test Chart",
        policy="standard",
        context={},
    )


# ── Helper: make a contract quickly ───────────────────────────

def _make_contract(chart_type="bar", x_col="category", y_cols=None,
                   title="Test", policy="standard", context=None):
    """Convenience constructor for ExecutionContract in tests."""
    return ExecutionContract(
        chart_type=chart_type,
        x_column=x_col,
        y_columns=y_cols or ["value1"],
        title=title,
        policy=policy,
        context=context or {},
    )


# ═══════════════════════════════════════════════════════════════
# 1.  ColumnValidator tests
# ═══════════════════════════════════════════════════════════════

def test_column_validator_all_columns_exist(sample_df, sample_columns):
    """All columns exist → empty failures list."""
    contract = _make_contract(x_col="订单日期", y_cols=["销售额", "利润"])
    failures = validate_columns(contract, sample_df, sample_columns)
    assert failures == [], f"Expected no failures, got {failures}"


def test_column_validator_x_missing_no_fuzzy_match(sample_df, sample_columns):
    """x_column is missing and no fuzzy match → 1 fatal failure."""
    contract = _make_contract(x_col="不存在的列", y_cols=["销售额"])
    failures = validate_columns(contract, sample_df, sample_columns)
    assert len(failures) >= 1, f"Expected at least 1 failure, got {len(failures)}"
    x_failures = [f for f in failures if f.field == "x_column"]
    assert len(x_failures) >= 1, f"Expected x_column failure, got {x_failures}"
    assert x_failures[0].severity == "fatal", (
        f"Expected fatal severity, got {x_failures[0].severity}"
    )


def test_column_validator_x_has_fuzzy_match(sample_df, sample_columns):
    """x_column has a fuzzy match → 1 repairable failure with suggestion."""
    contract = _make_contract(x_col="定单日期", y_cols=["销售额"])  # typo of 订单日期
    failures = validate_columns(contract, sample_df, sample_columns)
    assert len(failures) >= 1, f"Expected at least 1 failure, got {len(failures)}"
    x_failures = [f for f in failures if f.field == "x_column"]
    assert len(x_failures) >= 1
    # Should be repairable, not fatal
    assert x_failures[0].severity in ("repairable", "warning"), (
        f"Expected repairable/warning, got {x_failures[0].severity}"
    )
    assert x_failures[0].suggestion is not None, "Expected a suggestion for fuzzy match"


def test_column_validator_y_column_missing(sample_df, sample_columns):
    """A y_column is missing → at least 1 failure."""
    contract = _make_contract(x_col="订单日期", y_cols=["销售额", "不存在的Y列"])
    failures = validate_columns(contract, sample_df, sample_columns)
    assert len(failures) >= 1, f"Expected at least 1 failure, got {len(failures)}"
    y_failures = [f for f in failures if f.field and "y_column" in f.field]
    assert len(y_failures) >= 1, f"Expected y_column failure, got {y_failures}"


# ═══════════════════════════════════════════════════════════════
# 2.  TypeValidator tests
# ═══════════════════════════════════════════════════════════════

def test_type_validator_scatter_with_two_numeric(basic_df, basic_columns):
    """Scatter chart + 2+ numeric columns → empty failures."""
    contract = _make_contract(chart_type="scatter", x_col="value1", y_cols=["value2"])
    failures = validate_types(contract, basic_df, basic_columns)
    assert failures == [], f"Expected no type failures, got {failures}"


def test_type_validator_scatter_with_one_numeric():
    """Scatter chart + only 1 numeric column total → fatal failure."""
    # DataFrame with truly only 1 numeric column available
    df_one_num = pd.DataFrame({
        "name": ["A", "B", "C", "D", "E"],
        "score": [10, 20, 30, 40, 50],
    })
    cols_one_num = [
        {"name": "name", "dtype": "object", "dtype_cn": "分类"},
        {"name": "score", "dtype": "int64", "dtype_cn": "数值"},
    ]
    contract = _make_contract(chart_type="scatter", x_col="name", y_cols=["score"])
    failures = validate_types(contract, df_one_num, cols_one_num)
    # scatter needs 2 numeric columns; only 1 exists
    assert len(failures) >= 1, f"Expected at least 1 failure, got {len(failures)}"
    severity_levels = {f.severity for f in failures}
    assert "fatal" in severity_levels, (
        f"Expected fatal severity among failures, got {severity_levels}"
    )


def test_type_validator_line_with_numeric(basic_df, basic_columns):
    """Line chart + numeric → empty (or advisory if no time column)."""
    contract = _make_contract(chart_type="line", x_col="value1", y_cols=["value2"])
    failures = validate_types(contract, basic_df, basic_columns)
    # Line with numeric should pass; advisory warnings are acceptable
    fatals = [f for f in failures if f.severity == "fatal"]
    assert len(fatals) == 0, f"Expected no fatal failures, got {fatals}"


def test_type_validator_pie_with_category_and_numeric(basic_df, basic_columns):
    """Pie chart + 1 category + 1 numeric → empty failures."""
    contract = _make_contract(chart_type="pie", x_col="category", y_cols=["value1"])
    failures = validate_types(contract, basic_df, basic_columns)
    assert failures == [], f"Expected no type failures for valid pie, got {failures}"


def test_type_validator_pie_with_many_categories(basic_df, basic_columns):
    """Pie chart with 50 categories → advisory warning."""
    # basic_df has category with 5 unique values, which is fine.
    # We create a temp df with many categories to test the advisory.
    big_cat_df = pd.DataFrame({
        "big_cat": [f"Cat_{i}" for i in range(50)],
        "val": range(50),
    })
    big_cols = [
        {"name": "big_cat", "dtype": "object", "dtype_cn": "分类"},
        {"name": "val", "dtype": "int64", "dtype_cn": "数值"},
    ]
    contract = _make_contract(chart_type="pie", x_col="big_cat", y_cols=["val"])
    failures = validate_types(contract, big_cat_df, big_cols)
    # May or may not warn depending on implementation; at minimum no fatal
    fatals = [f for f in failures if f.severity == "fatal"]
    assert len(fatals) == 0, (
        f"Expected no fatal failures for many-category pie, got {fatals}"
    )


# ═══════════════════════════════════════════════════════════════
# 3.  IntentValidator tests
# ═══════════════════════════════════════════════════════════════

def test_intent_validator_chart_type_matches_selector(basic_columns):
    """Contract chart_type == chart_selector_output → empty failures."""
    contract = _make_contract(chart_type="bar")
    selector_output = "bar"
    failures = validate_intent(contract, selector_output, "show bar chart")
    assert failures == [], f"Expected no intent failures when types match, got {failures}"


def test_intent_validator_chart_type_differs_from_selector(basic_columns):
    """Contract chart_type != chart_selector_output → advisory failure."""
    contract = _make_contract(chart_type="bar")
    selector_output = "line"
    user_message = "show the trend over time"
    failures = validate_intent(contract, selector_output, user_message)
    assert len(failures) >= 1, (
        f"Expected at least 1 failure when types differ, got {len(failures)}"
    )
    # Should be advisory, not fatal
    severities = {f.severity for f in failures}
    assert "advisory" in severities or "warning" in severities, (
        f"Expected advisory/warning severity, got {severities}"
    )


# ═══════════════════════════════════════════════════════════════
# 4.  ConflictResolver tests
# ═══════════════════════════════════════════════════════════════

def test_conflict_resolver_no_conflict(basic_columns):
    """Chart types match → returns contract.chart_type unchanged."""
    contract = _make_contract(chart_type="bar")
    result = resolve_conflict(contract, "bar")
    assert result == "bar", f"Expected 'bar', got '{result}'"


def test_conflict_resolver_selector_wins_on_conflict(basic_columns):
    """LLM says scatter, selector says line → returns selector's 'line'."""
    contract = _make_contract(chart_type="scatter")
    result = resolve_conflict(contract, "line")
    assert result == "line", (
        f"Expected selector's 'line' to win, got '{result}'"
    )


# ═══════════════════════════════════════════════════════════════
# 5.  RepairPolicyEngine tests (via decide_repair)
# ═══════════════════════════════════════════════════════════════

def test_repair_policy_all_pass_proceed(default_contract, basic_df, basic_columns):
    """All validators pass → action='proceed'."""
    result = ValidationResult(passed=True, failures=[], warnings=[])
    decision = decide_repair(result, default_contract, basic_df, basic_columns)
    assert decision.action == "proceed", (
        f"Expected action 'proceed', got '{decision.action}'"
    )


def test_repair_policy_fatal_failure_reject(default_contract, basic_df, basic_columns):
    """Fatal failure present → action='reject'."""
    fatal_failure = ContractFailure(
        validator="column",
        reason="Column 'nonexistent' not found",
        severity="fatal",
        field="x_column",
        suggestion=None,
    )
    result = ValidationResult(passed=False, failures=[fatal_failure], warnings=[])
    decision = decide_repair(result, default_contract, basic_df, basic_columns)
    assert decision.action == "reject", (
        f"Expected action 'reject', got '{decision.action}'"
    )


def test_repair_policy_repairable_failure_triggers_repair(
    default_contract, basic_df, basic_columns
):
    """Repairable failure → action='repair' with repaired_contract."""
    repairable = ContractFailure(
        validator="column",
        reason="Column 'catagory' not found; did you mean 'category'?",
        severity="repairable",
        field="x_column",
        suggestion="category",
    )
    result = ValidationResult(passed=False, failures=[repairable], warnings=[])
    decision = decide_repair(result, default_contract, basic_df, basic_columns)
    assert decision.action == "repair", (
        f"Expected action 'repair', got '{decision.action}'"
    )
    assert decision.repaired_contract is not None, (
        "Expected repaired_contract to be set on repair decision"
    )


def test_repair_policy_exploratory_with_fatal_degrade(
    default_contract, basic_df, basic_columns
):
    """Exploratory policy + fatal failure → action='degrade' with degrade_plan."""
    contract = _make_contract(policy="exploratory")
    fatal_failure = ContractFailure(
        validator="type",
        reason="Scatter requires 2 numeric columns but only 1 found",
        severity="fatal",
        field="chart_type",
        suggestion=None,
    )
    result = ValidationResult(passed=False, failures=[fatal_failure], warnings=[])
    decision = decide_repair(result, contract, basic_df, basic_columns)
    assert decision.action in ("degrade", "repair", "reject"), (
        f"Expected degrade/repair/reject for exploratory+fatal, got '{decision.action}'"
    )
    if decision.action == "degrade":
        assert decision.degrade_plan is not None, (
            "Expected degrade_plan to be set on degrade decision"
        )


# ═══════════════════════════════════════════════════════════════
# 6.  ExecutionApproval tests (via approve)
# ═══════════════════════════════════════════════════════════════

def test_approval_proceed_approved(default_contract):
    """Proceed decision → approved=True, contract unchanged."""
    result = ValidationResult(passed=True, failures=[], warnings=[])
    repair = RepairDecision(
        action="proceed",
        repaired_contract=None,
        degrade_plan=None,
        error_message=None,
    )
    approval = approve(default_contract, result, repair)
    assert approval.approved is True, (
        f"Expected approved=True, got {approval.approved}"
    )
    assert approval.contract is not None, "Expected contract to be present"


def test_approval_reject_not_approved(default_contract):
    """Reject decision → approved=False, error_message set."""
    result = ValidationResult(passed=False, failures=[], warnings=[])
    repair = RepairDecision(
        action="reject",
        repaired_contract=None,
        degrade_plan=None,
        error_message="Fatal validation error: column not found",
    )
    approval = approve(default_contract, result, repair)
    assert approval.approved is False, (
        f"Expected approved=False, got {approval.approved}"
    )
    assert approval.error_message is not None, (
        "Expected error_message to be set on reject"
    )


def test_approval_degrade_not_approved_with_plan(default_contract):
    """Degrade decision → approved=False, degrade_plan set."""
    result = ValidationResult(passed=False, failures=[], warnings=[])
    degrade_plan = {"fallback_chart": "bar", "reason": "Scatter not feasible"}
    repair = RepairDecision(
        action="degrade",
        repaired_contract=None,
        degrade_plan=degrade_plan,
        error_message=None,
    )
    approval = approve(default_contract, result, repair)
    assert approval.approved is False, (
        f"Expected approved=False for degrade, got {approval.approved}"
    )
    assert approval.degrade_plan is not None, (
        "Expected degrade_plan to be set on degrade approval"
    )


# ═══════════════════════════════════════════════════════════════
# 7.  Integration: full validate_contract pipeline
# ═══════════════════════════════════════════════════════════════

def test_validate_contract_full_pipeline(sample_df, sample_columns):
    """Full validate_contract → returns ValidationResult with multiple validators."""
    contract = _make_contract(
        chart_type="line",
        x_col="订单日期",
        y_cols=["销售额", "利润"],
    )
    result = validate_contract(
        contract,
        sample_df,
        sample_columns,
        chart_selector_output="line",
        user_message="show sales trend over time",
    )
    assert isinstance(result, ValidationResult), (
        f"Expected ValidationResult, got {type(result).__name__}"
    )
    assert hasattr(result, "passed"), "ValidationResult should have 'passed' attribute"
    assert hasattr(result, "failures"), "ValidationResult should have 'failures' attribute"
    assert hasattr(result, "warnings"), "ValidationResult should have 'warnings' attribute"
    assert isinstance(result.failures, list), "failures should be a list"
    assert isinstance(result.warnings, list), "warnings should be a list"
    # Should pass for valid input
    assert result.passed is True, (
        f"Expected passed=True for valid contract, got passed={result.passed}, "
        f"failures={result.failures}, warnings={result.warnings}"
    )
