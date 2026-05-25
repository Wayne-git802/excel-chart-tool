# Excel Chart Tool — AI 图表分析助手

智能数据分析与可视化平台。上传 Excel/CSV 文件，AI 自动理解数据语义，生成专业图表和分析洞察。

## 功能

- **AI 驱动分析**：基于 LangGraph ReAct 架构，LLM 自主规划分析步骤
- **意图保真图表选择**：ChartSelector v4.1 四阶段裁决，用户语义优先于数据适配
- **多图表类型**：折线图、柱状图、散点图、饼图、直方图、箱线图
- **智能洞察**：自动检测趋势、分布、异常、相关性
- **实时对话**：SSE 流式响应，边分析边展示

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python / FastAPI / Uvicorn |
| AI 引擎 | LangGraph / DeepSeek API |
| 图表渲染 | ECharts |
| 前端 | Alpine.js + Tailwind CSS |

## 架构

```
用户消息 → ConversationRouter → AnalysisOrchestrator → ChartSelector v4.1
                                        ↓
                              InputGate → Plan → Execute → Synthesize
```

- **ChartSelector v4.1**：4 阶段 pipeline（Intent Parser → Hard Feasibility → Intent-Preserving Resolver → Schema Scorer）
- **三层 Execution Gate**：InputGate / PlanPruner + BudgetController / ExecutionGuard

## 快速启动

```bash
pip install -r requirements.txt
python app.py
# 访问 http://127.0.0.1:8800
```

## 项目结构

```
├── app.py                 # FastAPI 入口
├── services/
│   ├── analysis_orchestrator.py  # ReAct 编排器
│   ├── chart_selector.py         # 图表类型裁决引擎
│   ├── chat_service.py           # 对话路由 + SSE 流
│   ├── chart_builder.py          # ECharts 图表生成
│   └── router/                   # 路由 + MiniChartPlanner
├── templates/
├── static/
└── tests/
```
