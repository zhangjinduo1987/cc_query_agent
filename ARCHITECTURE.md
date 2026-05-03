# 问数分析智能体 — 完整代码流程说明

> 版本：v1.0.0 | 更新日期：2026-05-03

---

## 目录

1. [整体架构](#1-整体架构)
2. [目录结构](#2-目录结构)
3. [启动流程](#3-启动流程)
4. [完整请求生命周期](#4-完整请求生命周期)
5. [模块详解：agent/](#5-模块详解agent)
6. [模块详解：mcp_server/](#6-模块详解mcp_server)
7. [模块详解：api/](#7-模块详解api)
8. [模块详解：frontend/](#8-模块详解frontend)
9. [Python 与 Claude Code 交互原理](#9-python-与-claude-code-交互原理)
10. [MCP 协议工作原理](#10-mcp-协议工作原理)
11. [数据流转图](#11-数据流转图)
12. [关键设计决策](#12-关键设计决策)
13. [扩展指南](#13-扩展指南)

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         整体分层架构                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   浏览器 / 客户端                                                      │
│   ┌────────────────────────────────────┐                             │
│   │  frontend/src/index.html           │                             │
│   │  ├── 输入框（自然语言 Query）         │                             │
│   │  ├── WebSocket 实时流接收            │                             │
│   │  └── Markdown 报告渲染              │                             │
│   └──────────────┬─────────────────────┘                             │
│                  │ HTTP / WebSocket                                   │
│   ┌──────────────▼─────────────────────┐                             │
│   │  api/  FastAPI 后端                 │                             │
│   │  ├── main.py   启动 & MCP配置生成   │                             │
│   │  ├── routes.py REST + WS 路由       │                             │
│   │  └── models.py Pydantic 数据模型    │                             │
│   └──────────────┬─────────────────────┘                             │
│                  │ Python async call                                  │
│   ┌──────────────▼─────────────────────┐                             │
│   │  agent/  Claude Code Agent          │                             │
│   │  ├── agent.py   subprocess 交互核心  │                             │
│   │  ├── planner.py 任务拆解规划         │                             │
│   │  └── prompts.py Prompt 模板管理     │                             │
│   └──────────────┬─────────────────────┘                             │
│                  │ subprocess + stdin/stdout                          │
│   ┌──────────────▼─────────────────────┐                             │
│   │  Claude Code CLI 进程               │                             │
│   │  (claude --output-format stream-json│                             │
│   │   --mcp-config mcp_config.json)     │                             │
│   └──────────────┬─────────────────────┘                             │
│                  │ MCP Protocol (stdio JSON-RPC)                      │
│   ┌──────────────▼─────────────────────┐                             │
│   │  mcp_server/  数据工具层             │                             │
│   │  ├── server.py    MCP Server 主入口  │                             │
│   │  └── db_tools.py  工具函数实现        │                             │
│   │      ├── query_database  SQL取数     │                             │
│   │      ├── get_schema      表结构探索  │                             │
│   │      └── run_analysis    Python分析  │                             │
│   └──────────────┬─────────────────────┘                             │
│                  │ SQLAlchemy                                         │
│   ┌──────────────▼─────────────────────┐                             │
│   │  数据库层                            │                             │
│   │  SQLite (demo) / PostgreSQL (生产)  │                             │
│   └─────────────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 目录结构

```
cc_query_agent/
│
├── agent/                        # Claude Code Agent 核心层
│   ├── __init__.py
│   ├── agent.py                  # ClaudeCodeAgent 类：subprocess 交互 + stream-json 解析
│   ├── planner.py                # TaskPlanner 类：Query → DAG 任务拆解
│   └── prompts.py                # 所有 Prompt 字符串集中管理
│
├── mcp_server/                   # MCP 数据工具服务层
│   ├── __init__.py
│   ├── server.py                 # MCP Server 主入口（stdio 协议）
│   └── db_tools.py               # SQL/Schema/Python 三大工具函数
│
├── api/                          # FastAPI HTTP/WebSocket 接入层
│   ├── __init__.py
│   ├── main.py                   # FastAPI App + 启动事件 + 静态文件
│   ├── routes.py                 # 所有路由：REST + WebSocket
│   └── models.py                 # Pydantic 请求/响应/事件模型
│
├── frontend/
│   └── src/
│       └── index.html            # 无框架单页前端应用
│
├── data/
│   └── demo.db                   # SQLite 演示数据库（git ignore）
│
├── scripts/
│   └── init_demo_data.py         # 初始化演示数据（2万条电商订单）
│
├── tests/
│   └── test_components.py        # 各模块单元测试
│
├── mcp_config.json               # 运行时自动生成，Claude Code 读取（git ignore）
├── .env                          # 环境变量（git ignore）
├── .env.example                  # 环境变量模板
├── requirements.txt              # Python 依赖
├── start.sh                      # 一键启动脚本
└── README.md                     # 快速上手说明
```

---

## 3. 启动流程

```
bash start.sh
    │
    ├─① 检查 .env 是否存在
    │       └─ 不存在 → 从 .env.example 复制，提示填写 ANTHROPIC_API_KEY
    │
    ├─② pip install -r requirements.txt（幂等安装）
    │
    ├─③ 检查 data/demo.db 是否存在
    │       └─ 不存在 → 执行 scripts/init_demo_data.py
    │               ├── CREATE TABLE users / products / orders
    │               ├── 插入 2000 条用户数据
    │               ├── 插入 18 条商品数据
    │               └── 插入 20000 条订单数据（2024-11 ~ 2025-04）
    │
    ├─④ python3 tests/test_components.py（冒烟测试）
    │
    └─⑤ uvicorn api.main:app --host 0.0.0.0 --port 8000
            │
            └─ FastAPI startup 事件触发
                    └─ write_mcp_config()
                            └─ 生成 mcp_config.json：
                               {
                                 "mcpServers": {
                                   "data_tools": {
                                     "command": "python3",
                                     "args": ["mcp_server/server.py"],
                                     "env": { "DATABASE_URL": "..." }
                                   }
                                 }
                               }
```

**关键点**：`mcp_config.json` 是在 FastAPI **启动时动态生成**的，内容包含 MCP Server 的启动命令和环境变量。后续每次 Claude Code Agent 启动时，都通过 `--mcp-config` 参数读取此文件，从而知道如何拉起数据工具进程。

---

## 4. 完整请求生命周期

以一次 WebSocket 分析请求为例，端到端完整流程：

```
用户在浏览器输入：
  "分析最近30天的订单趋势，找出异常波动原因"
         │
         │  ① WebSocket 握手
         ▼
  frontend/src/index.html
  sendQuery()
    └── ws = new WebSocket("ws://host/api/ws/analyze")
    └── ws.send(JSON.stringify({ query: "...", context: {} }))
         │
         │  ② WS 消息到达服务端
         ▼
  api/routes.py :: ws_analyze()
    ├── await websocket.accept()
    ├── session_id = uuid4()[:8]          # 生成会话ID，如 "a3f9c012"
    ├── 解析 payload，提取 query / context
    ├── 推送 progress 事件给前端           # {"type":"progress","content":"开始分析..."}
    ├── 创建 ws_send 回调函数             # 将事件序列化后推 WebSocket
    └── agent = ClaudeCodeAgent(
            work_dir="/tmp/cc_agent_a3f9c012",
            mcp_config_path="mcp_config.json",
            on_event=ws_send              # ← 实时推送钩子
        )
         │
         │  ③ 调用 Agent 核心
         ▼
  agent/agent.py :: analyze()
    ├── full_prompt = _build_prompt(query, context)
    │       └── 填充 ANALYSIS_PROMPT_TEMPLATE：
    │           "## 数据分析请求
    │            用户问题: 分析最近30天的订单趋势...
    │            背景信息: 无特殊背景说明
    │            执行指引: 1.先调用get_schema..."
    │
    └── async for event in _run_claude_stream(full_prompt):
         │
         │  ④ 启动 Claude Code 子进程
         ▼
  agent/agent.py :: _run_claude_stream()
    └── cmd = [
            "claude",
            "--output-format", "stream-json",  # 每行输出一个 JSON 事件
            "--max-turns", "30",
            "--no-interactive",
            "--print",
            "--system-prompt", SYSTEM_PROMPT,
            "--allowedTools", "Bash,Read,Write,Edit",
            "--mcp-config", "/home/user/webapp/mcp_config.json",
            "<full_prompt>"
        ]
    └── process = await asyncio.create_subprocess_exec(*cmd,
            stdout=PIPE, stderr=PIPE,
            cwd="/tmp/cc_agent_a3f9c012"
        )
         │
         │  ⑤ Claude Code 进程启动
         │     同时拉起 MCP Server 子进程：
         │     python3 mcp_server/server.py
         ▼
  mcp_server/server.py (独立子进程，MCP stdio 协议)
    └── MCP Server 就绪，等待 Claude Code 调用工具
         │
         │  ⑥ Claude Code 开始执行（多轮 Agentic 循环）
         ▼
  Claude Code 内部执行循环：

  Turn 1: 理解任务
    模型思考 → 输出 stream-json:
    {"type":"assistant","message":{"content":[
      {"type":"text","text":"我来分析最近30天订单趋势。首先探索数据库结构..."}
    ]}}
         │ Python 收到 → AgentEvent(type="thinking", content="我来分析...")
         │ 推送给 WebSocket → 前端展示到 Trace 面板
         ▼
  Turn 2: 探索数据库 Schema
    模型决定调用工具 → 输出 stream-json:
    {"type":"assistant","message":{"content":[
      {"type":"tool_use","name":"mcp__data_tools__get_schema","input":{}}
    ]}}
         │ Python 收到 → AgentEvent(type="tool_call", tool_name="mcp__data_tools__get_schema")
         │ Claude Code 通过 MCP 协议发送请求给 mcp_server/server.py
         ▼
  mcp_server/server.py :: call_tool("get_schema", {})
    └── db_tools.get_schema()
            ├── SQLAlchemy inspect() 获取所有表名
            ├── 查询每张表的列信息（名称、类型、nullable）
            ├── SELECT COUNT(*) 统计行数
            └── SELECT * LIMIT 3 获取样例数据
        返回：
        {
          "orders": {"columns":[...],"row_count":20000,"sample_data":{...}},
          "users":  {"columns":[...],"row_count":2000, "sample_data":{...}},
          "products":{"columns":[...],"row_count":18,  "sample_data":{...}}
        }
         │ MCP 通过 stdio 返回给 Claude Code
         │ stream-json 输出:
         │ {"type":"tool","content":[{"type":"text","text":"{...}"}]}
         │ Python 收到 → AgentEvent(type="tool_result", content="{...}")
         ▼
  Turn 3: 执行 SQL 查询
    模型根据 schema 构造 SQL → 调用 query_database:
    {"type":"tool_use","name":"mcp__data_tools__query_database",
     "input":{"sql":"SELECT DATE(created_at) as date, COUNT(*) as order_cnt,
                     SUM(amount) as gmv FROM orders
                     WHERE created_at >= DATE('now','-30 days')
                       AND status='completed'
                     GROUP BY DATE(created_at) ORDER BY date"}}
         │
         ▼
  mcp_server/db_tools.py :: query_database(sql)
    ├── validate_sql() → 检查禁止关键词（INSERT/UPDATE/DELETE/DROP...）
    ├── inject_limit() → 若无 LIMIT 则自动追加 LIMIT 5000
    ├── pd.read_sql(safe_sql, engine) → 执行查询
    └── 返回：{"columns":["date","order_cnt","gmv"],"rows":[...],"row_count":30}
         │
         ▼
  Turn 4: Python 统计分析
    模型调用 run_analysis 做环比计算:
    {"type":"tool_use","name":"mcp__data_tools__run_analysis",
     "input":{"code":"
       import pandas as pd
       data = <前面查询的数据>
       df = pd.DataFrame(data['rows'], columns=data['columns'])
       df['date'] = pd.to_datetime(df['date'])
       df['mom_growth'] = df['order_cnt'].pct_change() * 100
       anomaly = df[df['mom_growth'].abs() > 30]
       result = anomaly.to_dict('records')
       print(f'异常日期数: {len(anomaly)}')
     "}}
         │
         ▼
  mcp_server/db_tools.py :: run_analysis(code)
    ├── 注入执行环境：{"pd": pandas, "np": numpy, "json": json}
    ├── 捕获 stdout（print 输出）
    ├── exec(code, safe_globals, local_vars)
    └── 返回：{"output":"异常日期数: 3\n","result":[{...}]}
         │
         ▼
  Turn 5: 生成最终报告
    模型整合所有数据 → 输出 Markdown 报告:
    {"type":"result","result":"## 📊 分析结论\n...","cost_usd":0.0032,"num_turns":5}
         │
         │  ⑦ Python 逐行读取事件流结束
         ▼
  agent/agent.py
    ├── _extract_report(events)  → 取 done 事件的 content 作为报告
    ├── _extract_stats(events)   → 取 cost_usd / num_turns
    └── 返回 AgentResult(success=True, report="## 📊 ...", ...)
         │
         │  ⑧ 路由层收到结果
         ▼
  api/routes.py :: ws_analyze()
    ├── 存入 _sessions[session_id]
    └── 推送 done 事件给 WebSocket：
        {"type":"done","content":"## 📊 分析结论\n...","metadata":{"cost_usd":0.0032}}
         │
         │  ⑨ 前端接收 done 事件
         ▼
  frontend/src/index.html
    ├── handleStreamEvent(ev) → case "done"
    ├── appendReport(ev.content, ...)  → 渲染 Markdown 到页面
    └── loadHistory()  → 刷新左侧历史记录
```

---

## 5. 模块详解：agent/

### 5.1 agent/prompts.py — Prompt 管理

集中存放所有 Prompt 字符串，避免散落在业务代码中。

| 常量 | 用途 | 说明 |
|------|------|------|
| `SYSTEM_PROMPT` | Claude Code 系统提示词 | 定义 Agent 角色、工作流程（6步）、约束规则、输出格式 |
| `TASK_PLANNING_PROMPT` | 任务规划模板 | 用于 Haiku 轻量规划，输出 JSON 任务 DAG |
| `ANALYSIS_PROMPT_TEMPLATE` | 分析执行模板 | 每次实际分析时填充 query + context |

**SYSTEM_PROMPT 工作流程规定**：

```
1. 理解查询   → 明确分析目标和指标
2. 探索数据   → 调用 get_schema 了解表结构
3. 拆解任务   → 输出分步执行计划
4. 取数执行   → 调用 query_database 获取数据
5. 分析计算   → 调用 run_analysis 执行 Python 统计
6. 生成洞察   → 输出标准 Markdown 报告
```

---

### 5.2 agent/agent.py — ClaudeCodeAgent 核心

**类结构**：

```python
class ClaudeCodeAgent:
    ┌─ __init__(work_dir, max_turns, mcp_config_path, on_event)
    │      └─ 创建工作目录，保存配置
    │
    ├─ analyze(query, context, stream_callback)     ← 公开入口
    │      ├─ _build_prompt()  → 填充 ANALYSIS_PROMPT_TEMPLATE
    │      ├─ _run_claude_stream()  → 异步生成器，逐事件 yield
    │      └─ _extract_report() / _extract_stats()  → 从事件流提取结果
    │
    ├─ _run_claude_stream(prompt)                   ← subprocess 核心
    │      ├─ _build_cmd()   → 组装 claude CLI 命令
    │      ├─ _build_env()   → 注入环境变量（ANTHROPIC_API_KEY）
    │      └─ asyncio.create_subprocess_exec()  → 启动子进程
    │             └─ async for line in process.stdout:
    │                    └─ _parse_stream_line(line)  → 解析单行 JSON
    │
    └─ _parse_stream_line(line)                     ← 事件解析器
           ├─ type=="system"    → AgentEvent(thinking, "初始化...")
           ├─ type=="assistant" → content[].type=="text"     → AgentEvent(thinking)
           │                   → content[].type=="tool_use"  → AgentEvent(tool_call)
           ├─ type=="tool"      → AgentEvent(tool_result)
           └─ type=="result"    → AgentEvent(done, content=最终报告)
```

**stream-json 事件格式详解**：

```jsonc
// Claude Code CLI --output-format stream-json 每行输出一个 JSON

// 1. 系统初始化
{"type": "system", "subtype": "init", "session_id": "xxx"}

// 2. 模型思考（文本输出）
{
  "type": "assistant",
  "message": {
    "content": [
      {"type": "text", "text": "我来分析订单趋势，首先探索数据库结构..."}
    ]
  }
}

// 3. 模型决定调用工具
{
  "type": "assistant",
  "message": {
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_01XYZ",
        "name": "mcp__data_tools__get_schema",
        "input": {}
      }
    ]
  }
}

// 4. 工具执行结果（MCP 返回后 Claude Code 注入）
{
  "type": "tool",
  "tool_use_id": "toolu_01XYZ",
  "content": [
    {"type": "text", "text": "{\"orders\":{...},\"users\":{...}}"}
  ]
}

// 5. 最终结果（所有 turns 完成后）
{
  "type": "result",
  "subtype": "success",
  "result": "## 📊 分析结论\n...",
  "cost_usd": 0.0032,
  "num_turns": 5,
  "is_error": false
}
```

---

### 5.3 agent/planner.py — TaskPlanner 任务规划

独立于 ClaudeCodeAgent，使用轻量的 `claude-3-5-haiku` 做**预规划**（可选调用）。

```
用户 Query
    │
    ▼
TaskPlanner.plan(query, schema_info)
    │
    ├── 构造 TASK_PLANNING_PROMPT（填入 query + schema JSON）
    ├── anthropic.messages.create(model="claude-3-5-haiku-20241022")
    └── _parse_plan(raw_text)
            ├── re.search(r"\{[\s\S]*\}") 提取 JSON 块
            └── 返回 AnalysisPlan:
                    ├── analysis_type: "trend"
                    ├── summary: "分析30天订单趋势"
                    └── tasks: [
                            AnalysisTask(id="t1", title="探索表结构", type="schema_explore"),
                            AnalysisTask(id="t2", title="查询日订单", type="sql_query", dependencies=["t1"]),
                            AnalysisTask(id="t3", title="计算环比", type="python_analysis", dependencies=["t2"])
                        ]
```

**为什么用 Haiku 而不是直接让 Claude Code 规划？**

- Haiku 调用更快（<1s）、更便宜（规划不需要执行工具）
- Claude Code 的 max_turns 是宝贵资源，让它专注执行
- 规划结果可用于前端展示"预计步骤"，提升用户体验

---

## 6. 模块详解：mcp_server/

### 6.1 mcp_server/server.py — MCP Server 主入口

MCP (Model Context Protocol) Server 是一个**独立子进程**，通过 `stdio` (标准输入输出) 与 Claude Code 通信，使用 JSON-RPC 协议。

```python
# 启动方式（由 Claude Code 根据 mcp_config.json 自动拉起）
python3 mcp_server/server.py

# 通信协议：stdin → JSON-RPC 请求，stdout → JSON-RPC 响应
```

**工具注册流程**：

```python
app = Server("data-tools")

@app.list_tools()      # 响应 Claude Code 的工具发现请求
async def list_tools() -> list[Tool]:
    return [
        Tool(name="query_database", description="...", inputSchema={...}),
        Tool(name="get_schema",     description="...", inputSchema={...}),
        Tool(name="run_analysis",   description="...", inputSchema={...}),
    ]

@app.call_tool()       # 响应 Claude Code 的工具调用请求
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_database": ...
    elif name == "get_schema":   ...
    elif name == "run_analysis": ...
```

**MCP 工具命名规则**：
Claude Code 中调用 MCP 工具时，名称格式为 `mcp__<server_name>__<tool_name>`。
本项目的 server_name 为 `data_tools`（来自 `mcp_config.json` 中的 key），因此：
- `mcp__data_tools__get_schema`
- `mcp__data_tools__query_database`
- `mcp__data_tools__run_analysis`

---

### 6.2 mcp_server/db_tools.py — 工具函数实现

#### `get_schema(table_name, include_sample)` 表结构探索

```python
流程：
    get_engine()                   # 延迟初始化 SQLAlchemy Engine
        └── create_engine(DATABASE_URL)
    │
    inspector.get_table_names()    # 获取所有表名
    inspector.get_columns(tname)   # 获取列信息（name, type, nullable）
    │
    SELECT COUNT(*) FROM {table}   # 行数统计
    SELECT * FROM {table} LIMIT 3  # 样例数据
    │
    返回 dict：
    {
      "orders": {
        "columns": [{"name":"order_id","type":"INTEGER","nullable":true}, ...],
        "row_count": 20000,
        "sample_data": {
          "columns": ["order_id","user_id",...],
          "rows": [[1,42,...],[2,88,...],[3,7,...]]
        }
      },
      ...
    }
```

#### `query_database(sql, limit)` SQL 查询

```python
流程：
    validate_sql(sql)
        └── regex 检查 INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE/REPLACE/MERGE
        └── 发现禁止关键词 → 返回 error（不执行）
    │
    inject_limit(sql, max_rows)
        └── 检查是否含 LIMIT 子句
        └── 无 LIMIT → 自动追加 "LIMIT {max_rows}"
    │
    pd.read_sql(safe_sql, engine)
        └── 执行查询，结果转为 DataFrame
    │
    日期列 → astype(str)            # 避免 JSON 序列化问题
    │
    返回 dict：
    {
      "columns": ["date", "order_cnt", "gmv"],
      "rows": [["2025-04-01", 320, 45600.0], ...],
      "row_count": 30,
      "sql_executed": "SELECT ... LIMIT 5000"
    }
```

#### `run_analysis(code, data_context)` Python 分析沙箱

```python
流程：
    构建执行环境 safe_globals：
        {"__builtins__": __builtins__,   # 完整内置（含 import）
         "pd": pandas,
         "np": numpy,
         "json": json}
    │
    若有 data_context → 合并到 safe_globals
    │
    捕获 stdout（用 io.StringIO 替换 sys.stdout）
    │
    exec(code, safe_globals, local_vars)
        └── 代码中的 result 变量将被捕获
    │
    恢复 sys.stdout
    │
    序列化 result：
        DataFrame → {"type":"dataframe","columns":[...],"rows":[...],"shape":[...]}
        其他对象 → 调用 .to_dict() 或原样返回
    │
    返回 dict：
    {
      "output": "异常日期数: 3\n",     # print 输出
      "result": [{"date":"2025-04-12","mom_growth":45.2}, ...]
    }
```

---

## 7. 模块详解：api/

### 7.1 api/models.py — 数据模型

```python
# 请求模型
AnalyzeRequest:
    query: str          # 自然语言问题（2~2000字符）
    context: dict|None  # 可选背景：time_range / dimensions / compare_period

# 响应模型
AnalyzeResponse:
    session_id: str     # 会话唯一ID（uuid前8位）
    query: str          # 原始问题
    report: str         # Markdown 格式分析报告
    success: bool
    tool_calls: list    # 工具调用历史记录
    cost_usd: float     # Claude 调用费用
    num_turns: int      # Agent 执行轮次
    error: str          # 错误信息（成功时为空）

# WebSocket 流式事件
StreamEvent:
    session_id: str
    type: str           # progress|thinking|tool_call|tool_result|done|error
    content: str        # 事件内容（截断至1000字符）
    tool_name: str      # 工具调用时的工具名
    tool_input: dict    # 工具调用时的输入参数
    metadata: dict      # 附加信息（cost/turns/session_id）
    timestamp: str      # ISO 格式时间戳
```

---

### 7.2 api/routes.py — 路由层

**REST 接口**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/health` | 健康检查，返回 db_connected 状态 |
| GET  | `/api/schema` | 获取数据库所有表结构（可传 table_name 过滤） |
| POST | `/api/analyze` | 同步分析（等待完整结果，适合短时查询） |
| GET  | `/api/history` | 最近 20 条分析历史 |
| GET  | `/api/session/{id}` | 查询指定会话的完整结果 |

**WebSocket 接口** `ws://host/api/ws/analyze`：

```
客户端 → 服务端：
  {"query": "分析近30天订单", "context": {}}

服务端 → 客户端（流式事件序列）：
  {"type":"progress",     "content":"开始分析..."}
  {"type":"thinking",     "content":"我来分析订单趋势..."}
  {"type":"tool_call",    "tool_name":"mcp__data_tools__get_schema", "tool_input":{}}
  {"type":"tool_result",  "content":"{\"orders\":{...}}"}
  {"type":"thinking",     "content":"已获取表结构，开始编写SQL..."}
  {"type":"tool_call",    "tool_name":"mcp__data_tools__query_database", "tool_input":{"sql":"..."}}
  {"type":"tool_result",  "content":"{\"rows\":[...]}"}
  {"type":"done",         "content":"## 📊 分析结论\n...", "metadata":{"cost_usd":0.003}}
```

**Agent 创建与 WebSocket 回调绑定**：

```python
# routes.py 中的关键逻辑
async def ws_send(json_str: str):          # ① 定义 WS 推送函数
    await websocket.send_text(json_str)

agent = ClaudeCodeAgent(
    on_event=on_event_wrapper              # ② 注入回调
)

# on_event_wrapper 将 AgentEvent 序列化为 StreamEvent JSON
# 每次 Agent 产生事件 → 自动调用 ws_send → 推送到前端
```

---

### 7.3 api/main.py — FastAPI 应用

```python
流程：

uvicorn 启动
    │
    ├── load_dotenv()                    # 加载 .env
    ├── FastAPI() 初始化
    ├── CORSMiddleware（允许所有来源）
    ├── include_router(router, prefix="/api")
    ├── mount StaticFiles("/static", "frontend/src/")
    └── @app.on_event("startup")
            └── write_mcp_config()
                    └── 生成 mcp_config.json：
                        {
                          "mcpServers": {
                            "data_tools": {
                              "command": "python3",
                              "args": ["<abs_path>/mcp_server/server.py"],
                              "env": {
                                "DATABASE_URL": "sqlite:///./data/demo.db",
                                "PYTHONPATH": "<project_root>"
                              }
                            }
                          }
                        }
```

---

## 8. 模块详解：frontend/

### 8.1 frontend/src/index.html — 单页应用

无任何外部框架依赖，纯原生 HTML + CSS + JavaScript。

**主要功能模块**：

```
index.html
│
├── CSS 变量系统（暗色主题）
│   ├── --bg / --bg2 / --bg3   背景层级
│   ├── --accent / --accent2   主色（紫色系）
│   ├── --green / --orange     状态色
│   └── --text / --text2 / --text3  文本层级
│
├── 布局：header + sidebar + main + input-bar
│
├── JavaScript 功能
│   │
│   ├── 初始化（DOMContentLoaded）
│   │   ├── checkHealth()   → GET /api/health → 更新状态点
│   │   ├── loadSchema()    → GET /api/schema → 渲染侧边栏表结构
│   │   └── loadHistory()   → GET /api/history → 渲染历史记录
│   │
│   ├── sendQuery()         → 核心发送逻辑
│   │   ├── 禁用输入框（防重复提交）
│   │   ├── appendUserBubble()    → 渲染用户气泡
│   │   ├── appendAgentThinking() → 渲染 Trace 面板 + Spinner
│   │   └── new WebSocket(WS_BASE)
│   │           ├── onopen  → ws.send(JSON.stringify({query, context}))
│   │           ├── onmessage → handleStreamEvent(ev, ...)
│   │           └── onclose → setAnalyzing(false)
│   │
│   ├── handleStreamEvent(ev, traceBody, spinnerEl)
│   │   ├── "progress"    → updateSpinner()
│   │   ├── "thinking"    → appendTraceLine(🗣️)
│   │   ├── "tool_call"   → appendTraceLine(🔧)
│   │   ├── "tool_result" → appendTraceLine(✅)
│   │   ├── "done"        → appendReport() + loadHistory()
│   │   └── "error"       → appendErrorBubble()
│   │
│   └── renderMarkdown(md)  → 轻量 Markdown 渲染器
│       ├── 代码块（```lang ... ```）
│       ├── 行内代码（`code`）
│       ├── 标题（## h2 / ### h3）
│       ├── 粗体（**text**）
│       ├── 表格（| col | col |）
│       ├── 无序列表（- item）
│       └── 有序列表（1. item）
```

---

## 9. Python 与 Claude Code 交互原理

这是整个系统最核心的部分，理解它是理解整个架构的关键。

### 9.1 为什么用 subprocess 而不是 Python SDK？

```
方式对比：

① claude-code-sdk（Python）
   优点：API 更简洁
   缺点：SDK 仍在 Beta，stream-json 支持不完整

② subprocess + CLI（本项目采用）
   优点：稳定可靠，完整支持所有 CLI 参数，包括 --mcp-config
   缺点：需要手动解析 stream-json

③ MCP Client 直接集成
   适合：不需要 Claude Code 推理能力，只需工具调用的场景
```

### 9.2 subprocess 交互的核心代码

```python
# agent/agent.py 核心逻辑（简化版）

async def _run_claude_stream(self, prompt: str):
    cmd = [
        "claude",
        "--output-format", "stream-json",   # ← 关键：每行一个 JSON 事件
        "--max-turns", "30",                # ← 最多执行 30 轮对话
        "--no-interactive",                 # ← 非交互模式（不等待键盘输入）
        "--print",                          # ← 执行完毕后自动退出
        "--system-prompt", SYSTEM_PROMPT,   # ← 注入角色定义
        "--allowedTools", "Bash,Read,Write,Edit",  # ← 允许的内置工具
        "--mcp-config", self.mcp_config_path,      # ← 注入 MCP 数据工具
        prompt                              # ← 用户 Query 作为最后一个参数
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,    # ← 捕获标准输出
        stderr=asyncio.subprocess.PIPE,    # ← 捕获错误输出
        cwd=self.work_dir,                 # ← 工作目录（每个会话独立）
        env=self._build_env(),             # ← 注入 ANTHROPIC_API_KEY
    )

    # 异步逐行读取（非阻塞，不会卡住事件循环）
    async for raw_line in process.stdout:
        line = raw_line.decode("utf-8").strip()
        event = self._parse_stream_line(line)
        if event:
            yield event     # ← 通过 async generator 推给调用方

    await process.wait()    # ← 等待进程完全退出
```

### 9.3 stream-json 解析状态机

```
每一行 raw_line 经过 _parse_stream_line() 转换为 AgentEvent：

raw_line (bytes)
    │
    decode("utf-8").strip()
    │
    json.loads(line)
    │
    根据 obj["type"] 分支：
    │
    ├─ "system"    → AgentEvent(type="thinking",    content="初始化: init")
    │
    ├─ "assistant" → obj["message"]["content"] 列表
    │                  ├─ block.type == "text"
    │                  │   └─ AgentEvent(type="thinking",  content=block.text)
    │                  └─ block.type == "tool_use"
    │                      └─ AgentEvent(type="tool_call", tool_name=block.name,
    │                                    tool_input=block.input)
    │
    ├─ "tool"      → AgentEvent(type="tool_result", content=截断至2000字符)
    │
    ├─ "result"    → AgentEvent(type="done",
    │                            content=obj.result,
    │                            metadata={cost_usd, num_turns, is_error})
    │
    └─ 其他        → None（忽略）
```

---

## 10. MCP 协议工作原理

### 10.1 MCP 是什么？

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，让 AI 模型能够标准化地调用外部工具。本质上是一套基于 JSON-RPC 的工具调用协议。

### 10.2 Claude Code 如何拉起 MCP Server？

```
1. Claude Code 读取 mcp_config.json：
   {
     "mcpServers": {
       "data_tools": {
         "command": "python3",
         "args": ["/path/to/mcp_server/server.py"],
         "env": {"DATABASE_URL": "...", "PYTHONPATH": "..."}
       }
     }
   }

2. Claude Code 以 subprocess 方式启动 MCP Server：
   python3 /path/to/mcp_server/server.py
   （通过 stdin/stdout 进行 JSON-RPC 通信）

3. Claude Code 发送 initialize 请求，MCP Server 返回能力声明

4. Claude Code 发送 tools/list 请求，获取工具列表

5. 模型决定调用工具时，Claude Code 发送 tools/call 请求
```

### 10.3 工具调用完整 JSON-RPC 流程

```
Claude Code → MCP Server (stdin):
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "query_database",
    "arguments": {
      "sql": "SELECT DATE(created_at) as dt, COUNT(*) FROM orders GROUP BY dt LIMIT 30"
    }
  }
}

MCP Server → Claude Code (stdout):
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"columns\":[\"dt\",\"COUNT(*)\"],\"rows\":[[\"2025-04-01\",320],...]}"
      }
    ]
  }
}
```

---

## 11. 数据流转图

```
用户输入 "分析近30天订单趋势"
    │
    ▼
[前端 WebSocket] ──JSON──▶ [FastAPI routes.py]
                                    │
                           创建 ClaudeCodeAgent
                           注入 ws_send 回调
                                    │
                           agent.analyze(query)
                                    │
                           _build_prompt()
                           填充 ANALYSIS_PROMPT_TEMPLATE
                                    │
                           asyncio.create_subprocess_exec
                           ┌─────────────────────────────┐
                           │   claude CLI 进程            │
                           │   --output-format stream-json│
                           │   --mcp-config xxx.json      │
                           └──────────┬──────────────────┘
                                      │ 同时拉起
                           ┌──────────▼──────────────────┐
                           │   python3 mcp_server/server.py│
                           │   (MCP stdio 服务)            │
                           └──────────────────────────────┘
                                      │
                   ┌──────────────────┼──────────────────────┐
                   │                  │                       │
              get_schema()     query_database()         run_analysis()
                   │                  │                       │
              SQLAlchemy         pd.read_sql()          exec(code)
              inspect()          + validate          + pandas/numpy
                   │                  │                       │
              返回表结构          返回查询结果            返回分析结果
                   │                  │                       │
                   └──────────────────┴───────────────────────┘
                                      │
                              各工具结果通过 MCP 返回给 Claude Code
                                      │
                              Claude Code 整合所有结果
                              生成 Markdown 报告
                                      │
                              输出 {"type":"result","result":"## ..."}
                                      │
                           _parse_stream_line() 解析
                           AgentEvent(type="done", content=报告)
                                      │
                           ws_send 回调触发
                                      │
[前端 WebSocket] ◀──JSON── [FastAPI routes.py]
    │
    ▼
handleStreamEvent(ev)
appendReport(ev.content)
renderMarkdown() → 展示分析报告
```

---

## 12. 关键设计决策

### 12.1 为什么每个会话使用独立工作目录？

```python
work_dir=f"/tmp/cc_agent_{session_id}"
```

- Claude Code 可能在工作目录创建临时文件（分析脚本、中间结果）
- 多并发请求互不干扰
- 会话结束后可安全清理

### 12.2 为什么 MCP Config 在启动时动态生成？

```python
@app.on_event("startup")
async def on_startup():
    write_mcp_config()
```

- `mcp_server/server.py` 的绝对路径在部署时才能确定
- `DATABASE_URL` 来自 `.env`，运行时读取
- 避免将路径硬编码到 Git 仓库

### 12.3 SQL 安全设计

```
三道防线：
① validate_sql()    → 正则禁止写操作关键词
② inject_limit()    → 自动注入 LIMIT，防止全表扫描
③ 只读 SQLAlchemy  → 生产环境可配置只读数据库账号
```

### 12.4 事件回调的同步/异步兼容

```python
@staticmethod
async def _safe_callback(cb, event):
    if asyncio.iscoroutinefunction(cb):
        await cb(event)          # 支持 async def callback
    else:
        cb(event)                # 支持普通 def callback
```

允许调用方传入任意类型的回调函数，不需要关心异步细节。

### 12.5 报告提取降级策略

```python
def _extract_report(events):
    # 优先：取最后一个 done 事件的 content
    for ev in reversed(events):
        if ev.type == "done" and ev.content.strip():
            return ev.content
    # 降级：拼接最后 5 条 thinking 文本
    parts = [ev.content for ev in events if ev.type == "thinking"]
    return "\n\n".join(parts[-5:]) if parts else "分析完成，未获取到报告内容。"
```

即使 Claude Code 未输出标准 `result` 事件，也能兜底返回内容。

---

## 13. 扩展指南

### 13.1 接入真实数据库

```bash
# .env 修改
DATABASE_URL=postgresql://user:password@host:5432/your_db

# 自动生效，无需改代码
# SQLAlchemy 支持：PostgreSQL / MySQL / Oracle / SQL Server
```

### 13.2 新增 MCP 工具

在 `mcp_server/server.py` 中添加工具定义和处理逻辑：

```python
# 1. 在 list_tools() 中添加工具声明
Tool(
    name="call_api",
    description="调用外部 REST API 获取数据",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "params": {"type": "object"}
        },
        "required": ["url"]
    }
)

# 2. 在 call_tool() 中添加处理分支
elif name == "call_api":
    import httpx
    url = arguments["url"]
    resp = httpx.get(url, params=arguments.get("params", {}))
    return [TextContent(type="text", text=resp.text)]
```

### 13.3 接入 Redis 替代内存会话

```python
# api/routes.py 替换 _sessions dict
import redis.asyncio as redis

redis_client = redis.from_url("redis://localhost:6379")

# 存储
await redis_client.setex(f"session:{session_id}", 3600, result_json)

# 读取
data = await redis_client.get(f"session:{session_id}")
```

### 13.4 添加认证

```python
# api/main.py 添加 API Key 验证中间件
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

@app.middleware("http")
async def verify_api_key(request, call_next):
    if request.url.path.startswith("/api"):
        key = request.headers.get("X-API-Key")
        if key != os.getenv("API_KEY"):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)
```

---

*本文档由项目代码自动梳理生成，如有更新请同步修改此文件。*
