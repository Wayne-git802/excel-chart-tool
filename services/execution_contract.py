"""
Execution Contract Layer — validation gateway between LLM output and chart executor.

Architecture:
  ColumnValidator  ──→  fuzzy-match column names against DataFrame
  TypeValidator    ──→  enforce data-type requirements per chart type
  IntentValidator  ──→  detect LLM deviation from ChartSelector (advisory only)
  ConflictResolver ──→  ChartSelector always wins on chart_type
  ContractValidator──→  orchestrator running all validators + conflict resolution
  RepairPolicyEngine──→  decide reject / repair / warn / degrade
  ExecutionApproval ──→  final gate with decision-ledger trace

All functions are pure, stateless, zero-LLM. Every repair is explicit and recorded.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

import pandas as pd

from services.column_registry import build_column_registry, ColumnMeta


# ═══════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════


@dataclass
class ExecutionContract:
    """Validated instruction from LLM to executor.

    chart_type: line | bar | scatter | histogram | pie | boxplot
    policy:     "strict" — reject on any fixable deviation
                "exploratory" — repair / degrade gracefully
    """

    chart_type: str = ""
    x_column: str = ""
    y_columns: list[str] = field(default_factory=list)
    title: str = ""
    policy: str = "exploratory"
    context: dict = field(default_factory=dict)


@dataclass
class ContractFailure:
    """Single validation failure with repair hint."""

    validator: str       # "ColumnValidator" | "TypeValidator" | "IntentValidator"
    reason: str          # human-readable
    severity: str        # "fatal" | "repairable" | "advisory"
    field: str = ""      # which field failed (x_column, y_columns, chart_type)
    suggestion: str = "" # repair suggestion, e.g. fuzzy match result


@dataclass
class ValidationResult:
    """Aggregated result from all validators."""

    passed: bool
    failures: list[ContractFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RepairDecision:
    """Policy engine output — how to proceed."""

    action: str                                     # "proceed" | "reject" | "repair" | "warn" | "degrade"
    repaired_contract: ExecutionContract | None = None
    degrade_plan: dict | None = None               # fallback plan for GracefulDegradation
    error_message: str = ""


@dataclass
class ApprovalResult:
    """Final gate output with decision ledger."""

    approved: bool
    contract: ExecutionContract | None = None
    degrade_plan: dict | None = None
    error_message: str = ""
    trace: dict = field(default_factory=dict)


@dataclass
class ValidationFailure:
    """Single validation failure with repair hint."""
    stage: str = ""
    field: str = ""
    reason: str = ""
    severity: str = "fatal"
    suggestion: str = ""

@dataclass
class CandidateSet:
    """Policy-filtered valid chart types."""
    valid_charts: list[str] = field(default_factory=list)
    exclusion_reasons: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# ColumnValidator — fuzzy column name matching
# ═══════════════════════════════════════════════════════════════

def _fuzzy_match(name: str, candidates: list[str], cutoff: float = 0.6) -> str:
    """Return the best fuzzy match, or '' if none passes cutoff."""
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else ""


def validate_columns(
    contract: ExecutionContract,
    df: pd.DataFrame,
    columns: list[dict],
) -> list[ContractFailure]:
    """Check every referenced column exists; try fuzzy repair on miss.

    Args:
        contract: LLM's intended execution instruction.
        df: The loaded pandas DataFrame (used for .columns).
        columns: Column metadata list (used for dtype_cn lookups).

    Returns:
        List of failures (empty = all pass).  Repairable failures include
        a fuzzy-match suggestion in ContractFailure.suggestion.
    """
    failures: list[ContractFailure] = []
    df_cols = list(df.columns)

    # --- x_column ---
    x = contract.x_column
    if not x:
        failures.append(ContractFailure(
            validator="ColumnValidator",
            reason="x_column is required but not specified",
            severity="fatal",
            field="x_column",
        ))
    elif x not in df_cols:
            suggestion = _fuzzy_match(x, df_cols)
            if suggestion:
                failures.append(ContractFailure(
                    validator="ColumnValidator",
                    reason=f"x_column '{x}' not found; nearest match: '{suggestion}'",
                    severity="repairable",
                    field="x_column",
                    suggestion=suggestion,
                ))
            else:
                failures.append(ContractFailure(
                    validator="ColumnValidator",
                    reason=f"x_column '{x}' not found in DataFrame",
                    severity="fatal",
                    field="x_column",
                ))

    # --- y_columns ---
    y_cols = contract.y_columns
    if not y_cols:
        failures.append(ContractFailure(
            validator="ColumnValidator",
            reason="y_columns is required but empty",
            severity="fatal",
            field="y_columns",
        ))
    else:
        for y in y_cols:
            if y not in df_cols:
                suggestion = _fuzzy_match(y, df_cols)
                if suggestion:
                    failures.append(ContractFailure(
                        validator="ColumnValidator",
                        reason=f"y_column '{y}' not found; nearest match: '{suggestion}'",
                        severity="repairable",
                        field="y_columns",
                        suggestion=suggestion,
                    ))
                else:
                    failures.append(ContractFailure(
                        validator="ColumnValidator",
                        reason=f"y_column '{y}' not found in DataFrame",
                        severity="fatal",
                        field="y_columns",
                    ))

    return failures


# ═══════════════════════════════════════════════════════════════
# TypeValidator — chart-type data requirements
# ═══════════════════════════════════════════════════════════════

_NUMERIC_CN = {"数值", "整数分类"}
_CATEGORY_CN = {"分类", "整数分类", "二值"}
_TIME_CN = {"日期"}


def _count_numeric(columns: list[dict]) -> int:
    """Count columns with numeric Chinese type labels."""
    return sum(1 for c in columns if c.get("dtype_cn", "") in _NUMERIC_CN)


def _count_category(columns: list[dict]) -> int:
    """Count columns with category Chinese type labels."""
    return sum(1 for c in columns if c.get("dtype_cn", "") in _CATEGORY_CN)


def _count_time(columns: list[dict]) -> int:
    """Count columns with time/date Chinese type labels."""
    return sum(1 for c in columns if c.get("dtype_cn", "") in _TIME_CN)


def validate_types(
    contract: ExecutionContract,
    df: pd.DataFrame,
    columns: list[dict],
) -> list[ContractFailure]:
    """Check column types satisfy the chart type's data requirements.

    Requirements per chart_type:
        line:      needs ≥1 numeric y  (advisory if no time col)
        scatter:   needs ≥2 numeric    (fatal if <2)
        bar:       needs ≥1 numeric y  (fatal if 0)
        histogram: needs ≥1 numeric    (fatal if 0)
        pie:       needs category + numeric (advisory if >20 categories)
        boxplot:   needs ≥1 numeric    (fatal if 0)

    Uses col_info dict's dtype_cn field: "数值", "文本", "日期", "分类", "整数分类", "二值"

    Args:
        contract: LLM's intended execution instruction.
        df: The loaded pandas DataFrame.
        columns: Column metadata list.

    Returns:
        List of failures (empty = all pass).
    """
    failures: list[ContractFailure] = []
    chart = contract.chart_type
    n_num = _count_numeric(columns)
    n_cat = _count_category(columns)
    n_time = _count_time(columns)

    # --- line ---
    if chart == "line":
        if n_num < 1:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="折线图需要至少 1 列数值型数据",
                severity="fatal",
                field="chart_type",
            ))
        elif n_time == 0:
            # Advisory: line chart without time column — still works (index as x)
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="折线图没有检测到日期/时间列，将使用行索引作为 X 轴",
                severity="advisory",
                field="chart_type",
            ))

    # --- scatter ---
    elif chart == "scatter":
        if n_num < 2:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason=f"散点图需要至少 2 列数值型数据，当前仅 {n_num} 列",
                severity="fatal",
                field="chart_type",
            ))

    # --- bar ---
    elif chart == "bar":
        if n_num < 1:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="柱状图需要至少 1 列数值型数据",
                severity="fatal",
                field="chart_type",
            ))

    # --- histogram ---
    elif chart == "histogram":
        if n_num < 1:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="直方图需要至少 1 列数值型数据",
                severity="fatal",
                field="chart_type",
            ))

    # --- pie ---
    elif chart == "pie":
        if n_cat < 1:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="饼图需要至少 1 列分类数据",
                severity="fatal",
                field="chart_type",
            ))
        if n_num < 1:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="饼图需要至少 1 列数值型数据",
                severity="fatal",
                field="chart_type",
            ))
        else:
            # Advisory: pie with >20 unique values becomes unreadable
            # Check if any category column has high cardinality
            for c in columns:
                if c.get("dtype_cn", "") in _CATEGORY_CN:
                    if c.get("unique_count", 0) > 20:
                        failures.append(ContractFailure(
                            validator="TypeValidator",
                            reason=f"饼图分类列 '{c.get('name', '')}' 有 {c['unique_count']} 个不同值，建议 ≤20 个以获得清晰图表",
                            severity="advisory",
                            field="chart_type",
                        ))
                        break  # emit one advisory only

    # --- boxplot ---
    elif chart == "boxplot":
        if n_num < 1:
            failures.append(ContractFailure(
                validator="TypeValidator",
                reason="箱线图需要至少 1 列数值型数据",
                severity="fatal",
                field="chart_type",
            ))

    return failures


# ═══════════════════════════════════════════════════════════════
# IntentValidator — detect LLM deviation from ChartSelector
# ═══════════════════════════════════════════════════════════════

def validate_intent(
    contract: ExecutionContract,
    chart_selector_output: str,
    user_message: str = "",
) -> list[ContractFailure]:
    """Detect when the LLM has deviated from the ChartSelector's intent-based choice.

    NOTE: This is advisory only — it doesn't block execution.
    The ConflictResolver handles the actual override.

    Args:
        contract: LLM's intended execution instruction.
        chart_selector_output: ChartSelector's authoritative chart_type.
        user_message: Original user query (reserved for future intent comparison).

    Returns:
        List with one advisory failure if deviation detected, empty otherwise.
    """
    failures: list[ContractFailure] = []
    if contract.chart_type and contract.chart_type != chart_selector_output:
        failures.append(ContractFailure(
            validator="IntentValidator",
            reason=f"LLM selected '{contract.chart_type}' but ChartSelector selected '{chart_selector_output}'; ChartSelector is the sole authority",
            severity="advisory",
            field="chart_type",
        ))
    return failures


# ═══════════════════════════════════════════════════════════════
# ConflictResolver — ChartSelector always wins
# ═══════════════════════════════════════════════════════════════

def resolve_conflict(contract: ExecutionContract, chart_selector_output: str) -> str:
    """Resolve chart_type conflict. ChartSelector is the sole authority.

    Args:
        contract: LLM's intended execution instruction.
        chart_selector_output: ChartSelector's authoritative chart_type.

    Returns:
        The resolved chart_type string.
    """
    if contract.chart_type != chart_selector_output:
        contract.context["chart_type_overridden"] = True
        contract.context["original_llm_chart_type"] = contract.chart_type
        contract.chart_type = chart_selector_output
    return contract.chart_type


# ═══════════════════════════════════════════════════════════════
# ContractValidator — orchestrator
# ═══════════════════════════════════════════════════════════════

def validate_contract(
    contract: ExecutionContract,
    df: pd.DataFrame,
    columns: list[dict],
    chart_selector_output: str,
    user_message: str = "",
) -> ValidationResult:
    """Run all validators and resolve conflicts. Aggregate into one result.

    Pipeline:
      1. ColumnValidator  → fuzzy-match column names
      2. TypeValidator    → check data-type suitability
      3. IntentValidator  → detect LLM/ChartSelector deviation
      4. ConflictResolver → ChartSelector always wins

    Args:
        contract: LLM's intended execution instruction.
        df: The loaded pandas DataFrame.
        columns: Column metadata list from analyzer.
        chart_selector_output: ChartSelector's authoritative chart_type.
        user_message: Original user query.

    Returns:
        Aggregated ValidationResult.
    """
    all_failures: list[ContractFailure] = []
    all_warnings: list[str] = []

    # 1. Column validation
    col_failures = validate_columns(contract, df, columns)
    all_failures.extend(col_failures)

    # 2. Intent validation — capture LLM deviation BEFORE conflict resolution
    #    (runs against the original contract.chart_type vs chart_selector_output)
    intent_failures = validate_intent(contract, chart_selector_output, user_message)
    for f in intent_failures:
        if f.severity == "advisory":
            all_warnings.append(f.reason)
        else:
            all_failures.append(f)

    # 3. Resolve chart_type conflict AFTER intent check
    #    (so type validation runs against the authoritative chart_type)
    resolve_conflict(contract, chart_selector_output)

    # 4. Type validation (against resolved chart_type)
    type_failures = validate_types(contract, df, columns)
    all_failures.extend(type_failures)

    # Determine pass/fail: passed if NO fatal failures
    has_fatal = any(f.severity == "fatal" for f in all_failures)
    passed = not has_fatal

    return ValidationResult(
        passed=passed,
        failures=all_failures,
        warnings=all_warnings,
    )


# ═══════════════════════════════════════════════════════════════
# RepairPolicyEngine — decide reject / repair / warn / degrade
# ═══════════════════════════════════════════════════════════════

def decide_repair(
    result: ValidationResult,
    contract: ExecutionContract,
    df: pd.DataFrame,
    columns: list[dict],
) -> RepairDecision:
    """Translate validation result into a concrete action.

    Decision matrix:
      - result.passed                              → "proceed"
      - any fatal failure                          → "reject"
      - only repairable failures                   → "repair"
      - only advisory failures                     → "warn"
      - exploratory policy + fatal failure         → "degrade"

    Args:
        result: Aggregated validation result.
        contract: Current ExecutionContract (may be mutated for repair).
        df: Loaded DataFrame.
        columns: Column metadata list.

    Returns:
        RepairDecision with action and, when applicable, repaired contract
        or degrade plan.
    """
    # Proceed: no failures at all
    if result.passed and not result.failures:
        return RepairDecision(action="proceed")

    fatal_any = any(f.severity == "fatal" for f in result.failures)
    repairable_any = any(f.severity == "repairable" for f in result.failures)
    advisory_any = any(f.severity == "advisory" for f in result.failures)
    non_advisory = [f for f in result.failures if f.severity != "advisory"]

    # Only advisory failures → warn (execute anyway)
    if not fatal_any and not repairable_any and advisory_any:
        return RepairDecision(action="warn")

    # Only repairable failures → repair
    if not fatal_any and repairable_any:
        repaired = ExecutionContract(
            chart_type=contract.chart_type,
            x_column=contract.x_column,
            y_columns=list(contract.y_columns),
            title=contract.title,
            policy=contract.policy,
            context=dict(contract.context),
        )
        repairs_made: list[str] = []

        for f in result.failures:
            if f.severity == "repairable" and f.suggestion:
                if f.field == "x_column":
                    old = repaired.x_column
                    repaired.x_column = f.suggestion
                    repairs_made.append(f"x_column: '{old}' → '{f.suggestion}'")
                elif f.field == "y_columns":
                    # Replace the bad column name in y_columns with suggestion
                    for i, y in enumerate(repaired.y_columns):
                        if y not in list(df.columns) and _fuzzy_match(y, list(df.columns)) == f.suggestion:
                            old = repaired.y_columns[i]
                            repaired.y_columns[i] = f.suggestion
                            repairs_made.append(f"y_column: '{old}' → '{f.suggestion}'")
                            break

        repaired.context["repair_attempted"] = repairs_made
        return RepairDecision(
            action="repair",
            repaired_contract=repaired,
        )

    # Fatal failure
    if fatal_any:
        # Exploratory policy → degrade instead of hard reject
        if contract.policy == "exploratory":
            degrade_plan = _build_degrade_plan(df, columns)
            return RepairDecision(
                action="degrade",
                degrade_plan=degrade_plan,
                error_message="; ".join(f.reason for f in non_advisory),
            )
        # Strict policy → reject
        return RepairDecision(
            action="reject",
            error_message="; ".join(f.reason for f in non_advisory),
        )

    # Fallback — shouldn't reach here
    return RepairDecision(action="reject", error_message="Unknown validation state")


def _build_degrade_plan(df: pd.DataFrame, columns: list[dict]) -> dict:
    """Build a simple fallback bar chart plan when the original is infeasible.

    Auto-detects:
      - x_column: first category column, or first text column, or index
      - y_columns: first numeric column
      - chart_type: bar (universal fallback)
    """
    df_cols = list(df.columns)
    # Use both dtype_cn AND raw dtype — some loaders label int64 as "整数分类"
    _num_dtypes = {"float64", "int64", "int32", "float32"}
    numeric_names = [
        c["name"] for c in columns
        if c.get("dtype_cn", "") in _NUMERIC_CN or c.get("dtype", "") in _num_dtypes
    ]
    category_names = [c["name"] for c in columns if c.get("dtype_cn", "") in _CATEGORY_CN]

    x = category_names[0] if category_names else (df_cols[0] if df_cols else "")
    if not x and len(df_cols) > 1:
        x = df_cols[0]

    y = numeric_names[0] if numeric_names else (df_cols[1] if len(df_cols) > 1 else "")
    if not y and len(df_cols) >= 2:
        y = df_cols[1]

    return {
        "fallback_chart_type": "bar",
        "x_column": x,
        "y_columns": [y] if y else [],
        "title": "数据概览（自动降级）",
        "reason": "原始图表请求不可行，降级为通用柱状图",
    }


# ═══════════════════════════════════════════════════════════════
# ExecutionApproval — final gate with decision ledger
# ═══════════════════════════════════════════════════════════════

def approve(
    contract: ExecutionContract,
    result: ValidationResult,
    repair_decision: RepairDecision,
) -> ApprovalResult:
    """Final gate: approve, reject, or degrade the contract.

    Builds a trace dict documenting every decision made.

    Args:
        contract: Original ExecutionContract.
        result: Aggregated validation result from validate_contract.
        repair_decision: Policy decision from decide_repair.

    Returns:
        ApprovalResult with approved flag, final contract, trace.
    """
    trace: dict = {
        "original_contract": {
            "chart_type": contract.chart_type,
            "x_column": contract.x_column,
            "y_columns": contract.y_columns,
            "title": contract.title,
            "policy": contract.policy,
        },
        "validation_passed": result.passed,
        "failure_count": len(result.failures),
        "warning_count": len(result.warnings),
        "failures": [
            {
                "validator": f.validator,
                "reason": f.reason,
                "severity": f.severity,
                "field": f.field,
            }
            for f in result.failures
        ],
        "warnings": result.warnings,
        "action": repair_decision.action,
    }

    action = repair_decision.action

    if action == "proceed":
        return ApprovalResult(
            approved=True,
            contract=contract,
            trace=trace,
        )

    if action == "warn":
        return ApprovalResult(
            approved=True,
            contract=contract,
            trace=trace,
        )

    if action == "repair":
        repaired = repair_decision.repaired_contract
        trace["repaired_contract"] = {
            "chart_type": repaired.chart_type if repaired else "",
            "x_column": repaired.x_column if repaired else "",
            "y_columns": repaired.y_columns if repaired else [],
            "repair_log": repaired.context.get("repair_attempted", []) if repaired else [],
        }
        return ApprovalResult(
            approved=True,
            contract=repaired,
            trace=trace,
        )

    if action == "reject":
        trace["error_message"] = repair_decision.error_message
        return ApprovalResult(
            approved=False,
            error_message=repair_decision.error_message,
            trace=trace,
        )

    if action == "degrade":
        trace["degrade_plan"] = repair_decision.degrade_plan
        trace["error_message"] = repair_decision.error_message
        return ApprovalResult(
            approved=False,
            degrade_plan=repair_decision.degrade_plan,
            error_message=repair_decision.error_message,
            trace=trace,
        )

    # Fallback
    return ApprovalResult(
        approved=False,
        error_message=f"Unknown action: {action}",
        trace=trace,
    )


# == Contract Kernel v1.2 ==

def _validate_complete(args: dict, df: pd.DataFrame, registry: dict) -> tuple:
    """Closed-form full-schema validation. Returns (failures, warnings)."""
    failures = []
    warnings = []
    df_cols = list(df.columns)

    # x_column - required, must exist
    x = args.get("x", "")
    if not x:
        failures.append(ValidationFailure(
            stage="validate", field="x_column",
            reason="x_column is required but not specified",
            severity="fatal"))
    elif x not in df_cols:
        suggestion = _fuzzy_match(x, df_cols)
        if suggestion:
            failures.append(ValidationFailure(
                stage="validate", field="x_column",
                reason=f"x_column '{x}' not found; nearest: '{suggestion}'",
                severity="repairable", suggestion=suggestion))
        else:
            failures.append(ValidationFailure(
                stage="validate", field="x_column",
                reason=f"x_column '{x}' not found in DataFrame",
                severity="fatal"))

    # y_columns - required, each must exist
    y = args.get("y", [])
    if isinstance(y, str):
        y = [y]
    if not y:
        failures.append(ValidationFailure(
            stage="validate", field="y_columns",
            reason="y_columns is required but empty",
            severity="fatal"))
    else:
        for yc in y:
            if yc not in df_cols:
                suggestion = _fuzzy_match(yc, df_cols)
                if suggestion:
                    failures.append(ValidationFailure(
                        stage="validate", field="y_columns",
                        reason=f"y_column '{yc}' not found; nearest: '{suggestion}'",
                        severity="repairable", suggestion=suggestion))
                else:
                    failures.append(ValidationFailure(
                        stage="validate", field="y_columns",
                        reason=f"y_column '{yc}' not found in DataFrame",
                        severity="fatal"))

    # chart_type validity
    ct = args.get("type", "bar")
    if ct not in {"line", "bar", "scatter", "histogram", "pie", "boxplot"}:
        failures.append(ValidationFailure(
            stage="validate", field="chart_type",
            reason=f"Invalid chart_type: {ct}",
            severity="fatal"))

    # title - warn only
    if not args.get("title"):
        warnings.append("title is empty, will auto-generate")

    return failures, warnings


def _build_candidates(registry: dict) -> CandidateSet:
    """Policy hard-constraint filter."""
    n_numeric = sum(1 for m in registry.values() if m.is_numeric)
    has_cat = any(m.is_categorical for m in registry.values())

    POLICY = {
        "line": n_numeric >= 1,
        "bar": n_numeric >= 1,
        "scatter": n_numeric >= 2,
        "histogram": n_numeric >= 1,
        "pie": has_cat and n_numeric == 1,
        "boxplot": n_numeric >= 1,
    }
    valid = [ct for ct, ok in POLICY.items() if ok]
    exclusion = {ct: "policy_constraint" for ct, ok in POLICY.items() if not ok}
    return CandidateSet(valid_charts=valid, exclusion_reasons=exclusion)


def _schema_rank(chart: str, registry: dict) -> int:
    """Discrete schema fit: 0=perfect, 1=good, 2=ok, 3=poor."""
    n_num = sum(1 for m in registry.values() if m.is_numeric)
    has_t = any(m.is_temporal for m in registry.values())
    has_c = any(m.is_categorical for m in registry.values())

    if chart == "line":
        return 0 if (has_t and n_num >= 1) else (1 if n_num >= 1 else 3)
    if chart == "bar":
        return 0 if (has_c and n_num >= 1) else (1 if n_num >= 1 else 2)
    if chart == "scatter":
        return 0 if n_num >= 2 else 3
    if chart == "pie":
        return 0 if (has_c and n_num == 1) else (2 if (has_c and n_num > 1) else 3)
    if chart == "histogram":
        return 0 if n_num >= 3 else (1 if n_num >= 1 else 3)
    if chart == "boxplot":
        return 0 if n_num >= 2 else (1 if n_num >= 1 else 3)
    return 2


def _resolve(args: dict, candidates: CandidateSet, message: str, registry: dict) -> dict:
    """Deterministic rank-based chart selection. NOT weighted scoring."""
    INTENT_KW = {
        "line": ["趋势", "变化", "增长", "下降", "走势", "折线", "曲线"],
        "bar": ["对比", "比较", "排名", "差异", "柱状", "条形"],
        "scatter": ["相关", "关联", "散点", "关系"],
        "histogram": ["分布", "直方", "频率"],
        "pie": ["占比", "比例", "份额", "饼图", "构成"],
        "boxplot": ["异常", "离群", "箱线"],
    }
    primary = ""
    for ct, kws in INTENT_KW.items():
        if any(kw in message for kw in kws):
            primary = ct
            break

    DEFAULT_PRIORITY = {"bar": 0, "line": 1, "pie": 2, "scatter": 3, "histogram": 4, "boxplot": 5}

    def rank_key(chart):
        intent_match = 0 if chart == primary else 1
        schema_r = _schema_rank(chart, registry)
        default_r = DEFAULT_PRIORITY.get(chart, 99)
        return (intent_match, schema_r, default_r)

    ranked = sorted(candidates.valid_charts, key=rank_key)
    return {
        "chart_type": ranked[0],
        "ranking": ranked,
        "runner_up": ranked[1] if len(ranked) > 1 else None,
    }


# ── Chart Narrative Authority ──────────────────────────────

CHART_NARRATIVE = {
    "line":      "已选择折线图展示变化趋势",
    "bar":       "已选择柱状图进行类别对比",
    "scatter":   "已选择散点图展示变量关系",
    "pie":       "已选择饼图展示构成比例",
    "histogram": "已选择直方图展示数据分布",
    "boxplot":   "已选择箱线图展示数据离散情况",
}


def chart_narrative(chart_type: str) -> str:
    """Return authoritative chart narrative. Contract is sole owner."""
    return CHART_NARRATIVE.get(chart_type, f"已选择{chart_type}图表")


def _build_explanation(chart_type: str, registry: dict, resolution: dict) -> list[str]:
    """Build structured explanation for why this chart was chosen.
    Contract is the sole authority for chart reasoning.
    LLM may narrate these reasons but must not re-evaluate them."""
    reasons = []

    n_num = sum(1 for m in registry.values() if m.is_numeric)
    has_cat = any(m.is_categorical for m in registry.values())
    has_time = any(m.is_temporal for m in registry.values())

    if n_num >= 2:
        reasons.append(f"检测到 {n_num} 个数值列")
    if has_cat:
        reasons.append("检测到分类列")
    if has_time:
        reasons.append("检测到时间列")

    chart_reasons = {
        "line": "时序数据适合展示变化趋势",
        "bar": "分类对比数据适合柱状图",
        "scatter": "双数值列适合观察相关关系",
        "pie": "单数值+分类列适合展示构成比例",
        "histogram": "多数值列适合展示数据分布",
        "boxplot": "多数值列适合展示离散情况和异常值",
    }
    reasons.append(chart_reasons.get(chart_type, f"选择{chart_type}图表"))

    ranking = resolution.get("ranking", [])
    if len(ranking) > 1:
        runner_up = ranking[1]
        reasons.append(f"备选类型: {runner_up}（因默认优先级较低未选择）")

    return reasons


# ── Column Selection ──────────────────────────────────────

def select_columns(
    df: "pd.DataFrame",
    registry: dict,
    intent: str = "",
    user_hints: dict = None,
) -> dict:
    """Deterministic column selection. No LLM involved.

    Rules:
      x = first categorical column → text column → best non-numeric
          → fallback: first column (never pick numeric for x)
      y = all numeric columns → fallback: column[1]

    Reserved: intent and user_hints for future use
    (e.g. "看趋势" → prefer temporal x, "看分布" → single numeric y).

    Returns:
        {"x": str, "y": list[str], "_meta": {"fallback_tier": int, "reason": str}}
    """
    import pandas as pd
    from services.column_registry import canonicalize_name

    df_cols = list(df.columns)
    # Map canonical → original for registry lookup
    col_map = {canonicalize_name(c): c for c in df_cols}
    canonical_cols = list(col_map.keys())

    category_cols = [c for c in canonical_cols
                     if registry.get(c) and registry[c].is_categorical]
    numeric_cols = [c for c in canonical_cols
                    if registry.get(c) and registry[c].is_numeric]
    text_cols = [c for c in canonical_cols
                 if registry.get(c) and not registry[c].is_numeric and not registry[c].is_categorical]

    # x: category → text → best non-numeric → first column
    x = ""
    fallback_tier = 0
    reason = ""

    if category_cols:
        x = category_cols[0]
        reason = "first categorical column"
    elif text_cols:
        x = text_cols[0]
        reason = "first text column"
        fallback_tier = 1
    else:
        # Fallback heuristic: pick non-numeric column with most unique values
        non_num = [c for c in canonical_cols if c not in numeric_cols]
        if non_num:
            try:
                distinct_counts = [(c, df[col_map[c]].nunique()) for c in non_num]
                best = max(distinct_counts, key=lambda t: t[1])
                x = col_map[best[0]]
                reason = f"heuristic: {best[0]} has {best[1]} unique values"
                fallback_tier = 2
            except Exception:
                x = df_cols[0]
                reason = "fallback: first column"
                fallback_tier = 3
        elif df_cols:
            x = df_cols[0]
            reason = "fallback: first column"
            fallback_tier = 3

    # y: all numeric → fallback: column[1]  (return original names)
    y = ([col_map[c] for c in numeric_cols] if numeric_cols
         else ([df_cols[1]] if len(df_cols) > 1 else []))

    return {
        "x": col_map.get(x, x),
        "y": y,
        "_meta": {"fallback_tier": fallback_tier, "reason": reason},
    }


# ── Contract Entry ─────────────────────────────────────────

def contract_entry(inp: dict) -> dict:
    """Contract Gate - single mandatory entry point. 6-stage pipeline."""
    import uuid
    EXPECTED = {"chart_type", "x", "y", "title", "status", "trace_id", "narratives", "explanation", "_locked"}
    trace_id = uuid.uuid4().hex[:8]

    # Stage 1: Normalize
    args = dict(inp.get("args", {}))
    if "y" in args and isinstance(args["y"], str):
        args["y"] = [args["y"]]
    if args.get("type") is None:
        args["type"] = "bar"
    if "x" in args and isinstance(args["x"], str):
        args["x"] = args["x"].strip()

    # Stage 2: Canonicalize
    registry = build_column_registry(inp.get("columns", []))
    ALIASES = {
        "折线": "line", "曲线": "line", "柱状": "bar", "柱形": "bar",
        "条形": "bar", "散点": "scatter", "气泡": "scatter",
        "饼图": "pie", "环形": "pie", "直方": "histogram",
        "箱线": "boxplot", "箱形": "boxplot",
    }
    args["type"] = ALIASES.get(args.get("type", "bar"), args.get("type", "bar"))

    # Stage 3: Validate
    failures, warnings = _validate_complete(args, inp["df"], registry)
    fatal = [f for f in failures if f.severity == "fatal"]
    repairable = [f for f in failures if f.severity == "repairable"]

    if repairable and not fatal:
        for f in repairable:
            if f.field == "x_column" and f.suggestion:
                args["x"] = f.suggestion
            elif f.field == "y_columns" and f.suggestion:
                args["y"] = [f.suggestion if y == f.field else y
                           for y in args.get("y", [])]
        failures, warnings = _validate_complete(args, inp["df"], registry)
        fatal = [f for f in failures if f.severity == "fatal"]

    if fatal:
        policy = inp.get("policy", "exploratory")
        if policy == "exploratory":
            degrade = _build_degrade_plan(inp["df"], inp.get("columns", []))
            result = {
                "chart_type": degrade.get("fallback_chart_type", "bar"),
                "x": degrade.get("x_column", ""),
                "y": degrade.get("y_columns", []),
                "title": degrade.get("title", "数据概览"),
                "status": "degraded",
                "trace_id": trace_id,
                "narratives": ["（已调整——数据降级）"],
                "explanation": ["数据降级：LLM 未提供有效的列选择"],
                "_locked": True,
            }
            assert set(result.keys()) == EXPECTED
            return result
        else:
            return {
                "chart_type": "", "x": "", "y": [], "title": "",
                "status": "rejected", "trace_id": trace_id,
                "narratives": [], "explanation": ["strict 策略下拒绝执行"],
                "_locked": True,
            }

    # Stage 4: CandidateBuilder
    candidates = _build_candidates(registry)
    if not candidates.valid_charts:
        return {
            "chart_type": "bar", "x": args.get("x", ""),
            "y": args.get("y", []), "title": args.get("title", "数据概览"),
            "status": "degraded", "trace_id": trace_id,
            "narratives": ["无可用的图表类型，已退回到柱状图"],
            "explanation": ["无可用的图表类型"],
            "_locked": True,
        }

    # Stage 5: Resolve
    resolution = _resolve(args, candidates, inp.get("message", ""), registry)
    args["type"] = resolution["chart_type"]

    # Stage 6: Lock
    explanation = _build_explanation(args["type"], registry, resolution)
    narratives = [chart_narrative(args["type"])]

    original_type = inp.get("args", {}).get("type", "bar")
    if original_type and original_type != args["type"]:
        cn = {"line": "趋势图", "bar": "柱状图", "pie": "饼图",
              "scatter": "散点图", "histogram": "直方图", "boxplot": "箱线图"}
        cn_name = cn.get(args["type"], args["type"])
        narratives.append(f"（已调整为{cn_name}——该图表更适合当前数据特征）")

    result = {
        "chart_type": args["type"],
        "x": args.get("x", ""),
        "y": list(args.get("y", [])),
        "title": args.get("title") or f"{args['type']} 图表",
        "status": "approved",
        "trace_id": trace_id,
        "narratives": narratives,
        "explanation": explanation,
        "_locked": True,
    }
    assert set(result.keys()) == EXPECTED
    return result
