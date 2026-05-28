# Changelog — Excel Chart Tool V2

## 2026-05-28 ~ 2026-05-29

---

### 架构设计 — Conversational Data Runtime

**问题：** V1 是批处理管线——用户一句话，系统生成完整 Plan，执行，结束。无法响应增量式操作（"只看前三个"、"换成饼图"、"只看 2010-2015"）。

**方案：** 对话式数据操作系统。核心思路：LLM 只在两头（IntentClassifier + 未来 Narrator），中间全部确定性代码。State 是声明式 ViewSpec（操作序列），不存储 current_df。

**设计文档：** `docs/architecture-v2-phase1.md` (32KB, 19个章节)

**关键决策：**
- Operation IR: FilterOp / SortOp / LimitOp / ChartPatchOp，全部 frozen dataclass
- OpClass: APPEND（叠加）vs REPLACE（同类型只用最后一个）
- canonical_order 重排执行顺序，解决"先 limit 再 sort"语义冲突
- Backend Protocol 抽象，PandasBackend 唯一实现
- Chart 不是 State Truth，从 ViewSpec + current_df 动态计算
- IR 不含展示逻辑（human_readable 在 renderers/）
- Replay engine 不直接依赖 pandas

---

### Phase 1: 核心运行时 (13 模块, 86 测试)

**时间：** 2026-05-29 凌晨

**模块：**
```
core/v2/
├── ir/            operations, view_spec, column_info
├── engine/        replay, validator, resolver
├── backends/      base (Protocol), pandas_backend
├── renderers/     op_renderer, summary_renderer
├── state/         conversation_state
├── policies/      replay_policy
└── serialization/ ops_json
```

**测试：** `tests/v2/` — 8 个测试文件 + 1 个 property test，86/86 通过

**关键修正：**
- Python 3.11 dataclass 继承限制 — 去掉 Op 基类，每个 Op 独立定义
- `apply()` 不再删除同类型旧 op，由 canonical_order + 查询属性处理"只用最后一个"语义，保证 undo 正确性

**Git commit:** `0220dcb` — Phase 1 complete

---

### Phase 2: API 层 + LLM 集成

**时间：** 2026-05-29 上午

#### 2.1: API 端点 (`core/v2/api.py`)

**问题：** 核心模块没有 HTTP 入口，无法测试端到端。

**方案：** FastAPI router，5 个 REST 端点：
- `POST /api/v2/upload` — 上传文件，创建会话
- `POST /api/v2/sessions/{sid}/apply` — 应用操作（JSON body → Operation）
- `POST /api/v2/sessions/{sid}/undo` — 撤销最后一个操作
- `GET /api/v2/sessions/{sid}/state` — 获取当前状态
- `GET /api/v2/sessions/{sid}/chart` — 获取图表数据

**验证：** upload → filter → sort → state → chart → undo×2 → invalid reject 全链路通过

**Git commit:** `5b8b562` — Phase 2 API endpoints

#### 2.2: IntentClassifier + IntentMapper

**问题：** 用户需要通过自然语言操作数据（"只看前三个"），而非手动构造 JSON Operation。

**方案：** LLM 在两头，中间确定性：
```
用户消息 → IntentClassifier(LLM) → StructuredIntent → IntentMapper(确定性) → Operation → Validator → Apply
```

**关键设计决策：** LLM 不输出 Operation —— 只输出 StructuredIntent（raw parameters），Mapper 基于 columns profile 做精确查找。防止 LLM "编字段"、"补全逻辑"、prompt 地狱。

**新增模块：**
- `engine/intent_models.py` — StructuredIntent dataclass
- `engine/classifier.py` — DeepSeek LLM prompt + API 调用
- `engine/intent_mapper.py` — 确定性映射（parse_range_params, fuzzy column match）

**新增端点：** `POST /api/v2/sessions/{sid}/chat`

**验证：**
- "只看前三个" → LimitOp(3) ✅
- "按销售额从高到低排序" → SortOp(销售额, desc) ✅
- "换成饼图" → ChartPatchOp(pie) ✅

**Git commits:** `6f05aee` — IntentClassifier + IntentMapper; `28e86e0` — fix prompt column names

#### 2.3: 耦合修复

**问题：** Phase 1/2 之间存在 9 个耦合/重复问题。

**修复：**
1. `OP_MAP` 移到 `ir/operations.py` 为单一数据源 — ops_json.py 和 api.py 统一导入
2. api.py 移除独立 TTL 缓存 — 直接用 `load_sheet`
3. `len(df)` → `backend.row_count(df)` — 遵循 Backend abstraction
4. 补回遗漏的 `File` import

**Git commit:** `5e08e9c` — fix coupling

---

### Phase 3: 前端 V2 对话模式

**时间：** 2026-05-29 下午

**问题：** 前端只有 V1 的 SSE 聊天模式（完整分析），没有 V2 的对话式操作入口。

**方案：** 在现有 `index.html` 中添加「对话模式」切换，复用现有聊天面板和 ECharts 渲染。

**改动：**
1. 状态变量: `v2Mode`, `v2SessionId`
2. Toggle 按钮: 聊天面板标题栏的「对话模式」/「⚡对话模式」切换
3. Upload 扩展: V2 模式下同时创建 V2 session
4. `_sendV2()`: POST → `/api/v2/sessions/{sid}/chat` → 解析 JSON → 更新图表
5. `toggleV2Mode()`: 切换模式，显示帮助信息

**验证：** 浏览器加载无 JS 错误，toggle 按钮交互正常

**Git commit:** `50f564a` — Phase 3 frontend

---

### 审计 (2026-05-29)

**范围：** Phase 1-3 全量审计（8 个检查维度）

| 检查项 | 结果 |
|--------|------|
| 全量测试 | 86/86 pass |
| 模块导入 | 17/17, 无循环依赖 |
| view_spec apply/undo | 3 sorts 共存, 4次 undo 归零 |
| 前后端数据契约 | 字段完全匹配 |
| Classifier | 5种 action 覆盖, no-key 降级 |
| Mapper 边界 | 9种 null/空/溢出/不存在 全部正确处理 |
| API 错误处理 | 11种错误路径全覆盖 |
| Chat 端点 | LLM→Mapper→Validator→Apply 链完整 |

**发现：**
- 🟡 Classifier prompt 示例含具体列名 → 已修复 (28e86e0)
- 🟡 "大于1.5" 对整数列截断为 min=1 → 暂不修复（极低触发概率）

---

### 最终结果

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 核心运行时 (17模块, 86测试) | ✅ |
| Phase 2 | API层 + LLM集成 (5端点 + /chat) | ✅ |
| Phase 3 | 前端 V2 对话模式 | ✅ |

**Git 提交数：** 7 commits (ca6fc4c → 28e86e0)

**累计新增代码：** ~2,500 行 Python + ~100 行 HTML/JS

**启动命令：**
```bash
cd C:\Users\admin\Desktop\excel-chart-tool
python -B -m uvicorn app:app --host 127.0.0.1 --port 8801
```

**使用流程：**
1. 打开 http://127.0.0.1:8801
2. 点「对话模式」切换按钮
3. 上传 Excel/CSV
4. 输入自然语言：`只看前三个` `按销售额排序` `换成饼图` `只看2020年后的`
