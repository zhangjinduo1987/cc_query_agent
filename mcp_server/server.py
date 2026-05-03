"""
MCP Server 主入口 - 通过 stdio 协议暴露数据工具给 Claude Code Agent
工具列表:
  - query_database   : 执行只读 SQL 查询
  - get_schema       : 获取数据库表结构
  - run_analysis     : 执行 Python 数据分析代码
"""

import asyncio
import json
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from mcp_server.db_tools import query_database, get_schema, run_analysis

app = Server("data-tools")


# ------------------------------------------------------------------ #
#  Tool 定义                                                           #
# ------------------------------------------------------------------ #

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_database",
            description=(
                "执行只读 SQL SELECT 查询，返回结构化数据。"
                "支持 SQLite / PostgreSQL。禁止写操作。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "完整的 SQL SELECT 语句",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回行数，默认 5000，上限 10000",
                        "default": 5000,
                    },
                },
                "required": ["sql"],
            },
        ),
        Tool(
            name="get_schema",
            description=(
                "获取数据库表结构、字段类型、行数统计和样例数据。"
                "在执行 SQL 前必须先调用此工具了解数据结构。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "指定表名（留空则返回所有表）",
                    },
                    "include_sample": {
                        "type": "boolean",
                        "description": "是否包含样例数据（默认 true）",
                        "default": True,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="run_analysis",
            description=(
                "在安全沙箱中执行 Python 数据分析代码（可使用 pandas / json）。"
                "将分析结果赋值给变量 `result` 可返回结构化数据。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python 分析代码，可用 pandas (pd) 和 json 模块",
                    },
                    "data_context": {
                        "type": "object",
                        "description": "注入代码执行环境的额外变量（可选）",
                    },
                },
                "required": ["code"],
            },
        ),
    ]


# ------------------------------------------------------------------ #
#  Tool 执行                                                           #
# ------------------------------------------------------------------ #

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    if name == "query_database":
        sql = arguments.get("sql", "")
        limit = int(arguments.get("limit", 5000))
        result = query_database(sql, limit=limit)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "get_schema":
        table_name = arguments.get("table_name") or None
        include_sample = bool(arguments.get("include_sample", True))
        result = get_schema(table_name=table_name, include_sample=include_sample)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "run_analysis":
        code = arguments.get("code", "")
        data_context = arguments.get("data_context") or {}
        result = run_analysis(code, data_context=data_context)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
