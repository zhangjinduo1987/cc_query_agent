# 问数分析智能体 (cc_query_agent)

基于 **Claude Code** 作为智能体引擎，完成自然语言 → 数据分析的全流程系统。

## 架构

```
用户自然语言 Query
       │
       ▼
  FastAPI 后端  ←→  WebSocket 实时推送
       │
       ▼
 Claude Code Agent  (claude-code-sdk / CLI)
       │
       ├── MCP Server (数据工具层)
       │       ├── query_database   SQL取数
       │       ├── get_schema       表结构探索
       │       └── run_analysis     Python分析
       │
       └── 工具执行 → 结果 → 报告
```

## 目录结构

```
cc_query_agent/
├── agent/               # Claude Code Agent 核心
│   ├── agent.py         # 主 Agent 类
│   ├── planner.py       # 任务拆解 DAG
│   └── prompts.py       # Prompt 管理
├── mcp_server/          # MCP 数据工具服务
│   ├── server.py        # MCP Server 主入口
│   ├── db_tools.py      # 数据库工具
│   └── analysis_tools.py# 分析工具
├── api/                 # FastAPI 后端
│   ├── main.py          # 入口 + WebSocket
│   ├── routes.py        # API 路由
│   └── models.py        # 数据模型
├── frontend/            # 前端界面
│   └── src/index.html   # 单页应用
├── data/
│   └── sample/          # SQLite Demo 数据
├── tests/               # 测试
├── scripts/             # 工具脚本
├── .env.example         # 环境变量示例
└── requirements.txt
```

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY

# 3. 初始化 Demo 数据
python scripts/init_demo_data.py

# 4. 启动服务
python api/main.py
# 访问 http://localhost:8000
```

## 技术栈

| 层次 | 技术 |
|------|------|
| Agent 引擎 | Claude Code SDK / CLI subprocess |
| 工具扩展 | MCP (Model Context Protocol) |
| 后端 | FastAPI + WebSocket |
| 数据库 | SQLite(demo) / PostgreSQL(生产) |
| 分析 | pandas + sqlalchemy |
| 前端 | 原生 HTML/JS (无框架依赖) |

## 示例 Query

- "分析最近30天订单趋势，找出异常波动"
- "对比本月和上月各城市的销售额"
- "找出高价值用户的行为特征"
- "统计各商品类目的转化率漏斗"
