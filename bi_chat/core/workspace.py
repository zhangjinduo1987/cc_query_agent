"""
workspace.py — 用户目录隔离 + CLAUDE.md 管理

每个 user_id 拥有完全独立的目录：
  {CC_WORKSPACE_ROOT}/{user_id}/
      CLAUDE.md        ← 用户个人规则、偏好、记忆

对外暴露：
  get_user_dir(user_id)          → Path   用户工作目录（自动创建）
  get_claude_md_path(user_id)    → Path   CLAUDE.md 路径
  read_claude_md(user_id)        → str    读取内容（不存在返回默认模板）
  write_claude_md(user_id, content) → None 写入内容
  get_mcp_config_path(user_id)   → Path   该用户的 mcp_config.json 路径
  ensure_mcp_config(user_id)     → Path   生成/更新 mcp_config.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# 工作区根目录，默认 ./cc_workspace（相对于 bi_chat/）
_WORKSPACE_ROOT = Path(
    os.getenv("CC_WORKSPACE_ROOT", "./cc_workspace")
).resolve()

# MCP server 脚本绝对路径
_MCP_SERVER_SCRIPT = Path(__file__).parent.parent / "mcp" / "server.py"

# 元数据库 URL（传给 MCP Server 进程环境变量）
_METADATA_DB_URL = os.getenv("METADATA_DB_URL", "")
_BI_DB_URL = os.getenv("BI_DB_URL", "")


# ────────────────────────────────────────────────
#  CLAUDE.md 默认模板
# ────────────────────────────────────────────────

_DEFAULT_CLAUDE_MD = """\
# 用户个人规则与偏好

## 展示字段规则
（暂无自定义规则，将展示所有可用核心指标）

## 默认过滤口径
（暂无，查询时使用原始数据）

## 指标展示偏好
（暂无）

## 个人记忆 / 上下文
（暂无）
"""


# ────────────────────────────────────────────────
#  目录和文件管理
# ────────────────────────────────────────────────

def get_user_dir(user_id: str) -> Path:
    """
    返回用户独立工作目录，不存在则自动创建。
    路径: {CC_WORKSPACE_ROOT}/{user_id}/
    """
    user_dir = _WORKSPACE_ROOT / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_claude_md_path(user_id: str) -> Path:
    """返回用户 CLAUDE.md 的绝对路径"""
    return get_user_dir(user_id) / "CLAUDE.md"


def read_claude_md(user_id: str) -> str:
    """
    读取用户 CLAUDE.md 内容。
    若文件不存在，自动用默认模板初始化并写入后返回。
    """
    path = get_claude_md_path(user_id)
    if not path.exists():
        write_claude_md(user_id, _DEFAULT_CLAUDE_MD)
        return _DEFAULT_CLAUDE_MD
    return path.read_text(encoding="utf-8")


def write_claude_md(user_id: str, content: str) -> None:
    """将 content 写入用户 CLAUDE.md（全量覆盖）"""
    path = get_claude_md_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ────────────────────────────────────────────────
#  MCP 配置管理
# ────────────────────────────────────────────────

def get_mcp_config_path(user_id: str) -> Path:
    """返回用户专属 mcp_config.json 路径"""
    return get_user_dir(user_id) / "mcp_config.json"


def ensure_mcp_config(user_id: str) -> Path:
    """
    生成或刷新用户专属 mcp_config.json。
    每次启动 Agent 前调用，确保配置是最新的。
    返回配置文件 Path。
    """
    config = {
        "mcpServers": {
            "bi_tools": {
                "command": "python3",
                "args": [str(_MCP_SERVER_SCRIPT)],
                "env": {
                    "BI_DB_URL": _BI_DB_URL,
                    "METADATA_DB_URL": _METADATA_DB_URL,
                    # 将项目根目录注入 PYTHONPATH，使 mcp/server.py 能 import bi_chat.*
                    "PYTHONPATH": str(Path(__file__).parent.parent.parent),
                },
            }
        }
    }
    config_path = get_mcp_config_path(user_id)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config_path
