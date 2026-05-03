"""
mcp/server.py — BI MCP Server 主入口

通过 stdio 协议暴露 query_bi_data 工具给 Claude Code Agent。
Claude Code 会根据 mcp_config.json 自动拉起此进程。

工具：
  query_bi_data(tb_name, field_keys, filters, limit)
    → 拼接 SQL，连接 BI 数据库执行，返回结构化结果
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any

# 确保项目根目录在 PYTHONPATH
sys.path.insert(0, os.environ.get("PYTHONPATH", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import pandas as pd
from sqlalchemy import create_engine, text

# ── 数据库连接 ────────────────────────────────────────────────
BI_DB_URL = os.getenv("BI_DB_URL", "sqlite:///./bi_chat/data/demo_bi.db")
_bi_engine = None

def _get_bi_engine():
    global _bi_engine
    if _bi_engine is None:
        _bi_engine = create_engine(BI_DB_URL, echo=False, pool_pre_ping=True)
    return _bi_engine


# ── MCP Server 实例 ────────────────────────────────────────────
app = Server("bi-tools")


# ════════════════════════════════════════════════════════════
#  工具定义
# ════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_bi_data",
            description=(
                "查询 BI 数据库，返回结构化数据。\n"
                "参数说明：\n"
                "  tb_name    : 表名（来自元数据 tb_name 字段）\n"
                "  field_keys : 需要查询的字段列表（来自元数据 field_key，必须存在于元数据中）\n"
                "  filters    : 过滤条件列表，每项为 {field, op, value}\n"
                "               op 可选: =, !=, >, >=, <, <=, IN, LIKE, BETWEEN\n"
                "  group_by   : 分组字段列表（可选）\n"
                "  order_by   : 排序字段列表，每项为 {field, direction}（可选）\n"
                "  limit      : 最大返回行数，默认 500，上限 5000\n"
                "严禁虚构字段，field_keys 必须全部来自用户元数据中提供的 field_key。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tb_name": {
                        "type": "string",
                        "description": "查询的表名（英文），必须来自元数据",
                    },
                    "field_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要 SELECT 的字段列表（field_key）",
                    },
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op":    {"type": "string"},
                                "value": {},
                            },
                            "required": ["field", "op", "value"],
                        },
                        "description": "WHERE 条件列表，空数组表示不过滤",
                        "default": [],
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "GROUP BY 字段列表（可选）",
                        "default": [],
                    },
                    "order_by": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field":     {"type": "string"},
                                "direction": {"type": "string", "enum": ["ASC", "DESC"]},
                            },
                        },
                        "description": "ORDER BY 字段列表（可选）",
                        "default": [],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回行数，默认 500",
                        "default": 500,
                    },
                },
                "required": ["tb_name", "field_keys"],
            },
        )
    ]


# ════════════════════════════════════════════════════════════
#  工具执行
# ════════════════════════════════════════════════════════════

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_bi_data":
        result = _execute_query(arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    return [TextContent(type="text", text=json.dumps({"error": f"未知工具: {name}"}))]


# ════════════════════════════════════════════════════════════
#  SQL 构建 + 执行
# ════════════════════════════════════════════════════════════

# 允许的操作符白名单
_ALLOWED_OPS = {"=", "!=", ">", ">=", "<", "<=", "IN", "LIKE", "BETWEEN", "NOT IN"}

# 禁止的表名/字段名字符（防 SQL 注入）
_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_ident(name: str) -> str:
    """校验标识符安全性，不安全则抛出异常"""
    if not _SAFE_IDENT.match(name):
        raise ValueError(f"不合法的标识符: {name!r}")
    return name


def _build_sql(args: dict) -> tuple[str, dict]:
    """
    根据参数构建 SELECT SQL 语句（参数化查询）。
    返回 (sql_str, params_dict)。
    """
    tb_name    = _safe_ident(args["tb_name"])
    field_keys = [_safe_ident(f) for f in args.get("field_keys", [])]
    filters    = args.get("filters", [])
    group_by   = [_safe_ident(f) for f in args.get("group_by", [])]
    order_by   = args.get("order_by", [])
    limit      = min(int(args.get("limit", 500)), 5000)

    if not field_keys:
        raise ValueError("field_keys 不能为空")

    select_clause = ", ".join(field_keys)
    sql = f"SELECT {select_clause} FROM {tb_name}"

    # WHERE 子句
    params: dict = {}
    where_parts: list[str] = []
    for i, f in enumerate(filters):
        field = _safe_ident(f["field"])
        op    = f["op"].upper().strip()
        val   = f["value"]

        if op not in _ALLOWED_OPS:
            raise ValueError(f"不支持的操作符: {op!r}")

        param_key = f"p_{i}"

        if op == "IN" or op == "NOT IN":
            if not isinstance(val, list):
                val = [val]
            placeholders = ", ".join(f":p_{i}_{j}" for j in range(len(val)))
            for j, v in enumerate(val):
                params[f"p_{i}_{j}"] = v
            where_parts.append(f"{field} {op} ({placeholders})")
        elif op == "BETWEEN":
            if not isinstance(val, list) or len(val) != 2:
                raise ValueError("BETWEEN 需要 [min, max] 格式")
            params[f"{param_key}_a"] = val[0]
            params[f"{param_key}_b"] = val[1]
            where_parts.append(f"{field} BETWEEN :{param_key}_a AND :{param_key}_b")
        else:
            params[param_key] = val
            where_parts.append(f"{field} {op} :{param_key}")

    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    # GROUP BY
    if group_by:
        sql += " GROUP BY " + ", ".join(group_by)

    # ORDER BY
    if order_by:
        order_parts = []
        for ob in order_by:
            f = _safe_ident(ob["field"])
            d = "DESC" if str(ob.get("direction", "ASC")).upper() == "DESC" else "ASC"
            order_parts.append(f"{f} {d}")
        sql += " ORDER BY " + ", ".join(order_parts)

    # LIMIT
    sql += f" LIMIT {limit}"
    return sql, params


def _execute_query(args: dict) -> dict[str, Any]:
    """执行 SQL 并返回结构化结果"""
    try:
        sql, params = _build_sql(args)
    except ValueError as e:
        return {"error": str(e), "sql": ""}

    try:
        engine = _get_bi_engine()
        df = pd.read_sql(text(sql), engine.connect(), params=params)

        # 日期/datetime 列转字符串，避免 JSON 序列化失败
        for col in df.select_dtypes(include=["datetime64", "object"]).columns:
            df[col] = df[col].astype(str)

        return {
            "sql_executed": sql,
            "columns": df.columns.tolist(),
            "rows": df.values.tolist(),
            "row_count": len(df),
        }
    except Exception as e:
        return {
            "error": str(e),
            "sql_executed": sql,
        }


# ════════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════════

async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
