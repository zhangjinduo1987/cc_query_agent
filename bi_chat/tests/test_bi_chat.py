"""
tests/test_bi_chat.py — BI Chat 完整组件测试

覆盖：
  1. 元数据读取（从 SQLite demo_meta.db）
  2. 工作区隔离（CLAUDE.md 读写）
  3. MCP SQL 构建 + 执行
  4. 意图分类（关键词兜底，无需 API Key）
  5. FastAPI 路由健康检查
  6. /api/chat 端点（mock CC CLI）
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── 强制使用 SQLite demo ───────────────────────────────────────
os.environ.setdefault(
    "METADATA_DB_URL",
    "sqlite:////home/user/webapp/bi_chat/data/demo_meta.db",
)
os.environ.setdefault(
    "BI_DB_URL",
    "sqlite:////home/user/webapp/bi_chat/data/demo_bi.db",
)
os.environ.setdefault(
    "CC_WORKSPACE_ROOT",
    "/home/user/webapp/bi_chat/cc_workspace",
)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")


# ════════════════════════════════════════════════════════════
#  1. 元数据读取
# ════════════════════════════════════════════════════════════

class TestMetadata(unittest.TestCase):

    def test_load_metadata_from_sqlite(self):
        """从 SQLite demo 库读取元数据"""
        from bi_chat.core.metadata import load_metadata
        metas = load_metadata()
        self.assertGreater(len(metas), 0, "应至少返回 1 张表")

    def test_table_names_and_fields(self):
        """验证表名、字段数量"""
        from bi_chat.core.metadata import load_metadata
        metas = load_metadata()
        tb_names = [m.tb_name for m in metas]
        self.assertIn("dws_order_daily_agg", tb_names)
        self.assertIn("dws_user_behavior_daily", tb_names)

        order_meta = next(m for m in metas if m.tb_name == "dws_order_daily_agg")
        self.assertEqual(len(order_meta.fields), 10)
        field_keys = [f.field_key for f in order_meta.fields]
        self.assertIn("order_cnt", field_keys)
        self.assertIn("gmv", field_keys)
        self.assertIn("profit", field_keys)

    def test_format_for_prompt(self):
        """格式化为 Prompt 文本"""
        from bi_chat.core.metadata import load_metadata, format_for_prompt
        metas = load_metadata()
        text = format_for_prompt(metas)
        self.assertIn("dws_order_daily_agg", text)
        self.assertIn("field_key", text)

    def test_engine_parsed_from_json(self):
        """engine 应从 engine_infos JSON 中解析"""
        from bi_chat.core.metadata import load_metadata
        metas = load_metadata()
        order_meta = next(m for m in metas if m.tb_name == "dws_order_daily_agg")
        self.assertEqual(order_meta.engine, "mysql")


# ════════════════════════════════════════════════════════════
#  2. 工作区隔离
# ════════════════════════════════════════════════════════════

class TestWorkspace(unittest.TestCase):

    def setUp(self):
        self.uid1 = "test_user_001"
        self.uid2 = "test_user_002"

    def test_user_dirs_isolated(self):
        """不同 user_id 目录完全隔离"""
        from bi_chat.core.workspace import get_user_dir
        d1 = get_user_dir(self.uid1)
        d2 = get_user_dir(self.uid2)
        self.assertNotEqual(str(d1), str(d2))
        self.assertTrue(d1.exists())
        self.assertTrue(d2.exists())

    def test_claude_md_default_created(self):
        """首次读取自动创建默认 CLAUDE.md"""
        from bi_chat.core.workspace import read_claude_md, get_claude_md_path
        uid = "test_new_user_999"
        path = get_claude_md_path(uid)
        if path.exists():
            path.unlink()

        content = read_claude_md(uid)
        self.assertIn("展示字段规则", content)
        self.assertTrue(path.exists())

    def test_write_and_read_claude_md(self):
        """写入 + 读取 CLAUDE.md 一致"""
        from bi_chat.core.workspace import write_claude_md, read_claude_md
        uid = "test_rw_user"
        custom = "# 自定义规则\n- 默认展示利润\n"
        write_claude_md(uid, custom)
        result = read_claude_md(uid)
        self.assertEqual(result, custom)

    def test_mcp_config_generated(self):
        """ensure_mcp_config 应生成有效 JSON"""
        from bi_chat.core.workspace import ensure_mcp_config
        path = ensure_mcp_config(self.uid1)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertIn("mcpServers", data)
        self.assertIn("bi_tools", data["mcpServers"])
        server_cfg = data["mcpServers"]["bi_tools"]
        self.assertEqual(server_cfg["command"], "python3")
        self.assertIn("BI_DB_URL", server_cfg["env"])


# ════════════════════════════════════════════════════════════
#  3. MCP SQL 构建 + 执行
# ════════════════════════════════════════════════════════════

class TestMCPServer(unittest.TestCase):

    def test_build_sql_basic(self):
        """基础 SELECT SQL 构建"""
        from bi_chat.mcp.server import _build_sql
        sql, params = _build_sql({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["stat_date", "order_cnt"],
            "filters": [],
            "limit": 10,
        })
        self.assertIn("SELECT stat_date, order_cnt FROM dws_order_daily_agg", sql)
        self.assertIn("LIMIT 10", sql)

    def test_build_sql_with_filter(self):
        """带过滤条件的 SQL"""
        from bi_chat.mcp.server import _build_sql
        sql, params = _build_sql({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["stat_date", "gmv"],
            "filters": [{"field": "city", "op": "=", "value": "北京"}],
            "limit": 100,
        })
        self.assertIn("WHERE city = :p_0", sql)
        self.assertEqual(params["p_0"], "北京")

    def test_build_sql_group_by(self):
        """GROUP BY + ORDER BY"""
        from bi_chat.mcp.server import _build_sql
        sql, params = _build_sql({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["city", "order_cnt"],
            "filters": [],
            "group_by": ["city"],
            "order_by": [{"field": "order_cnt", "direction": "DESC"}],
            "limit": 8,
        })
        self.assertIn("GROUP BY city", sql)
        self.assertIn("ORDER BY order_cnt DESC", sql)

    def test_build_sql_in_operator(self):
        """IN 操作符"""
        from bi_chat.mcp.server import _build_sql
        sql, params = _build_sql({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["city", "gmv"],
            "filters": [{"field": "city", "op": "IN", "value": ["北京", "上海"]}],
            "limit": 10,
        })
        self.assertIn("IN", sql)
        self.assertIn("p_0_0", params)
        self.assertIn("p_0_1", params)

    def test_sql_injection_blocked(self):
        """SQL 注入防护"""
        from bi_chat.mcp.server import _build_sql
        with self.assertRaises(ValueError):
            _build_sql({
                "tb_name": "dws_order; DROP TABLE dws_order",
                "field_keys": ["stat_date"],
                "filters": [],
                "limit": 10,
            })

    def test_execute_query_real_data(self):
        """对真实 demo BI 数据库执行查询"""
        from bi_chat.mcp.server import _execute_query
        result = _execute_query({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["stat_date", "order_cnt", "gmv"],
            "filters": [],
            "order_by": [{"field": "stat_date", "direction": "DESC"}],
            "limit": 5,
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["columns"], ["stat_date", "order_cnt", "gmv"])
        self.assertGreater(result["row_count"], 0)

    def test_execute_query_with_aggregation(self):
        """聚合查询（SUM）"""
        from bi_chat.mcp.server import _execute_query
        result = _execute_query({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["city", "order_cnt"],
            "filters": [],
            "group_by": ["city"],
            "order_by": [{"field": "order_cnt", "direction": "DESC"}],
            "limit": 10,
        })
        self.assertNotIn("error", result)
        self.assertGreater(result["row_count"], 0)

    def test_limit_capped_at_5000(self):
        """limit 超过 5000 应被截断"""
        from bi_chat.mcp.server import _build_sql
        sql, _ = _build_sql({
            "tb_name": "dws_order_daily_agg",
            "field_keys": ["stat_date"],
            "filters": [],
            "limit": 99999,
        })
        self.assertIn("LIMIT 5000", sql)


# ════════════════════════════════════════════════════════════
#  4. 意图分类（关键词兜底，无需 API）
# ════════════════════════════════════════════════════════════

class TestIntentClassify(unittest.TestCase):

    def test_keyword_fallback_edit_rule(self):
        """含规则关键词 → edit_rule"""
        from bi_chat.core.intent import _keyword_fallback
        cases = [
            "我期望看经营情况时默认展示利润",
            "以后查询默认按城市分组",
            "记住我不需要看成本字段",
            "修改展示字段",
            "设置过滤条件为北京",
        ]
        for q in cases:
            self.assertEqual(_keyword_fallback(q), "edit_rule", f"应为 edit_rule: {q!r}")

    def test_keyword_fallback_query_data(self):
        """数据查询关键词 → query_data"""
        from bi_chat.core.intent import _keyword_fallback
        cases = [
            "查看今天的经营情况",
            "昨天GMV是多少",
            "本周订单量趋势",
            "各城市收入对比",
            "给我看一下本月数据",
        ]
        for q in cases:
            self.assertEqual(_keyword_fallback(q), "query_data", f"应为 query_data: {q!r}")

    @patch("bi_chat.core.intent._get_client")
    def test_intent_classify_api_success(self, mock_get_client):
        """API 调用成功时使用 API 结果"""
        from bi_chat.core.intent import intent_classify
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="query_data")]
        )
        mock_get_client.return_value = mock_client

        result = intent_classify("u_001", "查看本月销售数据")
        self.assertEqual(result, "query_data")

    @patch("bi_chat.core.intent._get_client")
    def test_intent_classify_api_failure_fallback(self, mock_get_client):
        """API 调用失败时降级到关键词兜底"""
        from bi_chat.core.intent import intent_classify
        mock_get_client.side_effect = Exception("API error")

        result = intent_classify("u_001", "期望默认展示利润")
        self.assertEqual(result, "edit_rule")


# ════════════════════════════════════════════════════════════
#  5. FastAPI 路由 + /api/chat 端点
# ════════════════════════════════════════════════════════════

class TestFastAPIRoutes(unittest.TestCase):

    def setUp(self):
        from fastapi.testclient import TestClient
        # patch cc agent to avoid actual claude CLI calls
        self._patcher = patch(
            "bi_chat.core.intent.bi_query",
            new=AsyncMock(return_value="✅ 模拟分析结论：今日 GMV **¥100万**，增长 **+10%**"),
        )
        self._patcher.start()

        # also patch save_rule
        self._patcher2 = patch(
            "bi_chat.core.intent.save_rule",
            new=AsyncMock(return_value="✅ 规则已保存。"),
        )
        self._patcher2.start()

        from bi_chat.main import app
        self.client = TestClient(app)

    def tearDown(self):
        self._patcher.stop()
        self._patcher2.stop()

    def test_health_endpoint(self):
        """GET / 返回服务信息"""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("service", data)

    def test_chat_query_data(self):
        """POST /api/chat - query_data 意图"""
        with patch("bi_chat.core.intent._keyword_fallback", return_value="query_data"):
            with patch("bi_chat.core.intent._get_client") as mock_client:
                mock_client.side_effect = Exception("no api key")
                resp = self.client.post("/api/chat", json={
                    "user_id": "u_001",
                    "question": "查看本月订单量趋势",
                })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["user_id"], "u_001")
        self.assertIn("intent", data)
        self.assertIn("answer", data)

    def test_chat_edit_rule(self):
        """POST /api/chat - edit_rule 意图"""
        with patch("bi_chat.core.intent._get_client") as mock_client:
            mock_client.return_value = MagicMock(
                messages=MagicMock(
                    create=MagicMock(return_value=MagicMock(
                        content=[MagicMock(text="edit_rule")]
                    ))
                )
            )
            resp = self.client.post("/api/chat", json={
                "user_id": "u_001",
                "question": "期望默认展示利润、成本、目标收入完成率",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["user_id"], "u_001")
        self.assertIn("answer", data)

    def test_chat_empty_question(self):
        """空 question 应返回 422"""
        resp = self.client.post("/api/chat", json={
            "user_id": "u_001",
            "question": "",
        })
        self.assertEqual(resp.status_code, 422)

    def test_chat_missing_user_id(self):
        """缺少 user_id 应返回 422"""
        resp = self.client.post("/api/chat", json={
            "question": "查看数据",
        })
        self.assertEqual(resp.status_code, 422)


# ════════════════════════════════════════════════════════════
#  6. save_rule 工作流测试（无需真实 API）
# ════════════════════════════════════════════════════════════

class TestSaveRule(unittest.IsolatedAsyncioTestCase):

    @patch("bi_chat.core.intent._get_client")
    async def test_save_rule_writes_to_claude_md(self, mock_get_client):
        """save_rule 调用后 CLAUDE.md 内容更新"""
        from bi_chat.core.intent import save_rule
        from bi_chat.core.workspace import read_claude_md

        new_md = "# 用户个人规则\n## 展示字段规则\n- 默认展示利润、成本\n"
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=new_md)]
        )
        mock_get_client.return_value = mock_client

        uid = "test_save_rule_user"
        result = await save_rule(uid, "期望默认展示利润和成本")

        self.assertIn("规则已保存", result)
        saved = read_claude_md(uid)
        self.assertIn("默认展示利润", saved)

    @patch("bi_chat.core.intent._get_client")
    async def test_save_rule_api_failure(self, mock_get_client):
        """save_rule API 失败时返回错误提示"""
        from bi_chat.core.intent import save_rule
        mock_get_client.side_effect = Exception("API unreachable")

        result = await save_rule("u_err", "修改规则")
        self.assertIn("失败", result)


# ════════════════════════════════════════════════════════════
#  Runner
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestMetadata))
    suite.addTests(loader.loadTestsFromTestCase(TestWorkspace))
    suite.addTests(loader.loadTestsFromTestCase(TestMCPServer))
    suite.addTests(loader.loadTestsFromTestCase(TestIntentClassify))
    suite.addTests(loader.loadTestsFromTestCase(TestFastAPIRoutes))
    suite.addTests(loader.loadTestsFromTestCase(TestSaveRule))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
