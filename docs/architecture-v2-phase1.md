# Excel Chart Tool — V2 架构设计文档 (Phase 1)

> **Python 版本要求：** 3.10+（`X | None` 语法需要 3.10，`match/case` 需要 3.10）

## 0. 核心原则（不可违反）

1. **IR 永远不知道 UI。** Operation 不含展示相关的任何逻辑。渲染器独立存在。
2. **Replay 永远不知道 LLM。** 执行引擎是纯确定性代码。LLM 只在 Phase 2 的 IntentClassifier 中出现。
3. **Backend abstraction 尽早做。** replay engine 不直接依赖 pandas。哪怕 Phase 1 只有一个 PandasBackend。
4. **Chart 永远是 derived state。** 不是 ConversationState 的存储字段，而是从 ViewSpec + current_df 动态计算。
5. **ViewSpec 是声明式操作日志。** 不是 current state cache。current_df 是 materialize 的派生结果。

---

## 1. 目录结构

```
core/v2/
│
├── ir/                         # IR 层 — 纯数据结构，零依赖
│   ├── __init__.py
│   ├── operations.py           # Op, FilterOp, SortOp, LimitOp, ChartPatchOp, OpClass
│   ├── view_spec.py            # ViewSpec (apply, undo, 查询)
│   └── column_info.py          # ColumnInfo + extract_columns
│
├── engine/                     # 执行引擎 — 依赖 ir，不依赖 backend
│   ├── __init__.py
│   ├── replay.py               # canonical_order + replay (接收 Backend 参数)
│   ├── validator.py            # OpValidator
│   └── resolver.py             # ChartResolver (动态 chart 计算)
│
├── backends/                   # 执行后端 — 依赖 ir，不依赖 engine
│   ├── __init__.py
│   ├── base.py                 # Backend Protocol
│   └── pandas_backend.py       # PandasBackend (Phase 1 唯一实现)
│
├── renderers/                  # 渲染层 — 依赖 ir，不依赖 engine
│   ├── __init__.py
│   ├── op_renderer.py          # render_op(op, locale) → str
│   └── summary_renderer.py     # render_summary(view_spec, locale) → str
│
├── policies/                   # 全局策略 — 纯配置，零依赖
│   ├── __init__.py
│   ├── replay_policy.py        # 确定性约束 (Phase 2: groupby_sort, reset_index…)
│   └── validation_policy.py    # 校验严格度 (Phase 2)
│
├── state/                      # 会话状态 — 依赖 ir + engine
│   ├── __init__.py
│   └── conversation_state.py   # ConversationState
│
└── serialization/              # 序列化 — 依赖 ir
    ├── __init__.py
    └── ops_json.py             # ops_to_json / json_to_ops
```

**依赖方向（单向，无循环）：**

```
ir ← engine ← state
ir ← backends
ir ← renderers
ir ← serialization
policies: 零依赖，被 engine 和 state 引用
```

---

## 2. 架构总览

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────┐
│          IntentClassifier (LLM)             │  ← Phase 2
│  输入: 消息 + columns 摘要 + view_spec       │
│  输出: StructuredIntent                     │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│            OpPlanner (确定性)                │  ← Phase 2
│  StructuredIntent → [Operation, ...]         │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│           OpValidator (确定性)               │
│  validate_op(op, columns) → (ok, error)      │
│  失败 → 错误信息，state 不变                  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         ViewSpec.apply(op)                   │
│  APPEND 型 → 追加                           │
│  REPLACE 型 → 同类型覆盖                     │
│  不可变 — 返回新 ViewSpec                     │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│      canonical_order(view_spec)              │
│  filter → sort → limit（重排，确保语义正确）  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│    replay(base_df, ops, backend: Backend)    │
│  纯函数。通过 Backend 执行，不直接调 pandas   │
│  返回 current_df                             │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│   ChartResolver(current_df, view_spec)       │
│  优先 chart_preference → fallback v10        │
│  chart 是 derived，不是 stored                │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
              ChartBuilder → 渲染输出
```

---

## 3. IR 层

### 3.1 核心约束

- **Operation 不含任何展示逻辑。** 没有 `human_readable`，没有 `__str__` 重载。
- 所有字段通过 `renderers/op_renderer.py` 独立渲染，支持多 locale。
- **Operation 不可变。** 全部 `@dataclass(frozen=True)`。

### 3.2 OpClass：APPEND vs REPLACE

| OpClass | 语义 | 示例 | apply 行为 |
|---------|------|------|-----------|
| APPEND | 叠加 | FilterOp | 追加到末尾 |
| REPLACE | 同类唯一 | SortOp, LimitOp, ChartPatchOp | 移除所有同类型，追加当前 |

### 3.3 操作定义

```python
# ── ir/operations.py ─────────────────────────

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
from enum import Enum, auto
import uuid


class OpClass(Enum):
    APPEND = auto()
    REPLACE = auto()


@dataclass(frozen=True)
class Op:
    """Base class — not instantiated directly."""
    op_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    op_version: int = 1
    op_class: OpClass = OpClass.APPEND


# ── FilterOp (APPEND) ────────────────────────

@dataclass(frozen=True)
class FilterOp(Op):
    """
    Phase 1: column_range / value_match / expression。
    不做 row_slice（iloc 依赖排序，Phase 2）。
    """
    filter_type: Literal["column_range", "value_match", "expression"]
    column: str | None = None
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, 'op_class', OpClass.APPEND)


# ── SortOp (REPLACE) ─────────────────────────

@dataclass(frozen=True)
class SortOp(Op):
    column: str
    direction: Literal["asc", "desc"] = "desc"

    def __post_init__(self):
        object.__setattr__(self, 'op_class', OpClass.REPLACE)


# ── LimitOp (REPLACE) ────────────────────────

@dataclass(frozen=True)
class LimitOp(Op):
    n: int

    def __post_init__(self):
        object.__setattr__(self, 'op_class', OpClass.REPLACE)


# ── ChartPatchOp (REPLACE) ───────────────────

@dataclass(frozen=True)
class ChartPatchOp(Op):
    """
    用户图表偏好。不是最终 chart，只是 preference。
    最终 chart 由 ChartResolver 动态计算。
    """
    chart_type: str | None = None
    x_column: str | None = None
    y_columns: tuple[str, ...] | None = None
    title: str | None = None

    def __post_init__(self):
        object.__setattr__(self, 'op_class', OpClass.REPLACE)


Operation = FilterOp | SortOp | LimitOp | ChartPatchOp
```

### 3.4 Phase 2 扩展预留

| 操作 | OpClass | 延期原因 |
|------|---------|---------|
| AggregateOp | APPEND | groupby 改变数据粒度，需 DataGrain 模型 |
| ComputeOp | APPEND | 依赖图 + window function 复杂度 |
| row_slice | 待定 | 与 LimitOp 语义重叠 |

---

## 4. ViewSpec

### 4.1 数据结构

```python
# ── ir/view_spec.py ──────────────────────────

@dataclass(frozen=True)
class ViewSpec:
    """
    声明式数据视图定义。
    operations: 按用户操作历史顺序存储（用于 undo + 展示）。
    canonical_order() 在 replay 时重排执行顺序。
    两者排列不同是正常的——存储顺序 ≠ 执行顺序。
    """
    operations: tuple[Operation, ...] = ()
```

### 4.2 apply

```python
def apply(self, op: Operation) -> ViewSpec:
    if op.op_class == OpClass.APPEND:
        return ViewSpec(operations=self.operations + (op,))
    else:
        op_type = type(op)
        new_ops = tuple(
            o for o in self.operations if not isinstance(o, op_type)
        ) + (op,)
        return ViewSpec(operations=new_ops)
```

### 4.3 undo

```python
def undo(self) -> tuple[ViewSpec, Operation | None]:
    """返回 (新 ViewSpec, 被撤销的操作)。不修改自身。"""
    if not self.operations:
        return self, None

    last = self.operations[-1]

    if last.op_class == OpClass.APPEND:
        return ViewSpec(operations=self.operations[:-1]), last
    else:  # REPLACE
        op_type = type(last)
        prev = None
        for o in reversed(self.operations[:-1]):
            if isinstance(o, op_type):
                prev = o
                break
        rest = tuple(o for o in self.operations if not isinstance(o, op_type))
        if prev:
            return ViewSpec(operations=rest + (prev,)), last
        else:
            return ViewSpec(operations=rest), last
```

### 4.4 查询属性

```python
@property
def active_sort(self) -> SortOp | None:
    for op in reversed(self.operations):
        if isinstance(op, SortOp):
            return op
    return None

@property
def active_limit(self) -> LimitOp | None:
    for op in reversed(self.operations):
        if isinstance(op, LimitOp):
            return op
    return None

@property
def chart_preference(self) -> ChartPatchOp | None:
    """
    用户图表偏好，不是 final chart。
    最终 chart 由 ChartResolver 动态计算。
    """
    for op in reversed(self.operations):
        if isinstance(op, ChartPatchOp):
            return op
    return None

@property
def filters(self) -> tuple[FilterOp, ...]:
    return tuple(o for o in self.operations if isinstance(o, FilterOp))
```

### 4.5 要点

- **没有 `summary` 属性。** 展示逻辑在 `renderers/summary_renderer.py`。
- **没有 `active_chart`。** `chart_preference` 明确语义：这是 preference，不是 final chart。
- **所有查询方法都是 O(n)，n = len(operations)。** Phase 1 operations 数量小（< 20），无需优化。

---

## 5. Backend Abstraction

### 5.1 设计理由

replay engine 不直接 import pandas。所有数据操作通过 Backend 接口。未来只需实现 DuckDBBackend / PolarsBackend 即可切换执行引擎。

### 5.2 Protocol

```python
# ── backends/base.py ─────────────────────────

from typing import Protocol, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..ir.operations import FilterOp, SortOp, LimitOp


class Backend(Protocol):
    """
    数据执行后端接口。
    所有方法接收原始数据和对应的 Operation，返回处理后的数据。
    数据的具体类型由实现决定（PandasBackend → DataFrame，DuckDBBackend → Relation）。
    """

    def copy(self, data: Any) -> Any:
        """返回 data 的深副本，保证不修改原始数据。"""
        ...

    def filter(self, data: Any, op: "FilterOp") -> Any:
        """执行 FilterOp。"""
        ...

    def sort(self, data: Any, op: "SortOp") -> Any:
        """执行 SortOp。"""
        ...

    def limit(self, data: Any, op: "LimitOp") -> Any:
        """执行 LimitOp。"""
        ...

    def column_names(self, data: Any) -> list[str]:
        """返回列名列表，供 validator 使用。"""
        ...

    def row_count(self, data: Any) -> int:
        """返回行数。未来切换 DuckDB 时不依赖 len()。"""
        ...

    def column_dtype(self, data: Any, column: str) -> str:
        """
        返回列的 dtype 字符串表示。
        PandasBackend → "int64", "float64", "object", "datetime64[ns]"
        """
        ...
```

### 5.3 PandasBackend

```python
# ── backends/pandas_backend.py ───────────────

import pandas as pd
from .base import Backend
from ..ir.operations import FilterOp, SortOp, LimitOp


class PandasBackend:
    """Phase 1 唯一实现。"""

    def copy(self, data: pd.DataFrame) -> pd.DataFrame:
        return data.copy()

    def column_names(self, data: pd.DataFrame) -> list[str]:
        return list(data.columns)

    def row_count(self, data: pd.DataFrame) -> int:
        return len(data)

    def column_dtype(self, data: pd.DataFrame, column: str) -> str:
        return str(data[column].dtype)

    def filter(self, df: pd.DataFrame, op: FilterOp) -> pd.DataFrame:
        col = op.column
        if not col or col not in df.columns:
            return df

        if op.filter_type == "column_range":
            mn = op.params.get("min")
            mx = op.params.get("max")
            mask = pd.Series(True, index=df.index)
            if mn is not None:
                mask &= df[col] >= mn
            if mx is not None:
                mask &= df[col] <= mx
            return df[mask]

        if op.filter_type == "value_match":
            val = str(op.params.get("value", ""))
            if val:
                return df[df[col].astype(str).str.contains(val, na=False)]
            return df

        if op.filter_type == "expression":
            op_str = op.params.get("op")
            val = op.params.get("value")
            valid_ops = {">": "gt", "<": "lt", "==": "eq",
                         "!=": "ne", ">=": "ge", "<=": "le"}
            if op_str in valid_ops and val is not None:
                return df[getattr(df[col], valid_ops[op_str])(val)]

        return df

    def sort(self, df: pd.DataFrame, op: SortOp) -> pd.DataFrame:
        if op.column in df.columns:
            return df.sort_values(
                op.column,
                ascending=(op.direction == "asc"),
                na_position="last"
            )
        return df

    def limit(self, df: pd.DataFrame, op: LimitOp) -> pd.DataFrame:
        return df.head(op.n)
```

---

## 6. Replay Engine

### 6.1 ReplayPolicy

```python
# ── policies/replay_policy.py ────────────────

class ReplayPolicy:
    """全局确定性约束。Phase 1 只定义基础。"""
    FLOAT_PRECISION: int = 10

    # Phase 2 扩展:
    # GROUPBY_SORT: bool = False
    # RESET_INDEX: bool = True
    # FILL_NA: object = None
```

### 6.2 canonical_order

```python
# ── engine/replay.py ─────────────────────────

def canonical_order(view_spec) -> tuple:
    """
    解决 '先 limit 再 sort' 的语义冲突。

    规则:
      1. FilterOp: 按用户操作顺序
      2. SortOp: 只保留最后一个
      3. LimitOp: 只保留最后一个，总在 Sort 之后
      4. ChartPatchOp: 不放（不影响 df）

    ViewSpec.operations 保留用户操作历史（用于 undo）。
    canonical_order 只在 replay 时被调用。
    """
    from ..ir.operations import FilterOp

    result = list(view_spec.filters)

    sort = view_spec.active_sort
    if sort:
        result.append(sort)

    limit = view_spec.active_limit
    if limit:
        result.append(limit)

    return tuple(result)
```

### 6.3 replay

```python
def replay(base_data, view_spec, backend) -> Any:
    """
    纯函数。从 base 出发，通过 Backend 执行所有操作。

    不依赖 pandas — 所有数据操作通过 backend 代理。
    Phase 1 不做增量 materialize，每次完整 replay。
    """
    from ..ir.operations import FilterOp, SortOp, LimitOp

    data = backend.copy(base_data)
    ops = canonical_order(view_spec)

    for op in ops:
        if isinstance(op, FilterOp):
            data = backend.filter(data, op)
        elif isinstance(op, SortOp):
            data = backend.sort(data, op)
        elif isinstance(op, LimitOp):
            data = backend.limit(data, op)
        # ChartPatchOp: 不影响 data

    return data
```

---

## 7. OpValidator

```python
# ── engine/validator.py ──────────────────────

from ..ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp, Operation


def validate_op(op: Operation, columns: list[str]) -> tuple[bool, str | None]:
    """
    (ok, error) — ok=True 表示通过，error 可直接展示给用户。
    Phase 1: 列存在性 + 参数合法性。
    Phase 2: 依赖完整性 / 结构 barrier / chart 兼容性。
    """

    if isinstance(op, FilterOp):
        if op.column and op.column not in columns:
            return False, (
                f"列 '{op.column}' 不存在。"
                f"可用: {', '.join(columns[:10])}"
                f"{' ...' if len(columns) > 10 else ''}"
            )

    elif isinstance(op, SortOp):
        if op.column not in columns:
            return False, f"无法按 '{op.column}' 排序，该列不存在。"

    elif isinstance(op, LimitOp):
        if op.n < 0:
            return False, f"行数不能为负数: {op.n}"
        if op.n == 0:
            return False, "行数不能为 0"

    elif isinstance(op, ChartPatchOp):
        if op.x_column and op.x_column not in columns:
            return False, f"X 轴列 '{op.x_column}' 不存在"
        if op.y_columns:
            missing = [c for c in op.y_columns if c not in columns]
            if missing:
                return False, f"Y 轴列 {missing} 不存在"

    return True, None
```

**错误处理：** validate 失败 → state 不变 → error 返回用户。

---

## 8. ChartResolver

```python
# ── engine/resolver.py ───────────────────────

def resolve_chart(current_df, view_spec, columns_info: list[dict]) -> dict:
    """
    动态计算最终 chart 配置。

    优先级:
      1. chart_preference（如果合法）
      2. v10 contract 推断
      3. 安全默认值

    chart 不是 ConversationState 的存储字段。
    """
    preference = view_spec.chart_preference

    if preference and preference.chart_type:
        x = preference.x_column
        y = list(preference.y_columns) if preference.y_columns else []

        if not x and len(current_df.columns) > 0:
            x = current_df.columns[0]
        if not y and len(current_df.columns) > 1:
            y = [current_df.columns[1]]

        # 验证合法性
        df_cols = list(current_df.columns)
        if x and x in df_cols and y and all(c in df_cols for c in y):
            return {
                "chart_type": preference.chart_type,
                "x_column": x,
                "y_columns": y,
                "title": preference.title or "",
                "source": "preference",
                "degraded": False,
            }
        # 不合法 → 降级
        return _v10_fallback(current_df, columns_info, degraded=True)

    # 无 preference → v10 contract
    return _v10_fallback(current_df, columns_info, degraded=False)


def _v10_fallback(current_df, columns_info: list[dict], degraded: bool) -> dict:
    """
    Phase 1: 简单默认逻辑。
    Phase 2: 接入 v10 contract。
    """
    cols = list(current_df.columns)
    if len(cols) >= 2:
        return {
            "chart_type": "bar",
            "x_column": cols[0],
            "y_columns": [cols[1]],
            "title": "",
            "source": "v10_fallback",
            "degraded": degraded,
        }
    return {
        "chart_type": "table",
        "x_column": None,
        "y_columns": [],
        "title": "",
        "source": "fallback",
        "degraded": degraded,
    }
```

---

## 9. Renderers（展示层）

### 9.1 op_renderer

```python
# ── renderers/op_renderer.py ─────────────────

def render_op(op, locale: str = "zh") -> str:
    """
    将 Operation 渲染为人类可读字符串。
    locale 用于 Phase 2 多语言支持。
    IR 不知道 UI——所有展示逻辑在此。
    """
    from ..ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp

    if isinstance(op, FilterOp):
        return _render_filter(op)
    if isinstance(op, SortOp):
        direction = "升序" if op.direction == "asc" else "降序"
        return f"按 {op.column} {direction}"
    if isinstance(op, LimitOp):
        return f"仅显示前 {op.n} 条"
    if isinstance(op, ChartPatchOp):
        parts = []
        if op.chart_type:
            parts.append(f"图表: {op.chart_type}")
        if op.x_column:
            parts.append(f"X: {op.x_column}")
        if op.y_columns:
            parts.append(f"Y: {', '.join(op.y_columns)}")
        return " / ".join(parts) if parts else "图表配置变更"
    return str(op)


def _render_filter(op) -> str:
    if op.filter_type == "column_range":
        mn = op.params.get("min", "")
        mx = op.params.get("max", "")
        return f"{op.column}: {mn} ~ {mx}"
    if op.filter_type == "value_match":
        return f"{op.column} 包含 '{op.params.get('value', '')}'"
    if op.filter_type == "expression":
        return f"{op.column} {op.params.get('op', '')} {op.params.get('value', '')}"
    return ""
```

### 9.2 summary_renderer

```python
# ── renderers/summary_renderer.py ────────────

def render_summary(view_spec, locale: str = "zh") -> str:
    """前端状态栏的视图摘要。"""
    from .op_renderer import render_op

    parts = []
    for f in view_spec.filters:
        parts.append(render_op(f, locale))
    if view_spec.active_sort:
        parts.append(render_op(view_spec.active_sort, locale))
    if view_spec.active_limit:
        parts.append(render_op(view_spec.active_limit, locale))
    if view_spec.chart_preference:
        parts.append(render_op(view_spec.chart_preference, locale))
    return " → ".join(parts) if parts else "原始数据"
```

---

## 10. ConversationState

```python
# ── state/conversation_state.py ──────────────

from dataclasses import dataclass, field
from ..ir.view_spec import ViewSpec


@dataclass
class ConversationState:
    session_id: str
    file_key: str                       # base_df 的文件路径 / 缓存 key
    view_spec: ViewSpec = field(default_factory=ViewSpec)

    # 注意：没有 current_df, chart_spec 字段
    # current_df = replay(base_df, view_spec, backend)
    # chart      = resolve_chart(current_df, view_spec, columns_info)

    def materialize(self, base_data, backend):
        """纯 replay，用于内部测试 / 调试。"""
        from ..engine.replay import replay
        return replay(base_data, self.view_spec, backend)

    # to_frontend_state → 见 §16 修正版
    # apply_operation    → 见 §13 Orchestrator
    # undo_operation     → 见 §13 Orchestrator
```

**注意：** `to_frontend_state`、`apply_operation`、`undo_operation` 的完整实现在 §13 和 §16。

---

## 11. 序列化

```python
# ── serialization/ops_json.py ────────────────

import json
from ..ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp, Operation

_OP_MAP = {
    "FilterOp": FilterOp,
    "SortOp": SortOp,
    "LimitOp": LimitOp,
    "ChartPatchOp": ChartPatchOp,
}

_OPS_BY_TYPE = {v: k for k, v in _OP_MAP.items()}

_SKIP_FIELDS = {"op_id", "op_version", "op_class"}


def ops_to_json(ops: tuple[Operation, ...]) -> str:
    items = []
    for op in ops:
        d = {"type": _OPS_BY_TYPE[type(op)]}
        for field_name in op.__dataclass_fields__:
            if field_name in _SKIP_FIELDS:
                continue
            val = getattr(op, field_name)
            if isinstance(val, tuple):
                val = list(val)
            d[field_name] = val
        items.append(d)
    return json.dumps(items, ensure_ascii=False, indent=2)


def json_to_ops(j: str) -> tuple[Operation, ...]:
    items = json.loads(j)
    ops = []
    for item in items:
        cls = _OP_MAP[item.pop("type")]
        if "y_columns" in item and isinstance(item["y_columns"], list):
            item["y_columns"] = tuple(item["y_columns"])
        ops.append(cls(**item))
    return tuple(ops)
```

**Round-trip 要求（property test 验证）：**
```
ops → JSON → ops'
replay(base, view_with_ops, backend) == replay(base, view_with_ops', backend)
```

---

## 12. ColumnInfo（列元数据）

```python
# ── ir/column_info.py ────────────────────────

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnInfo:
    """
    列元数据。从 base_df 提取一次，后续 validate / resolve 都使用它。
    不存储在 ConversationState 中（因为 base_df 不变，columns 不变）。
    """
    name: str                # 列名
    dtype: str               # pandas dtype: "int64", "float64", "object", "datetime64[ns]"
    dtype_cn: str            # 中文: "整数", "小数", "文本", "日期"


def extract_columns(base_data, backend) -> list[ColumnInfo]:
    """
    从 base_data 提取列信息。
    上传文件后调用一次，结果在整个 session 生命周期内不变。
    Phase 1: 基于 pandas dtype 做简单映射。
    Phase 2: 接入 DataProfiler 做更丰富的语义推断。
    """
    import numpy as np

    dtype_cn_map = {
        "int": "整数",
        "float": "小数",
        "object": "文本",
        "datetime": "日期",
        "bool": "布尔",
    }

    result = []
    for name in backend.column_names(base_data):
        raw = backend.column_dtype(base_data, name)
        cn = "文本"
        for key, label in dtype_cn_map.items():
            if key in raw.lower():
                cn = label
                break
        result.append(ColumnInfo(name=name, dtype=raw, dtype_cn=cn))
    return result
```

**关键约定：** columns 信息只在初始化时提取一次。因为 Phase 1 没有 AggregateOp（不改 schema），所以后续 columns 永远不变。

---

## 13. Orchestrator（操作入口）

单个操作和撤销操作需要把 validate → apply → replay → resolve → render 串起来。
以下是 ConversationState 上的两个编排方法：

```python
# ── 在 state/conversation_state.py 中 ──────

def apply_operation(
    self,
    op: Operation,
    base_data,
    columns_info: list[ColumnInfo],
    backend,
) -> dict:
    """
    完成一次操作的完整流程。
    
    返回:
        {
            "ok": True/False,
            "error": str | None,
            "state": {...},  # 仅 ok=True 时，to_frontend_state 的结果
        }
    """
    from ..engine.validator import validate_op
    from ..renderers.op_renderer import render_op

    # 1. validate — 用 base 的列信息（因为 Phase 1 无 AggregateOp）
    col_names = [c.name for c in columns_info]
    ok, error = validate_op(op, col_names)
    if not ok:
        return {"ok": False, "error": error, "state": None}

    # 2. apply — state 是唯一被修改的
    self.view_spec = self.view_spec.apply(op)

    # 3. replay + resolve + render
    state = self.to_frontend_state(base_data, columns_info, backend)
    state["last_action"] = render_op(op)
    state["ok"] = True

    return state


def undo_operation(
    self,
    base_data,
    columns_info: list[ColumnInfo],
    backend,
) -> dict:
    """
    撤销最后一个操作。
    
    返回:
        {
            "ok": True/False,
            "removed": str | None,  # 被撤销操作的描述
            "state": {...},
        }
    """
    from ..renderers.op_renderer import render_op

    if not self.view_spec.operations:
        return {"ok": False, "removed": None, "error": "没有可撤销的操作", "state": None}

    new_spec, removed = self.view_spec.undo()
    self.view_spec = new_spec

    state = self.to_frontend_state(base_data, columns_info, backend)
    state["removed"] = render_op(removed) if removed else None
    state["ok"] = True

    return state
```

---

## 14. Session 初始化流程

```python
# ── 在 state/conversation_state.py 或独立 app 层 ──

import uuid
from ..ir.view_spec import ViewSpec
from ..ir.column_info import extract_columns


def create_session(file_key: str, base_data, backend) -> dict:
    """
    上传文件后创建新 session。
    
    file_key 用于后续从缓存取 base_data。
    
    返回:
        {
            "session_id": "...",
            "columns": [...],
            "total_rows": N,
        }
    """
    state = ConversationState(
        session_id=uuid.uuid4().hex[:16],
        file_key=file_key,
        view_spec=ViewSpec(),
    )

    columns = extract_columns(base_data, backend)

    return {
        "session_id": state.session_id,
        "columns": [
            {"name": c.name, "dtype": c.dtype, "dtype_cn": c.dtype_cn}
            for c in columns
        ],
        "total_rows": backend.row_count(base_data),
    }
```

**缓存规则：** `create_session` 返回 session_id，调用方把 `(file_key, base_data, columns_info, ConversationState)` 存入内存 dict。后续请求通过 session_id 找到这些对象。

---

## 15. API 端点定义（Phase 1 测试用）

相位 1 不需要完整前端，但需要 REST API 来手动测试和验证。

### 15.1 端点一览

```
POST   /api/v2/upload          # 上传文件 → 创建 session
POST   /api/v2/sessions/{sid}/apply    # 应用一个操作
POST   /api/v2/sessions/{sid}/undo     # 撤销最后一个操作  
GET    /api/v2/sessions/{sid}/state    # 获取当前状态
GET    /api/v2/sessions/{sid}/chart    # 获取渲染后的图表数据
```

### 15.2 请求/响应格式

**POST /api/v2/upload**
```
Request: multipart/form-data, file=<excel/csv>
Response 200:
{
    "session_id": "a1b2c3d4",
    "columns": [{"name": "日期", "dtype": "datetime64[ns]", "dtype_cn": "日期"}, ...],
    "total_rows": 5000
}
```

**POST /api/v2/sessions/{sid}/apply**
```
Request: application/json
{
    "op": {
        "type": "FilterOp",
        "filter_type": "column_range",
        "column": "年份",
        "params": {"min": 2010, "max": 2015}
    }
}
Response 200:
{
    "ok": true,
    "error": null,
    "last_action": "年份: 2010 ~ 2015",
    "row_count": 342,
    "total_rows": 5000,
    "active_filters": [...],
    "sort": null,
    "chart": {...},
    "operations": [...],
    "view_summary": "年份: 2010 ~ 2015",
    "can_undo": true
}
Response 400 (validation failed):
{
    "ok": false,
    "error": "列 '年份' 不存在。可用: 日期, 销售额, 品类",
    "state": null
}
```

**POST /api/v2/sessions/{sid}/undo**
```
Request: (empty body)
Response 200:
{
    "ok": true,
    "removed": "年份: 2010 ~ 2015",
    "row_count": 5000,
    "total_rows": 5000,
    "active_filters": [],
    "operations": [],
    "view_summary": "原始数据",
    "can_undo": false
}
```

**GET /api/v2/sessions/{sid}/state**
```
Response 200:
{
    "session_id": "a1b2c3d4",
    "row_count": 342,
    "total_rows": 5000,
    "columns": [...],
    "active_filters": [...],
    "sort": null,
    "limit": null,
    "chart": {...},
    "view_summary": "年份: 2010 ~ 2015",
    "operations": [...],
    "can_undo": true
}
```

### 15.3 错误响应统一格式

所有端点返回：
```json
{
    "ok": false,
    "error": "人类可读的中文错误信息",
    "error_code": "COLUMN_NOT_FOUND"  // Phase 2
}
```

---

## 16. 修正 to_frontend_state

### 16.1 修正后的代码

```python
def to_frontend_state(
    self,
    base_data,
    columns_info: list[ColumnInfo],
    backend,
) -> dict:
    """
    转为前端 JSON。
    
    关键：不直接从 df 读 dtype（那是 pandas 细节），
    而是从 columns_info 取。
    """
    from ..engine.replay import replay
    from ..engine.resolver import resolve_chart
    from ..renderers.summary_renderer import render_summary
    from ..renderers.op_renderer import render_op

    df = replay(base_data, self.view_spec, backend)
    chart = resolve_chart(df, self.view_spec, columns_info)

    return {
        "session_id": self.session_id,
        "row_count": backend.row_count(df),
        "total_rows": backend.row_count(base_data),
        "columns": [
            {"name": c.name, "dtype": c.dtype, "dtype_cn": c.dtype_cn}
            for c in columns_info
        ],
        "active_filters": [
            {
                "op_id": f.op_id,
                "type": f.filter_type,
                "column": f.column,
                "params": f.params,
                "label": render_op(f),
            }
            for f in self.view_spec.filters
        ],
        # 完整操作历史（供前端展示 + undo UI）
        "operations": [
            {
                "op_id": op.op_id,
                "type": type(op).__name__,
                "label": render_op(op),
            }
            for op in self.view_spec.operations
        ],
        "sort": {
            "column": s.column,
            "direction": s.direction,
        } if (s := self.view_spec.active_sort) else None,
        "limit": self.view_spec.active_limit.n if self.view_spec.active_limit else None,
        "chart": chart,
        "view_summary": render_summary(self.view_spec),
        "can_undo": len(self.view_spec.operations) > 0,
    }
```

### 16.2 注意事项

- **columns 字段：** 直接使用 `columns_info`，不从 `df` 重新读。因为 Phase 1 没有 AggregateOp，schema 不变。
- **Phase 2 警告：** AggregateOp 加入后，`columns_info` 不能直接用——它代表 base_df 的 schema，而 current_df 的 schema 可能因 groupby 改变。届时需要 `projected_schema(columns_info, view_spec)` 动态计算。
- **chart 数据：** `resolve_chart` 只返回图表配置（类型/轴/标题），不返回实际的 Plotly spec。前端需要调 `/api/v2/sessions/{sid}/chart` 获取渲染数据。

---

## 17. Phase 1 范围

### 实现模块（8 个）

| 模块 | 文件 | 职责 |
|------|------|------|
| Operations | `ir/operations.py` | 4 种 Op + OpClass |
| ColumnInfo | `ir/column_info.py` | 列元数据 + extract_columns |
| ViewSpec | `ir/view_spec.py` | apply, undo, 查询属性 |
| Backend base | `backends/base.py` | Backend Protocol (含 row_count, column_dtype) |
| PandasBackend | `backends/pandas_backend.py` | filter/sort/limit + row_count + column_dtype |
| Replay | `engine/replay.py` | canonical_order + replay |
| Validator | `engine/validator.py` | validate_op |
| Resolver | `engine/resolver.py` | resolve_chart |

### 辅助模块（5 个）

| 模块 | 文件 | 职责 |
|------|------|------|
| Serialization | `serialization/ops_json.py` | ops ↔ JSON |
| OpRenderer | `renderers/op_renderer.py` | render_op |
| SummaryRenderer | `renderers/summary_renderer.py` | render_summary |
| ConversationState | `state/conversation_state.py` | state 管理 + apply_operation + undo_operation + create_session + to_frontend_state |
| ReplayPolicy | `policies/replay_policy.py` | 确定性约束 |

### 不实现

| 内容 | 原因 |
|------|------|
| IntentClassifier (LLM) | Phase 2 |
| OpPlanner | Phase 2 |
| AggregateOp | 需 DataGrain |
| ComputeOp | 需 dependency graph |
| SemanticFocus | Phase 3 |
| 增量 materialize | Phase 3 |
| 前端对接 | Phase 3 |
| DuckDBBackend | Phase 2+ |

---

## 18. 测试清单

### 单元测试

| # | 文件 | 测试 | 预期 |
|---|------|------|------|
| T1 | test_operations.py | Op 创建 + frozen | 不可修改 |
| T2 | test_operations.py | OpClass 正确 | 4 种 Op 的 op_class |
| T3 | test_view_spec.py | FilterOp apply 叠加 | 2 个 filter 都保留 |
| T4 | test_view_spec.py | SortOp apply 覆盖 | 只有最后一个生效 |
| T5 | test_view_spec.py | LimitOp apply 覆盖 | 只有最后一个生效 |
| T6 | test_view_spec.py | undo FilterOp | 移除最后一个 |
| T7 | test_view_spec.py | undo SortOp (有 prev) | 恢复上一个 SortOp |
| T8 | test_view_spec.py | undo SortOp (无 prev) | 完全移除 SortOp |
| T9 | test_view_spec.py | undo LimitOp | 恢复或移除 |
| T10 | test_view_spec.py | view_spec 不可变 | apply 返回新实例，原不变 |
| T11 | test_replay.py | FilterOp column_range | 正确过滤 |
| T12 | test_replay.py | FilterOp value_match | 模糊匹配 |
| T13 | test_replay.py | FilterOp expression | 数值比较 |
| T14 | test_replay.py | 多个 FilterOp 叠加 | 两个条件同时生效 |
| T15 | test_replay.py | SortOp | 正确排序 |
| T16 | test_replay.py | LimitOp | df 只剩 N 行 |
| T17 | test_replay.py | Limit→Sort (重排) | top N 正确 |
| T18 | test_replay.py | Sort→Limit | top N 正确 |
| T19 | test_replay.py | ChartPatchOp 不影响 df | df 不变 |
| T20 | test_replay.py | canonical_order 重排 | filter→sort→limit |
| T21 | test_validator.py | 拦截不存在的列 | 返回 error |
| T22 | test_validator.py | 拦截 negative limit | 返回 error |
| T23 | test_validator.py | 拦截 limit=0 | 返回 error |
| T24 | test_validator.py | 合法 op 通过 | 返回 ok |
| T25 | test_resolver.py | chart_preference 生效 | source="preference" |
| T26 | test_resolver.py | preference 不合法降级 | degraded=true |
| T27 | test_resolver.py | 无 preference 回退 v10 | source="v10_fallback" |
| T28 | test_serialization.py | ops→JSON→ops | 反序列化后类型一致 |
| T29 | test_conversation_state.py | to_frontend_state 格式 | 字段完整，无 pandas dtype |
| T30 | test_column_info.py | extract_columns | dtype 映射正确 |
| T31 | test_conversation_state.py | apply_operation 成功 | state 更新 + 返回 ok |
| T32 | test_conversation_state.py | apply_operation 验证失败 | state 不变 + 返回 error |
| T33 | test_conversation_state.py | undo_operation 成功 | 回到上一步 state |
| T34 | test_conversation_state.py | undo_operation 空 ops | 返回 error |
| T35 | test_conversation_state.py | create_session | session_id + columns + total_rows |

### Property Tests（关键）

| # | 测试 | 预期 |
|---|------|------|
| P1 | `replay(df, v1, b) == replay(df, v2, b)` 其中 v2.ops = deserialize(serialize(v1.ops)) | determinism |
| P2 | REPLACE 型 undo(apply(state, op)) → materialize 与原始 state 一致 | undo 正确（无 prev 时） |
| P3 | REPLACE 型 undo(apply(apply(state, sortA), sortB)) → materialize 与 apply(state, sortA) 一致 | undo 恢复上一个（有 prev 时） |
| P4 | 任意顺序 sort+limit → canonical_order 后 → replay 结果一致 | 重排确定性 |
| P5 | 多次 apply + undo 后 operations 为空 → materialize 返回原始 base | 完整回退 |

---

## 19. 关键约束与注意事项

### 19.1 current_df 是派生值

**永远不要** 在 ConversationState 上存 `current_df` 字段。每次需要时调用 `replay(base_data, view_spec, backend)`。

### 19.2 Immutable 不可商量

ViewSpec 和 Operation 全部 frozen。apply/undo 返回新实例。这是 undo/redo 正确性的保证。

### 19.3 存储顺序 ≠ 执行顺序

`view_spec.operations` = 用户操作历史（用于 undo + 展示）。`canonical_order(view_spec)` = 执行顺序（用于 replay）。两者不同，这是设计意图。

### 19.4 base_df 生命周期

- 上传 → 缓存到内存（`file_key` → DataFrame）
- TTL 1 小时
- 大文件（>200MB）——TODO：parquet 持久化

### 19.5 版本化

`Op.op_version = 1`。反序列化时不检查版本（Phase 1 硬编码）。Phase 2 增加 migration。

### 19.6 新旧路径共存

```
/api/v2/...              → v2 对话式（本架构）
/api/chat/analyze       → v1 批处理（现有）
```

`core/v2/` 独立目录，不修改现有代码。

### 19.7 IR 分层原则

- `ir/` 不能 import `engine/`、`backends/`、`renderers/`
- `engine/` 可以 import `ir/`，不能 import `backends/`（通过 Protocol 反转依赖）
- `backends/` 可以 import `ir/`
- `renderers/` 可以 import `ir/`
- `state/` 可以 import `ir/`、`engine/`、`backends/`、`renderers/`、`policies/`
- `policies/` 不依赖任何模块

---

*最后更新：2026-05-29*
*Phase 1 目标：验证 replay-based conversational manipulation 交互模型。*
