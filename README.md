# Excel Chart Tool — Deterministic NL-to-Chart Pipeline

智能数据分析与可视化工具。上传 Excel/CSV，用自然语言生成图表和分析洞察。核心设计主张：**LLM 是 Renderer，不是 Decision-maker**——图表选择与数据操作由确定性流水线完成，LLM 仅负责意图理解和文案生成。

## 设计哲学

大多数 NL-to-Chart 工具让 LLM 自由推理图表选择和数据操作，但 LLM 在结构化决策上不可靠——同样的输入可能产生不同的输出，且无法审计。

本项目的核心思路是 **IntentClassifier → IntentMapper（确定性）→ Validator → Apply** 流水线。LLM 只做它擅长的事（理解用户想干什么），而把「怎么干」交给确定性的规则引擎。结果是：**同样的输入，永远产生同样的图表**。

## 架构

```
用户消息 → IntentClassifier (LLM)       → StructuredIntent
                ↓
         IntentMapper (规则引擎)          → 确定性的列名解析
                ↓
         Validator (schema校验)           → 拒绝非法操作
                ↓
         Apply (数据操作 + 图表渲染)       → pyecharts/Plotly 输出
```

两套运行时并存：

| 版本 | 架构 | 特点 |
|------|------|------|
| V1 (chat_service.py) | Bounded ReAct Agent | 最大3步推理，置信度≥0.85自动停止，SSE流式 |
| V2 (core/v2/) | 确定性流水线 | IR → Replay → IntentClassifier → IntentMapper → Validator → Apply |

V2 是整个项目的核心——所有操作序列可回放（Replay），所有输出可审计。

## 功能

- **自然语言生成图表**：折线图、柱状图、散点图、饼图、箱线图、直方图、热力图、气泡图、漏斗图、矩形树图、散点矩阵
- **智能数据分析**：自动检测趋势、相关性、分布形态、异常值、季节性
- **确定性图表选择**：基于字段语义和数据结构自动匹配图表类型，不依赖LLM猜测
- **操作可回放**：所有数据操作（筛选、排序、限制）记录为 IR，支持 und/redo 和重放
- **实时流式响应**：SSE 推送分析过程，用户可观察每一步推理
- **Light/Dark 主题**：6+2 套配色方案

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn |
| AI 引擎 | DeepSeek API（自实现 ReAct / 确定性流水线，非 LangGraph） |
| 图表渲染 | pyecharts（主力）+ Plotly（统计图补充） |
| 数据处理 | pandas, openpyxl |
| 前端 | Jinja2 模板 + Alpine.js + Tailwind CSS |
| 测试 | pytest（86 个测试用例） |

## 快速启动

```bash
pip install -r requirements.txt
python app.py
# 访问 http://127.0.0.1:8801
```

需要 DeepSeek API Key，在 `.env` 中配置。

### V2 API

```
POST /api/v2/upload     — 上传数据文件
POST /api/v2/apply      — 执行操作
POST /api/v2/undo       — 撤销操作
GET  /api/v2/state      — 当前会话状态
GET  /api/v2/chart      — 生成图表
POST /api/v2/chat       — 自然语言对话
```

## 项目结构

```
├── app.py                     # FastAPI 入口（:8801）
├── core/
│   ├── chat_service.py        # V1: Bounded ReAct Agent（1841行）
│   ├── chart/
│   │   ├── builder.py         # 图表生成器（pyecharts + Plotly, 767行）
│   │   └── selector.py        # 图表类型选择引擎
│   ├── routing/
│   │   ├── router.py          # 四级意图路由
│   │   ├── intent_extractor.py # LLM 意图提取
│   │   └── gate.py            # 能力门控
│   ├── planning/              # PlanValidator / PlanPruner / BudgetController
│   ├── analysis/              # 趋势、分布、异常、相关性检测
│   ├── profiling/             # 列级数据分析（cardinality, distribution, semantics）
│   ├── narration/             # 图表文案生成
│   ├── filtering/             # 数据筛选与校验
│   ├── contract/              # 合约校验层
│   └── v2/                    # V2 确定性流水线
│       ├── engine/
│       │   ├── classifier.py   # IntentClassifier: LLM → StructuredIntent
│       │   ├── intent_mapper.py # IntentMapper: 确定性列名解析
│       │   ├── validator.py    # OpValidator: schema校验
│       │   └── replay.py       # 操作回放引擎
│       ├── ir/                 # 中间表示（Operations, ColumnInfo, ViewSpec）
│       └── backends/           # 数据处理后端（Pandas）
├── tests/                     # 86 个测试用例
│   ├── v2/                    # V2 pipeline 测试
│   └── unit/                  # 单元测试
└── static/                    # ECharts.js + 前端资源
```

133 个 Python 模块，86 个测试用例，覆盖 V2 流水线的确定性属性。

## 与 ShopEase 的区别

| | ShopEase | Excel Chart Tool |
|---|---|---|
| LLM 角色 | Agent 自主决策 | Renderer（仅意图理解 + 文案） |
| 核心主张 | 多 Agent 协作完成复杂任务 | 确定性流水线，LLM 不做结构化决策 |
| 技术路线 | LangGraph 编排 | 自实现 ReAct + 规则引擎 |

两个项目共享同一个技术哲学的不同侧面：**什么时候该用 LLM，什么时候不该用**。
