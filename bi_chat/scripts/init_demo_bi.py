"""
scripts/init_demo_bi.py — 初始化 Demo BI 数据库

创建两张演示表：
  dws_order_daily_agg      → 订单每日汇总（6个月数据）
  dws_user_behavior_daily  → 用户行为每日汇总
"""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from sqlalchemy import create_engine, text

BI_DB_URL = os.getenv("BI_DB_URL", "sqlite:///./bi_chat/data/demo_bi.db")
Path("bi_chat/data").mkdir(parents=True, exist_ok=True)

engine = create_engine(BI_DB_URL, echo=False)

CITIES   = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京"]
CHANNELS = ["app", "小程序", "web", "门店"]


def create_tables():
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS dws_order_daily_agg"))
        conn.execute(text("DROP TABLE IF EXISTS dws_user_behavior_daily"))

        conn.execute(text("""
            CREATE TABLE dws_order_daily_agg (
                stat_date       DATE,
                city            VARCHAR(50),
                channel         VARCHAR(50),
                order_cnt       INTEGER,
                gmv             REAL,
                revenue         REAL,
                cost            REAL,
                profit          REAL,
                target_revenue  REAL,
                complete_rate   REAL
            )
        """))

        conn.execute(text("""
            CREATE TABLE dws_user_behavior_daily (
                stat_date       DATE,
                city            VARCHAR(50),
                dau             INTEGER,
                new_user_cnt    INTEGER,
                retention_rate  REAL
            )
        """))
        conn.commit()
    print("✅ 表结构创建完成")


def seed_orders(days: int = 180):
    rows = []
    base = datetime.today() - timedelta(days=days)
    for d in range(days):
        dt = (base + timedelta(days=d)).strftime("%Y-%m-%d")
        # 4月份模拟高峰
        peak = 1.4 if (base + timedelta(days=d)).month == 4 else 1.0
        for city in CITIES:
            for ch in CHANNELS:
                order_cnt = int(random.randint(80, 300) * peak)
                gmv = round(order_cnt * random.uniform(150, 400), 2)
                revenue = round(gmv * random.uniform(0.78, 0.92), 2)
                cost = round(revenue * random.uniform(0.55, 0.70), 2)
                profit = round(revenue - cost, 2)
                target_revenue = round(revenue * random.uniform(0.90, 1.15), 2)
                complete_rate = round(revenue / target_revenue, 4) if target_revenue else 0
                rows.append({
                    "stat_date": dt, "city": city, "channel": ch,
                    "order_cnt": order_cnt, "gmv": gmv, "revenue": revenue,
                    "cost": cost, "profit": profit,
                    "target_revenue": target_revenue, "complete_rate": complete_rate,
                })
    with engine.connect() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO dws_order_daily_agg
                (stat_date,city,channel,order_cnt,gmv,revenue,cost,profit,target_revenue,complete_rate)
                VALUES (:stat_date,:city,:channel,:order_cnt,:gmv,:revenue,:cost,:profit,:target_revenue,:complete_rate)
            """), r)
        conn.commit()
    print(f"✅ 订单数据插入完成：{len(rows)} 条")


def seed_users(days: int = 180):
    rows = []
    base = datetime.today() - timedelta(days=days)
    for d in range(days):
        dt = (base + timedelta(days=d)).strftime("%Y-%m-%d")
        for city in CITIES:
            dau = random.randint(2000, 8000)
            new_user_cnt = int(dau * random.uniform(0.05, 0.18))
            retention_rate = round(random.uniform(0.30, 0.55), 4)
            rows.append({
                "stat_date": dt, "city": city,
                "dau": dau, "new_user_cnt": new_user_cnt,
                "retention_rate": retention_rate,
            })
    with engine.connect() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO dws_user_behavior_daily
                (stat_date,city,dau,new_user_cnt,retention_rate)
                VALUES (:stat_date,:city,:dau,:new_user_cnt,:retention_rate)
            """), r)
        conn.commit()
    print(f"✅ 用户行为数据插入完成：{len(rows)} 条")


if __name__ == "__main__":
    print("🚀 初始化 BI Demo 数据库...")
    create_tables()
    seed_orders()
    seed_users()
    print(f"\n🎉 完成！数据库: {BI_DB_URL}")
