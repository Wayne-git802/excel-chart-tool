# v10 Core IR Protocol — Immutable System Contracts

> 本文档定义系统所有中间表示的 Schema、不可变性边界、生产者/消费者关系、失败语义。
> 所有模块只通过这些 IR 通信。禁止跨层直接访问 df、LLM 输出、或绕过 IR 的隐式依赖。

---

## 1. DatasetProfile

**Producer:** `DataProfiler.enhance(state.columns, df)` — upload 时跑一次
**Consumer:** StateTransformer (生成 ContextualProfile), Narration
**Immutability:** ✅ 全程只读，禁止任何模块修改
**Scope:** 全局数据集

```python
@dataclass(frozen=True)
class DatasetProfile:
    version: str              # "1.0"
    hash: str                 # sha256(repr(columns))
    row_count: int
    column_count: int
    columns: dict[str, ColumnProfile]  # key = canonical name
    temporal_cols: list[str]
    categorical_cols: list[str]
    numeric_cols: list[str]
```

```python
@dataclass(frozen=True)
class ColumnProfile:
    name: str                 # canonical (fullwidth→halfwidth, stripped)
    semantic_type: str        # "temporal" | "numeric" | "categorical" | "text" | "UNKNOWN"
    raw_dtype: str            # "int64" | "float64" | "object" | "datetime64" ...
    null_rate: float          # 0.0 ~ 1.0
    unique_count: int
    cardinality: str          # "low"(≤20) | "medium"(21-100) | "high"(>100)
    distribution: str | None  # "normal" | "right_skewed" | "left_skewed" | "uniform" | None
    min: Any | None
    max: Any | None
    mean: float | None
    median: float | None
```

**Failure semantics:** 不抛异常。无法判定的列 → `semantic_type="UNKNOWN"`。空 df → `columns={}`，`temporal_cols=[]` 等。

**边界规则:**
- Profiler 只做统计事实和结构归类。不做建议、不做解释、不输出 "insights"。
- `semantic_type` 判定通道: dtype + 列名模式 + 数据采样，三通道交叉验证。
- ColumnProfile 的 `distribution` 只对 numeric 列计算。非 numeric → None。

---

## 2. AnalysisIntent

**Producer:** `IntentExtractor.extract(query)` — LLM 调用
**Consumer:** Contract, CapabilityGate
**Immutability:** ✅ 生成后只读

```python
@dataclass(frozen=True)
class AnalysisIntent:
    type: str                # "trend" | "comparison" | "distribution" | "correlation" | "overview" | "UNKNOWN"
    confidence: float        # 0.0 ~ 1.0
    explicit_chart: str | None  # 用户明确指定的图表类型 ("line" | "bar" | ...)，无→None
    entities: dict[str, Any]    # {"filter_hint": "只看张三", "metrics": ["销售额"]}
```

**Failure semantics:** LLM 无法判定 → `type="UNKNOWN"`, `confidence=0.3`。Router 兜底 → overview。

---

## 3. Capability Gate

**位置:** Router → IntentExtractor 之后，Contract 之前
**规则:**

```
SUPPORTED_CAPABILITIES = {"trend", "comparison", "distribution", "correlation", "overview"}
```

```python
@dataclass(frozen=True)
class CapabilityResult:
    allowed: bool
    reason: str  # 通过→""，拒绝→"当前系统暂不支持预测类分析"
```

**Failure semantics:**
- `AnalysisIntent.type` 不在 SUPPORTED → `CapabilityResult(allowed=False)` → 不进入 Contract → 直接返回拒绝消息。
- `AnalysisIntent.type="UNKNOWN"` → 降级为 "overview"，不拒绝。

---

## 4. FilterSpec

**Producer:** `FilterSpecBuilder.build(query, profile)` — LLM 调用
**Consumer:** `validate_filter()`, `apply_filter()`
**Immutability:** 生成后只读。apply 时不修改 FilterSpec，产出新 df。

```python
@dataclass(frozen=True)
class FilterCondition:
    column: str              # canonical name (经过 validate_filter fuzzy match)
    operator: str            # "in" | "eq" | "neq" | "gt" | "lt" | "gte" | "lte" | "between"
    value: Any

@dataclass(frozen=True)
class FilterSpec:
    conditions: list[FilterCondition]  # AND 逻辑。列表为空 = 不过滤
    persist: bool                      # True→跨轮继承(sticky), False→仅本轮(one-shot)
```

**Failure semantics:**

| 场景 | 行为 |
|------|------|
| LLM 判定无需过滤 | `conditions=[]` |
| 列名 fuzzy match 失败 | `FilterValidationError(column="名字", candidates=["姓名","客户名"])` → 返回给用户 |
| 列名 fuzzy match 成功 | 替换为 canonical name，写入 FilterSpec |
| operator 不支持 | `FilterValidationError` |
| value 类型不匹配列类型 | `FilterValidationError` |

**`validate_filter(filter, profile)`:**
1. 对每个 FilterCondition.column 做 fuzzy match (difflib, cutoff=0.6)
2. 匹配成功 → 替换为 canonical name
3. 匹配失败 → FilterValidationError
4. 校验 operator 和 value 类型

---

## 5. ContextualProfile

**Producer:** `StateTransformer.transform(global_profile, filter_spec, df_filtered)`
**Consumer:** Contract
**Immutability:** ✅ 生成后只读
**Scope:** 当前 filter 下的局部数据视图

```python
@dataclass(frozen=True)
class ContextualProfile:
    version: str              # 继承自 DatasetProfile.version
    global_hash: str          # 继承自 DatasetProfile.hash
    filter_applied: bool
    filter_spec: FilterSpec | None
    row_count: int            # filter 后行数
    column_count: int         # 不变
    temporal_cols: list[str]  # ⚠️ 重新判定：filter 后可能不再是时序
    categorical_cols: list[str]  # ⚠️ 重新算 cardinality
    numeric_cols: list[str]
    columns: dict[str, ColumnProfile]  # ⚠️ 重新算 cardinality/distribution
```

**生成规则:**
- `columns[name].cardinality` → 从 df_filtered 重新算 (unique/nunique)
- `columns[name].distribution` → 从 df_filtered 重新算
- `temporal_cols` → 重新判定：filter 后只有1个日期 → 从 temporal_cols 移除
- `categorical_cols` → 重新判定：cardinality 塌缩到1 → 从 categorical_cols 移除
- 不可变字段继承：`raw_dtype`, `null_rate`(global), `mean`/`median`(global)

**Failure semantics:**
- `df_filtered` 为空 (0行) → `ContextualProfile(row_count=0, ...)` → Contract 检测 → 返回 "筛选后无数据"
- filter_spec 为空 (conditions=[]) → 等同于 GlobalProfile，但 cardinality 重新算

---

## 6. ChartDecision

**Producer:** Contract (DSL 规则引擎)
**Consumer:** Execution Engine
**Immutability:** ✅ 生成后只读

```python
@dataclass(frozen=True)
class ChartDecision:
    chart_type: str           # "line" | "bar" | "scatter" | "histogram" | "pie" | "boxplot"
    x_column: str             # canonical name
    y_columns: list[str]      # canonical names
    title: str
    decision_source: str      # "explicit_user" | "profile_rule" | "fallback"
```

**Contract DSL 规则 (优先级排序):**

```python
CHART_RULES = [
    # 1. 用户明确指定 → 无条件使用
    Rule(when={"explicit_chart": "not_none"}, then=use_explicit, because="用户指定图表类型"),
    
    # 2. 时序+数值 → 趋势图
    Rule(when={"intent": "trend", "temporal_cols": "not_empty", "numeric_cols": "not_empty"},
         then="line", because="时序列+数值列适合趋势分析"),
    
    # 3. 对比 → 柱状图（需分类维度）
    Rule(when={"intent": "comparison", "categorical_cols": "not_empty"},
         then="bar", because="分类维度+数值对比适合柱状图"),
    
    # 4. 相关性 → 散点图（需≥2数值列）
    Rule(when={"intent": "correlation", "numeric_cols.count": {"gte": 2}},
         then="scatter", because="双数值列适合相关性分析"),
    
    # 5. 分布 → 直方图（需≥1数值列）
    Rule(when={"intent": "distribution", "numeric_cols": "not_empty"},
         then="histogram", because="单数值列适合分布分析"),
    
    # 6. 概览 → 柱状图
    Rule(when={"intent": "overview"}, then="bar", because="概览默认柱状图"),
    
    # 7. Fallback
    Rule(when={}, then="bar", because="fallback"),
]
```

**列选择 (select_columns):** 从 ContextualProfile 选 x/y:
- x = temporal_cols[0] or categorical_cols[0] or numeric_cols[0]
- y = numeric_cols

**Failure semantics:**
- `x_column` 或 `y_columns` 为空 → `ChartDecision.none()` → 不进入 Execution → 返回 table fallback
- 所有规则不匹配 → fallback 规则命中 → bar

---

## 7. DecisionLedger

**Producer:** Contract (每次 chart 决策)
**Consumer:** 调试端点, session 审计
**Persistence:** 写入 AgentState

```python
@dataclass
class DecisionLedger:
    profile_hash: str
    contextual_hash: str
    steps: list[DecisionStep]

@dataclass
class DecisionStep:
    stage: str               # "filter" | "column_select" | "chart_type"
    rule_applied: str        # because 字段
    input_summary: dict      # {intent: "trend", temporal_cols: ["日期"], ...}
    output: Any
```

---

## 8. ChartFacts

**Producer:** `ChartFactsExtractor.extract(contextual_profile, chart_decision, chart_result)`
**Consumer:** Narrator (LLM)
**Immutability:** ✅ 生成后只读

```python
@dataclass(frozen=True)
class ChartFacts:
    chart_type: str
    x_label: str
    y_labels: list[str]
    row_count: int           # filter 后
    filter_description: str  # "姓名 = 张三、李四" | "(全部数据)"
    
    # 以下字段有精确算法定义
    trend_direction: str | None  
        # 算法: simple linear regression on y_cols[0]
        # slope > 0 → "upward", slope < 0 → "downward"
        # R² < 0.3 → "unclear", 单数据点 → None
    peak_point: tuple | None
        # 算法: argmax(y_cols[0]), 返回 (x_value, y_value)
        # 多 y 轴只取第一个
    comparison: str | None
        # 触发条件: FilterSpec.persist=True AND len(filter values)=2
        # 算法: 按 y_cols[0].mean() 比较两组
        # 输出: "{A}比{B}高{X}倍"
        # 不满足条件 → None
    stats: dict[str, dict]   # {y_col: {mean, median, min, max}}
    decision_source: str      # 继承自 ChartDecision.decision_source
```

**Failure semantics:** 不抛异常。无法计算 → 字段为 None。Narrator 负责判断是否在叙述中提及。

---

## 9. FilterContext (会话级)

**Producer:** FilterSpecBuilder + Router (clear_filter 意图)
**Consumer:** StateTransformer
**Location:** AgentState.filter_context

```python
@dataclass
class FilterContext:
    sticky_filter: FilterSpec | None  # 跨轮继承
    one_shot_filter: FilterSpec | None  # 本轮用完即弃

    def active_filter(self) -> FilterSpec | None:
        """当前生效的 filter：one_shot 优先，否则 sticky"""
        return self.one_shot_filter or self.sticky_filter

    def apply_new(self, fs: FilterSpec):
        if fs.persist:
            self.sticky_filter = fs
            self.one_shot_filter = None
        else:
            self.one_shot_filter = fs

    def clear(self):
        self.sticky_filter = None
        self.one_shot_filter = None
```

**状态转换规则 (确定性，不允许 LLM 操作):**
- `persist=True` → 替换 sticky，清除 one_shot（不是叠加）
- `persist=False` → 设为 one_shot，不影响 sticky
- Router 识别 "算了/清除/看全部" → `FilterContext.clear()`
- 非 filter 类新 query 且用户未提清除 → sticky 继续生效

---

## 10. Producer-Consumer Matrix

```
Object              Producer            Consumer
─────────────────────────────────────────────────────
DatasetProfile      Profiler            StateTransformer, Narrator
AnalysisIntent      IntentExtractor     CapabilityGate, Contract
FilterSpec          FilterSpecBuilder   validate_filter, StateTransformer
ContextualProfile   StateTransformer    Contract, ChartFactsExtractor
ChartDecision       Contract            Execution Engine
DecisionLedger      Contract            Session audit, Debug endpoint
ChartFacts          ChartFactsExtractor Narrator (LLM)
FilterContext       FilterSpecBuilder   StateTransformer
                    + Router
```

## 11. Failure Semantics Summary

| 失败点 | 行为 | 不做什么 |
|--------|------|---------|
| semantic_type 无法判定 | UNKNOWN | 不 fallback 成 text |
| UNKNOWN 传播到 temporal | 禁止 line/area | 不静默选 line |
| 列名 fuzzy match 失败 | FilterValidationError → 用户提示 | 不跳过 filter |
| df_filtered = 0 行 | ContextualProfile(row_count=0) → 提示用户 | 不画空白图 |
| x_column 或 y_columns 为空 | ChartDecision.none() → table fallback | 不强画 chart |
| Capability 不支持 | ExplicitFailure | 不让 LLM 编 |
| ChartFacts 字段无法计算 | None | 不让 LLM 猜 |
