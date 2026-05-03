"""
数据库工具模块 - 封装 SQL 查询、Schema 探索等数据库操作
支持 SQLite（Demo）和 PostgreSQL（生产）
"""

import json
import re
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/demo.db")

# 全局引擎（延迟初始化）
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False)
    return _engine


# ------------------------------------------------------------------ #
#  SQL 安全检查                                                         #
# ------------------------------------------------------------------ #

_FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    检查 SQL 安全性。
    返回 (is_safe, error_message)
    """
    if _FORBIDDEN_PATTERNS.search(sql):
        return False, "禁止执行写操作（INSERT/UPDATE/DELETE/DROP 等）"
    return True, ""


def inject_limit(sql: str, max_rows: int = 5000) -> str:
    """若 SQL 没有 LIMIT，自动注入"""
    stripped = sql.strip().rstrip(";")
    if not _LIMIT_PATTERN.search(stripped):
        return f"{stripped} LIMIT {max_rows}"
    return stripped


# ------------------------------------------------------------------ #
#  核心工具函数                                                         #
# ------------------------------------------------------------------ #

def query_database(sql: str, limit: int = 5000) -> dict[str, Any]:
    """
    执行只读 SQL 查询，返回结构化结果。

    :param sql:   SELECT 语句
    :param limit: 最大返回行数（默认 5000）
    :return:      {"columns": [...], "rows": [...], "row_count": int, "sql_executed": str}
    """
    is_safe, err = validate_sql(sql)
    if not is_safe:
        return {"error": err, "sql": sql}

    safe_sql = inject_limit(sql, max_rows=min(limit, 10000))

    try:
        engine = get_engine()
        df = pd.read_sql(safe_sql, engine)

        # 日期列转字符串，避免 JSON 序列化失败
        for col in df.select_dtypes(include=["datetime64", "object"]).columns:
            df[col] = df[col].astype(str)

        return {
            "columns": df.columns.tolist(),
            "rows": df.values.tolist(),
            "row_count": len(df),
            "sql_executed": safe_sql,
        }
    except Exception as exc:
        return {"error": str(exc), "sql_executed": safe_sql}


def get_schema(table_name: str = None, include_sample: bool = True) -> dict[str, Any]:
    """
    获取数据库表结构信息。

    :param table_name:     指定表名（None 则返回所有表）
    :param include_sample: 是否包含样例数据
    :return:               表结构 + 统计信息
    """
    try:
        engine = get_engine()
        inspector = inspect(engine)

        if table_name:
            tables_to_inspect = [table_name]
        else:
            tables_to_inspect = inspector.get_table_names()

        result = {}
        for tname in tables_to_inspect:
            columns = inspector.get_columns(tname)
            col_info = [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                }
                for col in columns
            ]

            # 行数统计
            try:
                with engine.connect() as conn:
                    row = conn.execute(text(f"SELECT COUNT(*) FROM {tname}")).fetchone()
                    row_count = row[0] if row else 0
            except Exception:
                row_count = -1

            # 样例数据
            sample_rows = []
            if include_sample and row_count > 0:
                try:
                    df_sample = pd.read_sql(f"SELECT * FROM {tname} LIMIT 3", engine)
                    for col in df_sample.select_dtypes(include=["datetime64", "object"]).columns:
                        df_sample[col] = df_sample[col].astype(str)
                    sample_rows = df_sample.values.tolist()
                except Exception:
                    pass

            result[tname] = {
                "columns": col_info,
                "row_count": row_count,
                "sample_data": {
                    "columns": [c["name"] for c in col_info],
                    "rows": sample_rows,
                } if include_sample else None,
            }

        return result
    except Exception as exc:
        return {"error": str(exc)}


def run_analysis(code: str, data_context: dict | None = None) -> dict[str, Any]:
    """
    在受限沙箱中执行 Python 数据分析代码。
    data_context 中的变量会注入到执行环境。

    :param code:         Python 分析代码（使用 pandas）
    :param data_context: 可注入的变量（如 {"df": ...}）
    :return:             {"output": str, "result": any}
    """
    import io
    import sys
    import traceback

    # 构建执行环境（包含数据分析常用库）
    import numpy as np
    safe_globals = {
        "__builtins__": __builtins__,   # 允许完整内置函数（含 import）
        "pd": pd,
        "np": np,
        "json": json,
    }
    if data_context:
        safe_globals.update(data_context)

    # 捕获 stdout
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    exec_result = None
    try:
        local_vars = {}
        exec(code, safe_globals, local_vars)  # noqa: S102
        exec_result = local_vars.get("result", None)
        output = captured.getvalue()
    except Exception:
        output = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    # 序列化 result
    if isinstance(exec_result, pd.DataFrame):
        for col in exec_result.select_dtypes(include=["datetime64", "object"]).columns:
            exec_result[col] = exec_result[col].astype(str)
        exec_result = {
            "type": "dataframe",
            "columns": exec_result.columns.tolist(),
            "rows": exec_result.values.tolist(),
            "shape": list(exec_result.shape),
        }
    elif hasattr(exec_result, "to_dict"):
        exec_result = exec_result.to_dict()

    return {
        "output": output[:5000],    # 截断超长输出
        "result": exec_result,
    }
