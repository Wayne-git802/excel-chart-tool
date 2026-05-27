# System Invariants — Never-Violate Rules

> 本文档定义系统永远不能违反的规则。所有代码变更、重构、新功能必须过这些检查。
> 违反任何一条 = 架构退化，必须立即修复。

---

## I. LLM Boundary

| # | Invariant | 验证方式 |
|---|-----------|---------|
| I-1 | LLM 永远不直接读取 df | grep `df` in narrator.py/intent_extractor.py 的 LLM prompt |
| I-2 | LLM 永远不决定 chart_type | chart_type 只从 Contract DecisionLedger 产出 |
| I-3 | LLM 只做两件事：生成 FilterSpec + 生成 Narration | 其他任何 LLM 输出 → 违规 |
| I-4 | LLM 的 Narration prompt 必须以 "以下是已计算好的事实…不要推断" 开头 | 字符串匹配 |

---

## II. Contract Purity

| # | Invariant | 验证方式 |
|---|-----------|---------|
| II-1 | Contract 永远不访问 df | Contract 模块禁止 `import pandas` |
| II-2 | Contract 永远不读 LLM 叙事 | Contract 输入只有 ContextualProfile + AnalysisIntent |
| II-3 | Contract 规则声明式、优先级排序、每条规则有 `because` | 所有 chart 决策路径可追溯到具体规则 |
| II-4 | Contract 输出总是 ChartDecision 或被拒绝 | 不存在 "LLM 建议覆盖 Contract" 的路径 |

---

## III. Profile Immutability

| # | Invariant | 验证方式 |
|---|-----------|---------|
| III-1 | DatasetProfile 生成后全程只读 | frozen dataclass |
| III-2 | Profile 不做数据解释/建议 | DatasetProfile 不含 insights/suggested_analyses 字段 |
| III-3 | semantic_type 只能由 Profiler 设定 | 搜索 `semantic_type =` 只出现在 profiler.py |
| III-4 | Profile version + hash 不可变 | 生成后再修改 → 违规 |

---

## IV. State Integrity

| # | Invariant | 验证方式 |
|---|-----------|---------|
| IV-1 | 所有状态转换是 total + explicit | State + Input → State OR ExplicitFailure |
| IV-2 | 不允许 silent fallback | 任何 fallback 必须写入 DecisionLedger |
| IV-3 | FilterContext 的状态转换是确定性的 | LLM 不能清除/修改 FilterContext |
| IV-4 | 空 df（filter 后 0 行）必须显式提示用户 | 不能画空白图 |

---

## V. Execution Determinism

| # | Invariant | 验证方式 |
|---|-----------|---------|
| V-1 | 相同 (profile, intent, filter) → 相同 ChartDecision | Replay test |
| V-2 | Execution 层不做决策 | chart_builder 不选 type、不挑列 |
| V-3 | 所有决策路径可审计 | DecisionLedger 写入 session |

---

## VI. Capability Boundary

| # | Invariant | 验证方式 |
|---|-----------|---------|
| VI-1 | 不支持的 capability 必须短路在 Router 层 | 不进入 IntentExtractor (LLM) |
| VI-2 | CapabilityGate Layer A（规则）先于 Layer B（LLM intent 校验） | 代码顺序 |
| VI-3 | 不支持的能力返回 ExplicitFailure，不让 LLM 编 | 响应格式固定 |

---

## VII. IR Serialization

| # | Invariant | 验证方式 |
|---|-----------|---------|
| VII-1 | 所有 IR 对象有 to_dict() 和 from_dict() | Phase 0 序列化测试 |
| VII-2 | to_dict 输出可 JSON 序列化 | json.dumps 不抛异常 |
| VII-3 | to_dict → from_dict 往返一致 | roundtrip test |

## VIII. Orchestrator Purity

| # | Invariant | 验证方式 |
|---|-----------|---------|
| VIII-1 | Orchestrator 只传 IR，不解释 IR | 禁止 if chart_type / if intent 分支 |
| VIII-2 | Orchestrator 不做 fallback 决策 | fallback 只在 Contract/Executor 层 |
| VIII-3 | Orchestrator 不含业务规则 | 所有 if 只能是 pipeline routing (fact_query vs chart_query) |
