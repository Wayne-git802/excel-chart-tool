# Excel Chart Tool — Deterministic NL-to-Chart Pipeline

An intelligent data analysis and visualization tool. Upload Excel/CSV files, describe what you want in natural language, and get charts and insights — with deterministic, reproducible results.

**Core design philosophy: LLM as Renderer, not Decision-maker.**

Most NL-to-Chart tools let LLMs freely decide chart selection and data operations. But LLMs are unreliable on structured decisions — the same input can produce different outputs, and there's no audit trail. This project takes a different approach: the LLM only understands *what* the user wants (intent), while *how* to execute it is handled by a deterministic rule engine. Same input always produces the same chart.

## Architecture

```
User Message
    │
    ▼
IntentClassifier (LLM)      → StructuredIntent  (what does the user want?)
    │
    ▼
IntentMapper (rule engine)  → Operation         (deterministic column resolution)
    │
    ▼
Validator (schema check)    → reject/accept     (reject illegal operations)
    │
    ▼
Apply (data ops + render)   → pyecharts/Plotly  (execute and render)
```

Two runtimes coexist:

| Version | Architecture | Characteristics |
|---------|-------------|-----------------|
| V1 (chat_service.py) | Bounded ReAct Agent | Max 3 reasoning steps, auto-stop at confidence >= 0.85, SSE streaming |
| V2 (core/v2/) | Deterministic pipeline | IR -> Replay -> IntentClassifier -> IntentMapper -> Validator -> Apply |

V2 is the project's core innovation — all operations are replayable, all outputs are auditable.

## Features

- **NL-to-chart**: line, bar, scatter, pie, boxplot, histogram, heatmap, bubble, funnel, treemap, scatter matrix
- **Data analysis**: automatic trend detection, correlation, distribution, outlier, and seasonality analysis
- **Deterministic chart selection**: field semantics + data structure drive chart type matching — no LLM guessing
- **Replayable operations**: all data ops (filter, sort, limit) recorded as IR with undo/redo and replay
- **SSE streaming**: real-time reasoning visibility — users see every analysis step
- **Light/Dark themes**: 6+2 color palettes

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI + Uvicorn |
| AI engine | DeepSeek API (custom ReAct + deterministic pipeline, not LangGraph) |
| Chart rendering | pyecharts (primary) + Plotly (statistical charts) |
| Data processing | pandas, openpyxl |
| Frontend | Jinja2 + Alpine.js + Tailwind CSS |
| Testing | pytest (86 test cases) |

## Quick Start

```bash
pip install -r requirements.txt
python app.py
# Open http://127.0.0.1:8801
```

Requires DeepSeek API key — set in `.env`.

### V2 API

```
POST /api/v2/upload     — Upload data file
POST /api/v2/apply      — Execute operation
POST /api/v2/undo       — Undo operation
GET  /api/v2/state      — Current session state
GET  /api/v2/chart      — Generate chart
POST /api/v2/chat       — Natural language conversation
```

## Project Structure

```
├── app.py                     # FastAPI entry point (:8801)
├── core/
│   ├── chat_service.py        # V1: Bounded ReAct Agent (1,841 lines)
│   ├── chart/
│   │   ├── builder.py         # Chart generator (pyecharts + Plotly, 767 lines)
│   │   └── selector.py        # Chart type selection engine
│   ├── routing/               # 4-level intent routing
│   ├── planning/              # PlanValidator / PlanPruner / BudgetController
│   ├── analysis/              # Trend, distribution, correlation, outlier detectors
│   ├── profiling/             # Column-level profiling (cardinality, semantics)
│   ├── narration/             # Chart caption generation
│   ├── filtering/             # Data filtering and validation
│   ├── contract/              # Contract validation layer
│   └── v2/                    # V2 deterministic pipeline
│       ├── engine/
│       │   ├── classifier.py   # IntentClassifier: LLM -> StructuredIntent
│       │   ├── intent_mapper.py # IntentMapper: deterministic column resolution
│       │   ├── validator.py    # OpValidator: schema validation
│       │   └── replay.py       # Operation replay engine
│       ├── ir/                 # Intermediate representation (Ops, ColumnInfo, ViewSpec)
│       └── backends/           # Data backends (Pandas)
├── tests/                     # 86 test cases
│   ├── v2/                    # V2 pipeline tests (determinism properties)
│   └── unit/                  # Unit tests
└── static/                    # ECharts.js + frontend assets
```

133 Python modules, 86 test cases covering the V2 pipeline's determinism properties.

## Design Philosophy

The project explores a specific thesis: **in NL-to-structured-output systems, LLMs should be constrained to semantic understanding, not operational decision-making.**

- **IntentClassifier** uses LLM for the one thing LLMs are good at: understanding what the user means
- **IntentMapper** is pure deterministic logic — column name resolution, type inference, parameter mapping
- **Validator** enforces schema constraints — no hallucinated column names, no impossible operations
- **Apply** executes the concrete operations derived from deterministic mappings

The result: given the same data and the same natural language query, the system always produces the same chart. This property (determinism) is verified by property-based tests in `tests/v2/property/test_determinism.py`.

## Relationship to ShopEase

| | ShopEase | Excel Chart Tool |
|---|---|---|
| LLM role | Agent autonomously decides actions | Renderer (intent understanding + captions only) |
| Core thesis | Multi-agent collaboration for complex tasks | Deterministic pipeline, LLM excluded from structured decisions |
| Approach | LangGraph orchestration | Custom ReAct + rule engine |

Both projects explore different sides of the same question: *when should an LLM make decisions, and when should it step aside?*
