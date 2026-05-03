"""
scripts/init_demo_meta.py — 初始化 Demo 元数据库

创建三张元数据表并写入演示数据：
  olap_table_pro                 → 表基本信息
  olap_src_table_field_mapping   → 字段映射
  olap_table_plus                → 引擎扩展信息
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from sqlalchemy import create_engine, text

METADATA_DB_URL = os.getenv(
    "METADATA_DB_URL",
    "sqlite:////home/user/webapp/bi_chat/data/demo_meta.db",
)

Path("/home/user/webapp/bi_chat/data").mkdir(parents=True, exist_ok=True)
engine = create_engine(METADATA_DB_URL, echo=False)


def create_tables():
    with engine.connect() as conn:
        # ── olap_table_pro ─────────────────────────────────────
        conn.execute(text("DROP TABLE IF EXISTS olap_table_pro"))
        conn.execute(text("""
            CREATE TABLE olap_table_pro (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                plus_id         INTEGER,
                db_name         VARCHAR(100),
                tb_name         VARCHAR(200),
                cn_name         VARCHAR(200),
                tb_cn_name      VARCHAR(200),
                note            TEXT,
                type            INTEGER DEFAULT 1,
                status          INTEGER DEFAULT 3,
                owner_name      VARCHAR(100),
                owner_email     VARCHAR(200),
                modify_name     VARCHAR(100),
                modify_email    VARCHAR(200),
                modify_time     DATETIME,
                create_time     DATETIME DEFAULT CURRENT_TIMESTAMP,
                engine_infos    TEXT,
                theme           VARCHAR(100),
                theme_key       VARCHAR(100),
                type_key        VARCHAR(100),
                model_type      INTEGER DEFAULT 0,
                tb_type         INTEGER DEFAULT 0,
                tenant_id       INTEGER DEFAULT 1
            )
        """))

        # ── olap_src_table_field_mapping ───────────────────────
        conn.execute(text("DROP TABLE IF EXISTS olap_src_table_field_mapping"))
        conn.execute(text("""
            CREATE TABLE olap_src_table_field_mapping (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                table_id        INTEGER NOT NULL,
                field_key       VARCHAR(200),
                field_name      VARCHAR(200),
                basic_id        INTEGER,
                is_customize    INTEGER DEFAULT 0,
                src_table_name  VARCHAR(200),
                src_field       VARCHAR(200),
                etl_type        INTEGER DEFAULT 0,
                etl_summary     TEXT,
                status          INTEGER DEFAULT 1,
                src_field_type  VARCHAR(50),
                create_time     DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # ── olap_table_plus ────────────────────────────────────
        conn.execute(text("DROP TABLE IF EXISTS olap_table_plus"))
        conn.execute(text("""
            CREATE TABLE olap_table_plus (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                engine          VARCHAR(100),
                instance_id     INTEGER,
                instance_name   VARCHAR(200),
                datasource_id   INTEGER,
                db_name         VARCHAR(100),
                table_id        INTEGER NOT NULL,
                table_name      VARCHAR(200),
                type            INTEGER DEFAULT 1,
                created_time    DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_name    VARCHAR(100),
                tenant_id       INTEGER DEFAULT 1,
                time_granularity VARCHAR(50)
            )
        """))
        conn.commit()
    print("✅ 元数据表结构创建完成")


def seed_tables():
    """插入两张演示 BI 表的元数据"""
    tables = [
        {
            "id": 1, "db_name": "bi_data",
            "tb_name": "dws_order_daily_agg",
            "cn_name": "订单每日汇总",
            "tb_cn_name": "订单每日汇总",
            "note": "每日订单量、GMV、收入、成本、利润汇总表，按城市/渠道分组",
            "status": 3, "theme": "经营", "theme_key": "operation",
            "owner_name": "数仓团队",
            "engine_infos": '{"engine":"mysql","instance":"prod_mysql"}',
            "tenant_id": 1,
        },
        {
            "id": 2, "db_name": "bi_data",
            "tb_name": "dws_user_behavior_daily",
            "cn_name": "用户行为每日汇总",
            "tb_cn_name": "用户行为每日汇总",
            "note": "DAU、新用户数、次日留存率，按城市分组",
            "status": 3, "theme": "用户", "theme_key": "user",
            "owner_name": "数仓团队",
            "engine_infos": '{"engine":"mysql","instance":"prod_mysql"}',
            "tenant_id": 1,
        },
    ]

    with engine.connect() as conn:
        for t in tables:
            conn.execute(text("""
                INSERT INTO olap_table_pro
                (id, db_name, tb_name, cn_name, tb_cn_name, note, status,
                 theme, theme_key, owner_name, engine_infos, tenant_id)
                VALUES
                (:id, :db_name, :tb_name, :cn_name, :tb_cn_name, :note, :status,
                 :theme, :theme_key, :owner_name, :engine_infos, :tenant_id)
            """), t)
        conn.commit()
    print(f"✅ olap_table_pro 插入 {len(tables)} 条")


def seed_table_plus():
    """插入 olap_table_plus（引擎信息）"""
    rows = [
        {"id": 1, "engine": "mysql", "table_id": 1,
         "table_name": "dws_order_daily_agg", "db_name": "bi_data",
         "instance_name": "prod_mysql", "tenant_id": 1},
        {"id": 2, "engine": "mysql", "table_id": 2,
         "table_name": "dws_user_behavior_daily", "db_name": "bi_data",
         "instance_name": "prod_mysql", "tenant_id": 1},
    ]
    with engine.connect() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO olap_table_plus
                (id, engine, table_id, table_name, db_name, instance_name, tenant_id)
                VALUES (:id, :engine, :table_id, :table_name, :db_name, :instance_name, :tenant_id)
            """), r)
        conn.commit()
    print(f"✅ olap_table_plus 插入 {len(rows)} 条")


def seed_fields():
    """插入字段映射"""
    # 订单汇总表字段
    order_fields = [
        (1, "stat_date",      "统计日期",       "stat_date",      "dws_order_daily_agg", 0, "",                         "DATE"),
        (1, "city",           "城市",           "city",           "dws_order_daily_agg", 0, "",                         "VARCHAR"),
        (1, "channel",        "渠道",           "channel",        "dws_order_daily_agg", 0, "",                         "VARCHAR"),
        (1, "order_cnt",      "订单量",         "order_cnt",      "dws_order_daily_agg", 0, "",                         "INTEGER"),
        (1, "gmv",            "GMV",            "gmv",            "dws_order_daily_agg", 0, "",                         "REAL"),
        (1, "revenue",        "实收收入",       "revenue",        "dws_order_daily_agg", 0, "",                         "REAL"),
        (1, "cost",           "成本",           "cost",           "dws_order_daily_agg", 0, "",                         "REAL"),
        (1, "profit",         "利润",           "profit",         "dws_order_daily_agg", 1, "revenue - cost",           "REAL"),
        (1, "target_revenue", "目标收入",       "target_revenue", "dws_order_daily_agg", 0, "",                         "REAL"),
        (1, "complete_rate",  "收入完成率",     "complete_rate",  "dws_order_daily_agg", 1, "revenue / target_revenue", "REAL"),
    ]
    # 用户行为表字段
    user_fields = [
        (2, "stat_date",      "统计日期",   "stat_date",      "dws_user_behavior_daily", 0, "", "DATE"),
        (2, "city",           "城市",       "city",           "dws_user_behavior_daily", 0, "", "VARCHAR"),
        (2, "dau",            "日活用户数", "dau",            "dws_user_behavior_daily", 0, "", "INTEGER"),
        (2, "new_user_cnt",   "新增用户数", "new_user_cnt",   "dws_user_behavior_daily", 0, "", "INTEGER"),
        (2, "retention_rate", "次日留存率", "retention_rate", "dws_user_behavior_daily", 0, "", "REAL"),
    ]

    all_fields = order_fields + user_fields
    with engine.connect() as conn:
        for i, (tid, fkey, fname, src_f, src_t, etl_t, etl_s, ftype) in enumerate(all_fields, 1):
            conn.execute(text("""
                INSERT INTO olap_src_table_field_mapping
                (id, table_id, field_key, field_name, src_field, src_table_name,
                 etl_type, etl_summary, status, src_field_type)
                VALUES
                (:id, :table_id, :field_key, :field_name, :src_field, :src_table_name,
                 :etl_type, :etl_summary, :status, :src_field_type)
            """), {
                "id": i, "table_id": tid, "field_key": fkey, "field_name": fname,
                "src_field": src_f, "src_table_name": src_t,
                "etl_type": etl_t, "etl_summary": etl_s,
                "status": 1, "src_field_type": ftype,
            })
        conn.commit()
    print(f"✅ olap_src_table_field_mapping 插入 {len(all_fields)} 条")


if __name__ == "__main__":
    print("🚀 初始化 Demo 元数据库...")
    create_tables()
    seed_tables()
    seed_table_plus()
    seed_fields()
    print(f"\n🎉 完成！元数据库: {METADATA_DB_URL}")
