"""
初始化 Demo 数据库 - 生成 orders / users / products 三张演示表
包含 6 个月的模拟电商数据
"""

import os
import sys
import random
from datetime import datetime, timedelta

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/demo.db")

# 确保 data 目录存在
os.makedirs("data", exist_ok=True)

engine = create_engine(DATABASE_URL, echo=False)

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆"]
CATEGORIES = ["电子数码", "服装鞋包", "食品饮料", "家居家电", "美妆护肤", "图书文具", "运动户外", "母婴用品"]
PRODUCTS = [
    ("iPhone 15", "电子数码", 5999), ("AirPods Pro", "电子数码", 1999),
    ("MacBook Air", "电子数码", 9999), ("小米14", "电子数码", 3999),
    ("耐克运动鞋", "服装鞋包", 899), ("优衣库外套", "服装鞋包", 399),
    ("农夫山泉箱装", "食品饮料", 29), ("星巴克礼盒", "食品饮料", 188),
    ("戴森吸尘器", "家居家电", 3299), ("小熊电饭煲", "家居家电", 299),
    ("兰蔻面霜", "美妆护肤", 880), ("SK-II精华", "美妆护肤", 1290),
    ("Python编程书", "图书文具", 89), ("笔记本文具套装", "图书文具", 49),
    ("Keep哑铃套装", "运动户外", 299), ("迪卡侬跑步鞋", "运动户外", 399),
    ("帮宝适纸尿裤", "母婴用品", 189), ("好奇奶粉", "母婴用品", 360),
]
STATUSES = ["completed", "completed", "completed", "completed", "refunded", "cancelled"]


def create_tables():
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS orders"))
        conn.execute(text("DROP TABLE IF EXISTS users"))
        conn.execute(text("DROP TABLE IF EXISTS products"))

        conn.execute(text("""
            CREATE TABLE users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT NOT NULL,
                age        INTEGER,
                city       TEXT,
                gender     TEXT,
                register_date DATE
            )
        """))

        conn.execute(text("""
            CREATE TABLE products (
                product_id   INTEGER PRIMARY KEY,
                name         TEXT NOT NULL,
                category     TEXT,
                price        REAL,
                stock        INTEGER
            )
        """))

        conn.execute(text("""
            CREATE TABLE orders (
                order_id     INTEGER PRIMARY KEY,
                user_id      INTEGER,
                product_id   INTEGER,
                product_name TEXT,
                category     TEXT,
                city         TEXT,
                amount       REAL,
                quantity     INTEGER,
                status       TEXT,
                created_at   DATETIME
            )
        """))
        conn.commit()
    print("✅ 表结构创建完成")


def seed_users(n=2000):
    rows = []
    base_date = datetime(2024, 1, 1)
    for i in range(1, n + 1):
        rows.append({
            "user_id": i,
            "username": f"user_{i:04d}",
            "age": random.randint(18, 60),
            "city": random.choice(CITIES),
            "gender": random.choice(["M", "F"]),
            "register_date": (base_date + timedelta(days=random.randint(0, 480))).strftime("%Y-%m-%d"),
        })
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO users (user_id, username, age, city, gender, register_date)
            VALUES (:user_id,:username,:age,:city,:gender,:register_date)
        """), rows)
        conn.commit()
    print(f"✅ 插入 {n} 条用户数据")


def seed_products():
    rows = []
    for idx, (name, category, price) in enumerate(PRODUCTS, start=1):
        rows.append({
            "product_id": idx,
            "name": name,
            "category": category,
            "price": price,
            "stock": random.randint(50, 500),
        })
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO products (product_id, name, category, price, stock)
            VALUES (:product_id,:name,:category,:price,:stock)
        """), rows)
        conn.commit()
    print(f"✅ 插入 {len(PRODUCTS)} 条商品数据")


def seed_orders(n=20000):
    rows = []
    base_date = datetime(2024, 11, 1)
    end_date  = datetime(2025, 4, 30)
    delta_days = (end_date - base_date).days

    for i in range(1, n + 1):
        product_idx = random.randint(0, len(PRODUCTS) - 1)
        name, category, price = PRODUCTS[product_idx]

        # 模拟趋势：4月份订单量较高（造成"异常"波动）
        order_date = base_date + timedelta(days=random.randint(0, delta_days))
        if order_date.month == 4 and random.random() < 0.3:
            order_date += timedelta(days=random.randint(-3, 3))

        qty = random.randint(1, 3)
        # 价格有±10%浮动
        actual_price = round(price * random.uniform(0.9, 1.1), 2)

        rows.append({
            "order_id":     i,
            "user_id":      random.randint(1, 2000),
            "product_id":   product_idx + 1,
            "product_name": name,
            "category":     category,
            "city":         random.choice(CITIES),
            "amount":       round(actual_price * qty, 2),
            "quantity":     qty,
            "status":       random.choice(STATUSES),
            "created_at":   order_date.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # 分批插入
    batch = 500
    with engine.connect() as conn:
        for start in range(0, len(rows), batch):
            conn.execute(text("""
                INSERT INTO orders
                (order_id,user_id,product_id,product_name,category,city,amount,quantity,status,created_at)
                VALUES
                (:order_id,:user_id,:product_id,:product_name,:category,:city,:amount,:quantity,:status,:created_at)
            """), rows[start:start + batch])
        conn.commit()
    print(f"✅ 插入 {n} 条订单数据（时间范围：2024-11 ~ 2025-04）")


if __name__ == "__main__":
    print("🚀 初始化 Demo 数据库...")
    create_tables()
    seed_users()
    seed_products()
    seed_orders()
    print("\n🎉 Demo 数据初始化完成！")
    print(f"   数据库: {DATABASE_URL}")
    print("   表: users(2000) / products(18) / orders(20000)")
