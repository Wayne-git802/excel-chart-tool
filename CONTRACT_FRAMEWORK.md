================================================================================
Contract Gate — Execution Kernel v1.2
================================================================================

设计原则
────────
  Rule 1: No Bypass          — execute_one 不接 raw LLM args
  Rule 2: Single Normalize    — 所有 normalize 只在 contract_entry 内
  Rule 3: Single Truth        — ColumnRegistry 唯一语义解释器，Contract 只消费
  Rule 4: Contract Authority  — 最终裁决者是 ContractResolver
  Rule 5: Immutable Flow      — 每阶段 input 不可变，output 是新对象
  Rule 6: Deterministic       — 相同 input → 相同 output（规则排序，非加权评分）
  Rule 7: No Dtype Access     — Contract 层禁止直接读 dtype / dtype_cn


================================================================================
一、数学结构
================================================================================

这个系统不是 rule engine，是 constrained optimization：

    maximize:  score(chart) = α·Intent(chart) + β·Feasibility(chart) + γ·Hint(chart)

    subject to: PolicyConstraints(chart) == true

其中：
  - PolicyConstraints:   硬约束，false → 从候选空间删除
  - Intent(chart):       用户意图匹配度（keyword → chart type mapping）
  - Feasibility(chart):  数据结构适配度（n_numeric, has_time, has_category）
  - Hint(chart):         软信号加权（"比较"→偏好 bar，"分布"→偏好 histogram）
  - α, β, γ:             权重系数，Policy phase 固定


================================================================================
二、6-Stage Pipeline
================================================================================

User / LLM Input
        │
        ▼
┌─────────────────────────────────────────────────┐
│              contract_entry()                    │
│                                                 │
│  1. Normalize        fix structure              │
│       │                                         │
│  2. Canonicalize     ColumnRegistry (frozen)     │
│       │                                         │
│  3. Validate         structured result           │
│       │                 ↓                        │
│  4. CandidateBuilder build valid-chart set       │  ← ⭐ 新增
│       │                 ↓                        │
│  5. Resolve          deterministic scoring       │
│       │                 ↓                        │
│  6. Lock             freeze + trace              │
│                                                 │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
              execute_one (dict only)


================================================================================
三、数据类型
================================================================================

── Kernel layer (dataclass, 类型安全) ──

@dataclass
class ColumnMeta:
    name: str
    is_numeric: bool
    is_temporal: bool
    is_categorical: bool

@dataclass
class ValidationFailure:
    stage: str              # "validate" | "candidate" | "resolve"
    field: str              # "x_column" | "y_columns" | "chart_type"
    reason: str
    severity: str           # "fatal" | "repairable" | "advisory"
    suggestion: str = ""

@dataclass
class ValidationResult:
    passed: bool
    failures: list[ValidationFailure]
    warnings: list[str]

@dataclass
class CandidateSet:
    """Policy 过滤后的合法图表类型集合（不含 scores——Resolve 用 _schema_rank）。"""
    valid_charts: list[str]              # ["bar", "line", "pie", ...]
    exclusion_reasons: dict[str, str]    # {"scatter": "n_numeric < 2", ...}

@dataclass
class ContractTrace:
    stage_results: dict     # {"normalize": ..., "canonicalize": ..., ...}
    modifications: list     # [{field, from, to, reason, stage}]
    candidate_set: CandidateSet | None

── Boundary layer (dict, 外部接口) ──

ContractInput (dict):
    {
        "args": {...},          # LLM 原始 args
        "df": DataFrame,
        "columns": [...],       # 列元数据
        "message": str,         # 用户原始消息
        "policy": str,          # "strict" | "exploratory"
    }

ContractOutput (dict — schema locked):
    {
        "chart_type": str,          # 最终选定的图表类型
        "x": str,                   # x 轴列名
        "y": list[str],             # y 轴列名列表
        "title": str,               # 图表标题
        "status": str,              # "approved" | "degraded" | "rejected"
        "trace_id": str,            # trace 标识
        "narratives": list[str],    # 需 yield 的叙事事件
        "_locked": True,
    }

    契约：contract_entry() 返回的 dict **必须恰好包含这 8 个 key**。
    调用方（orchestrator / chat_service）解包时做 key 校验：
        assert set(output.keys()) == EXPECTED_KEYS


================================================================================
四、各阶段详细设计
================================================================================

── Stage 1: Normalize ──

职责：修复 LLM 输出格式问题。纯语法修复，不做语义判断。

规则：
  - y 必须是 list：isinstance(y, str) → [y]
  - type 不能是 None → 暂设 "bar"（Resolve 会修正）
  - x 去首尾空格
  - 空 title → None（Resolve 阶段生成默认值）

契约：input 不可变，返回 new args dict。


── Stage 2: Canonicalize ──

职责：构建 ColumnRegistry，统一语义。

def build_column_registry(columns: list[dict]) -> dict[str, ColumnMeta]:
    """
    纯函数。每次完全重建，无 cache，无 global state。

    类型判定规则（单一来源）：
      is_numeric:     dtype ∈ {float64,int64,int32,float32}
                      OR dtype_cn ∈ {数值,整数}
      is_temporal:    dtype == datetime64
                      OR column name 含 {date,time,日期,时间,年,月,日}
      is_categorical: dtype_cn ∈ {分类,二值,整数分类}
                      OR dtype == object
    """
    registry = {}
    for c in columns:
        name = c["name"]
        registry[name] = ColumnMeta(
            name=name,
            is_numeric=_is_numeric(c),
            is_temporal=_is_temporal(c),
            is_categorical=_is_categorical(c),
        )
    return registry

强制规则：
  ❌ 禁止外部直接读 c["dtype"] 或 c["dtype_cn"]
  ✓ 永远通过 registry[name].is_numeric 访问

Chart type 别名归一化：
  "折线"→"line", "曲线"→"line", "趋势"→"line",
  "柱状"→"bar", "柱形"→"bar", "条形"→"bar",
  "散点"→"scatter", "气泡"→"scatter",
  "饼图"→"pie", "环形"→"pie", "占比"→"pie",
  "直方"→"histogram", "分布"→"histogram",
  "箱线"→"boxplot", "箱形"→"boxplot"


── Stage 3: Validate ──

职责：全量 schema 校验。不允许 partial path。

def _validate_complete(args: dict, df: pd.DataFrame,
                       registry: dict[str, ColumnMeta]) -> ValidationResult:
    """
    闭包式校验。每个必须字段都检查。
    返回结构化 ValidationResult，不是 boolean。
    """
    failures = []
    warnings = []

    # x_column
    x = args.get("x", "")
    if not x:
        failures.append(ValidationFailure("validate", "x_column",
                         "required but not specified", "fatal"))
    elif x not in df.columns:
        s = _fuzzy_match(x, df.columns)
        severity = "repairable" if s else "fatal"
        failures.append(ValidationFailure("validate", "x_column",
                         f"'{x}' not in DataFrame", severity, suggestion=s))

    # y_columns
    y = args.get("y", [])
    if isinstance(y, str):   # ← 这理论上在 Normalize 已修复，但防御性检查
        y = [y]
    if not y:
        failures.append(ValidationFailure("validate", "y_columns",
                         "required but empty", "fatal"))
    else:
        for yc in y:
            if yc not in df.columns:
                s = _fuzzy_match(yc, df.columns)
                severity = "repairable" if s else "fatal"
                failures.append(ValidationFailure("validate", "y_columns",
                                 f"'{yc}' not in DataFrame", severity, suggestion=s))

    # chart_type 合法性
    ct = args.get("type", "bar")
    if ct not in VALID_CHART_TYPES:
        failures.append(ValidationFailure("validate", "chart_type",
                         f"invalid type: {ct}", "fatal"))

    # title（warn 不 block）
    if not args.get("title"):
        warnings.append("title empty, will auto-generate")

    return ValidationResult(
        passed=all(f.severity != "fatal" for f in failures),
        failures=failures,
        warnings=warnings,
    )


── Stage 4: CandidateBuilder ⭐ 新增 ──

职责：Policy 硬约束裁剪候选空间。让 Resolve 只面对合法解。

def _build_candidates(registry: dict[str, ColumnMeta]) -> CandidateSet:
    """
    Policy 作为 FILTER，不是权重。
    硬约束过滤：把不可行的图表类型从候选空间删除。
    """

    # 从 registry 提取统计
    n_numeric = sum(1 for m in registry.values() if m.is_numeric)
    has_time = any(m.is_temporal for m in registry.values())
    has_category = any(m.is_categorical for m in registry.values())

    # Policy 硬约束表
    POLICY = {
        "line":      n_numeric >= 1,
        "bar":       n_numeric >= 1,            # bar 永远可行
        "scatter":   n_numeric >= 2,
        "histogram": n_numeric >= 1,
        "pie":       has_category and n_numeric == 1,
        "boxplot":   n_numeric >= 1,
    }

    valid = [ct for ct, feasible in POLICY.items() if feasible]
    exclusion = {ct: f"policy constraint failed" for ct, feasible in POLICY.items() if not feasible}

    return CandidateSet(
        valid_charts=valid,
        exclusion_reasons=exclusion,
    )


── Stage 5: Resolve (2-stage deterministic) ──

职责：在合法候选空间中，用规则排序选出最优。不是加权评分——是确定性优先级链。

def _resolve(args: dict, candidates: CandidateSet,
             message: str, registry: dict[str, ColumnMeta]) -> dict:
    """
    纯函数。相同 input → 相同 output。

    不是 weighted scoring。是 deterministic rank：
      Priority 1: Intent exact match       (1/0)
      Priority 2: Schema match score       (0–3 discrete)
      Priority 3: Default priority order   (固定链条)

    平局打破：按 default priority order。
    """

    intent = _parse_intent(message)  # {primary: "line"|"", secondary: [...]}

    def rank_key(chart: str) -> tuple:
        """
        返回排序键。Python tuple 比较从左到右，天然实现优先级链。
        """
        # Priority 1: Intent match (0=matched, 1=no match — 越小越好)
        intent_match = 0 if (chart == intent["primary"] or chart in intent["secondary"]) else 1

        # Priority 2: Schema match (0=best → 3=worst — 越小越好)
        schema_rank = _schema_rank(chart, registry)

        # Priority 3: Default priority (固定顺序 — 越小越优先)
        DEFAULT_PRIORITY = {"bar": 0, "line": 1, "pie": 2, "scatter": 3, "histogram": 4, "boxplot": 5}
        default_rank = DEFAULT_PRIORITY.get(chart, 99)

        return (intent_match, schema_rank, default_rank)

    # 在合法候选空间内排序
    ranked = sorted(candidates.valid_charts, key=rank_key)

    return {
        "chart_type": ranked[0],
        "ranking": ranked,
        "runner_up": ranked[1] if len(ranked) > 1 else None,
    }


def _schema_rank(chart: str, registry: dict[str, ColumnMeta]) -> int:
    """
    离散 schema 适配评分：0=完美匹配, 1=良好, 2=可行, 3=勉强。

    规则固定，不依赖权重、不依赖运行时状态。
    """
    n_numeric = sum(1 for m in registry.values() if m.is_numeric)
    has_time = any(m.is_temporal for m in registry.values())
    has_category = any(m.is_categorical for m in registry.values())

    if chart == "line":
        if has_time and n_numeric >= 1:  return 0   # 天然时序
        if n_numeric >= 1:               return 1   # index-based
        return 3
    if chart == "bar":
        if has_category and n_numeric >= 1:  return 0  # 天然分类对比
        if n_numeric >= 1:                   return 1
        return 2                                      # bar 永远可行但没 numeric 时降级
    if chart == "scatter":
        if n_numeric >= 2:  return 0
        return 3
    if chart == "pie":
        if has_category and n_numeric == 1:  return 0
        if has_category and n_numeric > 1:   return 2
        return 3
    if chart == "histogram":
        if n_numeric >= 3:  return 0
        if n_numeric >= 1:  return 1
        return 3
    if chart == "boxplot":
        if n_numeric >= 2:  return 0
        if n_numeric >= 1:  return 1
        return 3
    return 2  # unknown


── Stage 6: Lock ──

职责：冻结最终 args，生成不可变副本。全链路 trace。

def _lock(args: dict, trace: ContractTrace) -> dict:
    return {
        "type": args["type"],
        "x": args.get("x", ""),
        "y": list(args.get("y", [])),
        "title": args.get("title") or f"{args['type']} 图表",
        "_locked": True,
        "_trace_id": trace.id,
    }


================================================================================
五、contract_entry 主函数
================================================================================

def contract_entry(inp: dict) -> dict:
    """
    Contract Gate — 唯一执行入口门禁。

    6-stage pipeline，每阶段 immutable in → new out。
    返回 schema-locked dict（8 个 key）。
    """

    EXPECTED_OUTPUT_KEYS = {"chart_type", "x", "y", "title", "status", "trace_id", "narratives", "_locked"}
    trace_id = uuid4().hex[:8]

    # ═══ 1. Normalize ═══
    args = _normalize(inp["args"])

    # ═══ 2. Canonicalize ═══
    registry = build_column_registry(inp["columns"])
    args["type"] = _canonicalize_chart_type(args.get("type", "bar"))

    # ═══ 3. Validate ═══
    # ⚠️ 只读 registry，不直接访问 dtype/dtype_cn
    validation = _validate_complete(args, inp["df"], registry)

    # Repair: 如果只有 repairable 失败，尝试修复
    if not validation.passed:
        repairable = [f for f in validation.failures if f.severity == "repairable"]
        fatal = [f for f in validation.failures if f.severity == "fatal"]
        if repairable and not fatal:
            args = _apply_repairs(args, repairable)
            validation = _validate_complete(args, inp["df"], registry)

    if not validation.passed:
        if inp["policy"] == "exploratory":
            degrade = _build_degrade_plan(inp["df"], registry)
            result = _degrade_to_args(degrade)
            result["status"] = "degraded"
            result["trace_id"] = trace_id
            result["narratives"] = [f"（已调整为{degrade['chart_type_cn']}——数据降级）"]
            result["_locked"] = True
            assert set(result.keys()) == EXPECTED_OUTPUT_KEYS
            return result
        else:
            return {
                "chart_type": "", "x": "", "y": [], "title": "",
                "status": "rejected", "trace_id": trace_id,
                "narratives": [], "_locked": True,
            }

    # ═══ 4. CandidateBuilder ═══
    candidates = _build_candidates(registry)

    if not candidates.valid_charts:
        return {
            "chart_type": "bar", "x": args.get("x", ""), "y": args.get("y", []),
            "title": args.get("title", "数据概览"),
            "status": "degraded", "trace_id": trace_id,
            "narratives": ["无可用的图表类型，已退回到柱状图"],
            "_locked": True,
        }

    # ═══ 5. Resolve — 确定性规则排序 ═══
    resolution = _resolve(args, candidates, inp["message"], registry)
    args["type"] = resolution["chart_type"]

    # ═══ 6. Lock ═══
    narratives = []
    original_type = inp["args"].get("type", "bar")
    if original_type and original_type != args["type"]:
        type_cn = {"line": "趋势图", "bar": "柱状图", "pie": "饼图",
                   "scatter": "散点图", "histogram": "直方图", "boxplot": "箱线图"}
        narratives.append(f"（已调整为{type_cn.get(args['type'], args['type'])}——该图表更适合当前数据特征）")

    result = {
        "chart_type": args["type"],
        "x": args.get("x", ""),
        "y": list(args.get("y", [])),
        "title": args.get("title") or f"{args['type']} 图表",
        "status": "approved",
        "trace_id": trace_id,
        "narratives": narratives,
        "_locked": True,
    }
    assert set(result.keys()) == EXPECTED_OUTPUT_KEYS
    return result


================================================================================
六、调用方改造
================================================================================

所有调用方统一模式：

    inp = {
        "args": action.get("args", {}),
        "df": df,
        "columns": state.columns,
        "message": message,
        "policy": "exploratory",  # or "strict" for direct_visualization
    }
    result = contract_entry(inp)

    for n in result["narratives"]:
        yield SSEEvent("narrative", {"content": n})

    result = dispatcher.execute_one(tool, result["args"], ...)


================================================================================
七、确定性保证
================================================================================

contract_entry 的确定性来自三点：

1. registry 在 Canonicalize 阶段 frozen → 后续阶段不变
2. _resolve 是确定性规则排序（不是加权评分）：
   Priority 1: Intent match (0/1)
   Priority 2: Schema rank (0-3 discrete)
   Priority 3: Default priority (固定顺序)
   → 相同 input 永远相同 rank_key tuple → 永远相同结果
3. Policy 硬约束表 + _schema_rank 规则固定（不随运行时变化）

不存在"今天 line 赢、明天 scatter 赢"的漂移。


================================================================================
八、测试矩阵
================================================================================

L0: 内部函数（保持现有 21 tests）
    validate_columns, _hard_feasible, _build_degrade_plan, etc.

L1: ColumnRegistry（新增 3 tests）
    - 标准列（int64 + object）
    - "整数分类" dtype_cn → is_numeric=True
    - 空 columns → 空 registry

L2: CandidateBuilder（新增 4 tests）
    - 有 time + 1 numeric → valid: [line, bar, histogram, boxplot]
    - 有 category + 1 numeric → valid: [bar, pie, histogram, boxplot]
    - 2 numeric → valid: [line, bar, scatter, histogram, boxplot]
    - 0 numeric → valid: [bar]  ← bar 永远可行

L3: Resolve 确定性（新增 3 tests）
    - 相同 input 两次 → 相同 output
    - "趋势" + has_time → line 胜出
    - "趋势" + no_time → bar 可能胜出（feasibility 拉低 line）

L4: contract_entry 集成（新增 6 tests）
    - 正常 args → ok=True
    - y=string → normalize 修正 → ok=True
    - 空 x → fatal → degrade
    - 空 y → fatal → degrade
    - strict policy + fatal → ok=False, no degrade
    - exploratory + fatal → ok=False, degrade plan 有效
