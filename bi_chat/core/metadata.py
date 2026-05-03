"""
metadata.py — BI 元数据读取模块

从三张元数据表读取 BI 问数所需的完整上下文：
  olap_table_pro              → 表基本信息（表名、中文名、引擎信息等）
  olap_src_table_field_mapping → 字段映射（field_key、中文名、源字段）
  olap_table_plus             → 引擎信息（engine 类型）

兼容 SQLite（本地 Demo）和 MySQL（生产环境）。

对外暴露：
  load_metadata() → list[TableMeta]   完整元数据列表
  format_for_prompt(metas) → str      格式化为 CC Prompt 可读字符串
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

METADATA_DB_URL = os.getenv(
    "METADATA_DB_URL",
    "sqlite:////home/user/webapp/bi_chat/data/demo_meta.db",
)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(METADATA_DB_URL, echo=False, pool_pre_ping=True)
    return _engine


# ────────────────────────────────────────────────
#  数据结构
# ────────────────────────────────────────────────

@dataclass
class FieldMeta:
    field_key: str          # 字段英文名（指标/维度 key）
    field_name: str         # 字段中文名
    src_field: str          # 源表字段名
    src_table_name: str     # 源表名
    etl_type: int = 0       # 0=直接取字段 1=计算字段
    etl_summary: str = ""   # 计算公式（etl_type=1 时有值）


@dataclass
class TableMeta:
    table_id: int
    tb_name: str            # 表英文名
    cn_name: str            # 表中文名
    db_name: str            # 所在库名
    engine: str             # 引擎类型（mysql / clickhouse / hive …）
    theme: str = ""         # 主题
    note: str = ""          # 表注释
    fields: list[FieldMeta] = field(default_factory=list)


# ────────────────────────────────────────────────
#  核心读取逻辑
# ────────────────────────────────────────────────

def load_metadata(
    theme: Optional[str] = None,
    tb_name: Optional[str] = None,
    limit: int = 200,
) -> list[TableMeta]:
    """
    从元数据库读取表 + 字段信息，返回结构化列表。

    :param theme:   可选主题过滤（如 "经营"）
    :param tb_name: 可选表名精确过滤
    :param limit:   最多返回多少张表（防止 Prompt 过大）
    :return:        TableMeta 列表
    """
    try:
        engine = _get_engine()
        return _load_from_db(engine, theme, tb_name, limit)
    except Exception as e:
        # 元数据库不可达时，返回内置演示元数据（开发/测试用）
        print(f"[metadata] 数据库读取失败({e})，降级到内置 Demo 元数据")
        return _demo_metadata()


def _extract_engine_from_infos(engine_infos_str: Optional[str], plus_engine: Optional[str]) -> str:
    """
    从 engine_infos JSON 字符串或 olap_table_plus.engine 列提取引擎名称。
    兼容 SQLite 和 MySQL（MySQL 版可用 JSON_UNQUOTE，SQLite 只能 Python 解析）。
    """
    if plus_engine:
        return plus_engine

    if engine_infos_str:
        try:
            data = json.loads(engine_infos_str)
            if isinstance(data, dict):
                return data.get("engine", "unknown")
        except (json.JSONDecodeError, TypeError):
            pass

    return "unknown"


def _load_from_db(engine, theme, tb_name, limit) -> list[TableMeta]:
    """从真实数据库读取元数据（兼容 SQLite / MySQL）"""

    # ── Step1: 读取表基本信息 ──────────────────────────────────
    # 注意：不使用 MySQL 专属的 JSON_UNQUOTE/JSON_EXTRACT，用 Python 解析
    where_clauses = ["p.status = 3"]
    params: dict = {}

    if theme:
        where_clauses.append("p.theme LIKE :theme")
        params["theme"] = f"%{theme}%"
    if tb_name:
        where_clauses.append("p.tb_name = :tb_name")
        params["tb_name"] = tb_name

    where_sql = " AND ".join(where_clauses)

    table_sql = f"""
        SELECT
            p.id            AS table_id,
            p.tb_name,
            COALESCE(p.cn_name, p.tb_cn_name, p.note) AS cn_name,
            p.db_name,
            p.theme,
            p.note,
            p.engine_infos,
            pl.engine       AS plus_engine
        FROM olap_table_pro p
        LEFT JOIN olap_table_plus pl ON pl.table_id = p.id
        WHERE {where_sql}
        ORDER BY p.id
        LIMIT :limit
    """
    params["limit"] = limit

    with engine.connect() as conn:
        table_rows = conn.execute(text(table_sql), params).fetchall()

    if not table_rows:
        return []

    table_ids = [r.table_id for r in table_rows]

    # ── Step2: 批量读取字段映射 ────────────────────────────────
    id_placeholders = ", ".join(f":id_{i}" for i in range(len(table_ids)))
    field_sql = f"""
        SELECT
            f.table_id,
            f.field_key,
            COALESCE(f.field_name, f.field_key) AS field_name,
            f.src_field,
            COALESCE(f.src_table_name, '') AS src_table_name,
            COALESCE(f.etl_type, 0)        AS etl_type,
            COALESCE(f.etl_summary, '')    AS etl_summary
        FROM olap_src_table_field_mapping f
        WHERE f.table_id IN ({id_placeholders})
          AND f.status = 1
        ORDER BY f.table_id, f.id
    """
    field_params = {f"id_{i}": tid for i, tid in enumerate(table_ids)}

    with engine.connect() as conn:
        field_rows = conn.execute(text(field_sql), field_params).fetchall()

    # ── Step3: 组装 TableMeta ──────────────────────────────────
    field_map: dict[int, list[FieldMeta]] = {}
    for fr in field_rows:
        fmeta = FieldMeta(
            field_key=fr.field_key or "",
            field_name=fr.field_name or fr.field_key or "",
            src_field=fr.src_field or "",
            src_table_name=fr.src_table_name or "",
            etl_type=fr.etl_type or 0,
            etl_summary=fr.etl_summary or "",
        )
        field_map.setdefault(fr.table_id, []).append(fmeta)

    result: list[TableMeta] = []
    for tr in table_rows:
        engine_name = _extract_engine_from_infos(
            getattr(tr, "engine_infos", None),
            getattr(tr, "plus_engine", None),
        )
        result.append(TableMeta(
            table_id=tr.table_id,
            tb_name=tr.tb_name or "",
            cn_name=tr.cn_name or tr.tb_name or "",
            db_name=tr.db_name or "",
            engine=engine_name,
            theme=tr.theme or "",
            note=tr.note or "",
            fields=field_map.get(tr.table_id, []),
        ))

    return result


# ────────────────────────────────────────────────
#  格式化为 Prompt 文本
# ────────────────────────────────────────────────

def format_for_prompt(metas: list[TableMeta]) -> str:
    """
    将元数据列表格式化为 Claude Code Prompt 可读的文本块。
    控制每张表最多展示 50 个字段，防止 Prompt 过长。
    """
    if not metas:
        return "（暂无可用元数据）"

    lines: list[str] = ["## 可用数据表元数据\n"]
    for tm in metas:
        lines.append(f"### 表名: {tm.tb_name}（{tm.cn_name}）")
        lines.append(f"- 库名: {tm.db_name}")
        lines.append(f"- 引擎: {tm.engine}")
        if tm.theme:
            lines.append(f"- 主题: {tm.theme}")
        if tm.note:
            lines.append(f"- 说明: {tm.note}")

        if tm.fields:
            lines.append("- 字段列表（field_key | 中文名 | 源字段）:")
            for f in tm.fields[:50]:
                formula = f" [计算: {f.etl_summary}]" if f.etl_type == 1 and f.etl_summary else ""
                lines.append(f"  · {f.field_key} | {f.field_name} | {f.src_field}{formula}")
            if len(tm.fields) > 50:
                lines.append(f"  · ... 共 {len(tm.fields)} 个字段（已截断）")
        else:
            lines.append("- 字段列表: （暂无）")

        lines.append("")  # 空行分隔

    return "\n".join(lines)


# ────────────────────────────────────────────────
#  本地 Demo 元数据（无数据库时兜底）
# ────────────────────────────────────────────────

def _demo_metadata() -> list[TableMeta]:
    """开发/测试用演示元数据，模拟电商经营指标表（无 DB 时兜底）"""
    return [
        TableMeta(
            table_id=1,
            tb_name="dws_order_daily_agg",
            cn_name="订单每日汇总",
            db_name="bi_data",
            engine="mysql",
            theme="经营",
            note="每日订单量、GMV 汇总表",
            fields=[
                FieldMeta("stat_date",      "统计日期",   "stat_date",      "ods_order", 0, ""),
                FieldMeta("city",           "城市",       "city",           "ods_order", 0, ""),
                FieldMeta("channel",        "渠道",       "channel",        "ods_order", 0, ""),
                FieldMeta("order_cnt",      "订单量",     "order_cnt",      "ods_order", 0, ""),
                FieldMeta("gmv",            "GMV",        "gmv",            "ods_order", 0, ""),
                FieldMeta("revenue",        "实收收入",   "revenue",        "ods_order", 0, ""),
                FieldMeta("cost",           "成本",       "cost",           "ods_order", 0, ""),
                FieldMeta("profit",         "利润",       "profit",         "ods_order", 1, "revenue - cost"),
                FieldMeta("target_revenue", "目标收入",   "target_revenue", "ods_order", 0, ""),
                FieldMeta("complete_rate",  "完成率",     "complete_rate",  "ods_order", 1, "revenue / target_revenue"),
            ],
        ),
        TableMeta(
            table_id=2,
            tb_name="dws_user_behavior_daily",
            cn_name="用户行为每日汇总",
            db_name="bi_data",
            engine="mysql",
            theme="用户",
            note="DAU、新用户、留存等用户行为指标",
            fields=[
                FieldMeta("stat_date",      "统计日期", "stat_date",      "ods_user", 0, ""),
                FieldMeta("city",           "城市",     "city",           "ods_user", 0, ""),
                FieldMeta("dau",            "日活用户", "dau",            "ods_user", 0, ""),
                FieldMeta("new_user_cnt",   "新增用户", "new_user_cnt",   "ods_user", 0, ""),
                FieldMeta("retention_rate", "次日留存", "retention_rate", "ods_user", 0, ""),
            ],
        ),
    ]
