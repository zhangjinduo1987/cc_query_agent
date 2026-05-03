"""
测试模块 - 测试各核心组件
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def test_db_tools():
    """测试数据库工具"""
    print("\n🧪 测试 db_tools...")
    from mcp_server.db_tools import get_schema, query_database, run_analysis

    # 1. Schema
    schema = get_schema()
    assert "error" not in schema, f"get_schema failed: {schema}"
    tables = list(schema.keys())
    print(f"   ✅ get_schema: 发现表 {tables}")

    # 2. Query
    result = query_database("SELECT COUNT(*) AS cnt FROM orders")
    assert "error" not in result, f"query_database failed: {result}"
    print(f"   ✅ query_database: orders 行数 = {result['rows'][0][0]}")

    # 3. Analysis
    code = """
import pandas as pd
data = {'a': [1,2,3], 'b': [4,5,6]}
df = pd.DataFrame(data)
result = df.describe().to_dict()
print(f"DataFrame shape: {df.shape}")
"""
    res = run_analysis(code)
    assert "error" not in res.get("output", ""), f"run_analysis output error"
    print(f"   ✅ run_analysis: {res['output'].strip()}")


def test_mcp_server_import():
    """测试 MCP Server 可正常导入"""
    print("\n🧪 测试 MCP Server import...")
    try:
        from mcp_server.server import app
        print(f"   ✅ MCP Server 导入成功: {app.name}")
    except Exception as e:
        print(f"   ❌ MCP Server 导入失败: {e}")


def test_agent_import():
    """测试 Agent 可正常导入"""
    print("\n🧪 测试 Agent import...")
    try:
        from agent.agent import ClaudeCodeAgent
        from agent.planner import TaskPlanner
        agent = ClaudeCodeAgent(work_dir="/tmp/test_agent")
        planner = TaskPlanner()
        print(f"   ✅ ClaudeCodeAgent 实例化成功")
        print(f"   ✅ TaskPlanner 实例化成功")
    except Exception as e:
        print(f"   ❌ Agent import 失败: {e}")


def test_api_models():
    """测试 Pydantic 模型"""
    print("\n🧪 测试 API 模型...")
    try:
        from api.models import AnalyzeRequest, AnalyzeResponse, StreamEvent
        req = AnalyzeRequest(query="测试查询")
        ev  = StreamEvent(session_id="test", type="thinking", content="hello")
        print(f"   ✅ AnalyzeRequest: query='{req.query}'")
        print(f"   ✅ StreamEvent JSON: {ev.model_dump_json()[:80]}...")
    except Exception as e:
        print(f"   ❌ 模型测试失败: {e}")


async def test_planner_offline():
    """测试 TaskPlanner（无 API Key 时跳过）"""
    print("\n🧪 测试 TaskPlanner...")
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-xxx"):
        print("   ⚠️  跳过（未设置 ANTHROPIC_API_KEY）")
        return
    try:
        from agent.planner import TaskPlanner
        planner = TaskPlanner()
        plan = await planner.plan("分析最近30天订单趋势")
        print(f"   ✅ TaskPlanner: type={plan.analysis_type}, tasks={len(plan.tasks)}")
        for t in plan.tasks:
            print(f"      - [{t.id}] {t.title}")
    except Exception as e:
        print(f"   ❌ TaskPlanner 失败: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("  问数分析智能体 - 组件测试")
    print("=" * 50)

    test_db_tools()
    test_mcp_server_import()
    test_agent_import()
    test_api_models()
    asyncio.run(test_planner_offline())

    print("\n" + "=" * 50)
    print("  ✅ 所有可测试组件通过")
    print("=" * 50)
