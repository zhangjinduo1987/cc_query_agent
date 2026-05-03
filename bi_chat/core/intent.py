"""
intent.py — 意图识别 + 规则保存 + BI 问数三大核心函数

严格按照需求规范实现：
  intent_classify(user_id, question) → "edit_rule" | "query_data"
  save_rule(user_id, question)       → str  （内部方法，不对外暴露）
  bi_query(user_id, question)        → str  （返回自然语言结论）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import AsyncGenerator

import anthropic
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from bi_chat.core.workspace import (
    read_claude_md,
    write_claude_md,
    ensure_mcp_config,
    get_user_dir,
)
from bi_chat.core.metadata import load_metadata, format_for_prompt

# ── Anthropic 轻量客户端（意图识别用，不消耗 CC 配额）──────────────
_anthropic_client: anthropic.Anthropic | None = None

def _get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client

CC_MAX_TURNS = int(os.getenv("CC_MAX_TURNS", "20"))

# ════════════════════════════════════════════════════════════
#  1. 意图识别
# ════════════════════════════════════════════════════════════

_INTENT_SYSTEM = """\
你是一个意图分类器，只需返回下面两个标签之一，不得输出任何其他内容：
- edit_rule   ：用户想修改规则/偏好/展示字段/口径/过滤条件/记忆，
                关键词：期望、默认、以后、固定、规则、偏好、展示字段、口径、过滤条件、记住、设置
- query_data  ：用户想查数据/指标/报表/统计，
                关键词：查、看、分析、统计、今天、昨天、本周、本月、趋势、对比、报表

只输出 edit_rule 或 query_data，不含空格、标点或换行。
"""

def intent_classify(user_id: str, question: str) -> str:
    """
    意图识别：返回 "edit_rule" 或 "query_data"。
    使用 claude-3-5-haiku 快速推理（<500ms），不走 CC CLI。
    失败时默认降级为 query_data。
    """
    try:
        resp = _get_client().messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": question}],
        )
        raw = resp.content[0].text.strip().lower()
        # 提取核心标签（防止模型多输出字符）
        if "edit_rule" in raw:
            return "edit_rule"
        if "query_data" in raw:
            return "query_data"
        # 关键词兜底规则
        return _keyword_fallback(question)
    except Exception:
        return _keyword_fallback(question)


def _keyword_fallback(question: str) -> str:
    """无 API 时的关键词兜底分类"""
    edit_keywords = ["期望", "默认", "以后", "固定", "规则", "偏好",
                     "展示字段", "口径", "过滤", "记住", "设置", "修改"]
    for kw in edit_keywords:
        if kw in question:
            return "edit_rule"
    return "query_data"


# ════════════════════════════════════════════════════════════
#  2. 规则保存（save_rule）—— 内部方法
# ════════════════════════════════════════════════════════════

_SAVE_RULE_SYSTEM = """\
你是一个 BI 规则管理助手。
你的任务：根据用户的表达，更新 CLAUDE.md 文件中对应的规则内容。

规则：
1. 完整保留 CLAUDE.md 原有其他章节，只更新/追加相关规则
2. 不要新增无关内容，不要删除用户已有的历史规则
3. 输出完整的 CLAUDE.md 文本（Markdown 格式），不含任何额外说明
4. 若用户只说"记住 xxx"，追加到 ## 个人记忆 / 上下文 章节
5. 若用户说展示字段/指标口径，更新 ## 展示字段规则 或 ## 默认过滤口径
"""

async def save_rule(user_id: str, question: str) -> str:
    """
    【内部方法，不对外暴露】
    流程：
      1. 读取该用户 CLAUDE.md 当前内容
      2. 调用 Claude（haiku）理解用户意图并生成更新后的完整 CLAUDE.md
      3. 写回用户目录
      4. 返回"规则已保存"提示
    """
    current_md = read_claude_md(user_id)

    prompt = f"""\
当前 CLAUDE.md 内容：
---
{current_md}
---

用户说：{question}

请输出更新后的完整 CLAUDE.md 内容。
"""
    try:
        resp = _get_client().messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2048,
            system=_SAVE_RULE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        new_md = resp.content[0].text.strip()
        # 去掉可能的 markdown 代码块包裹
        new_md = re.sub(r"^```(?:markdown)?\n?", "", new_md)
        new_md = re.sub(r"\n?```$", "", new_md)
        write_claude_md(user_id, new_md.strip() + "\n")
        return "✅ 规则已保存。您的偏好设置已更新，后续问数将自动应用。"
    except Exception as e:
        return f"⚠️ 规则保存失败：{e}"


# ════════════════════════════════════════════════════════════
#  3. BI 问数核心（bi_query）
# ════════════════════════════════════════════════════════════

# ── CC CLI 系统提示词 ─────────────────────────────────────────
_BI_SYSTEM_PROMPT = """\
你是一个专业的 BI 数据分析智能体。

## 严格执行规则
1. 必须先读取 CLAUDE.md，了解用户的个人规则、偏好和记忆
2. 根据下方提供的【数据表元数据】和 CLAUDE.md 规则，规划查询方案
3. 必须调用 MCP 工具 mcp__bi_tools__query_bi_data 执行数据查询，严禁虚构数据
4. 字段必须来自元数据中存在的 field_key，不允许使用元数据中没有的字段
5. 拿到数据后自行完成计算、汇总、对比分析
6. 最终只输出业务化自然语言结论，不输出 SQL、不输出过程、不输出表格代码块
7. 结论简洁有力，突出关键数字和趋势，每条结论控制在 2 句话内

## 输出格式
直接输出分析结论，使用简洁的 Markdown，例如：
- 今日订单量 **12,345** 单，较昨日增长 **+8.3%**
- GMV **¥234.5万**，完成率 **92%**，距目标还差 **¥19.5万**
"""

_BI_USER_PROMPT_TMPL = """\
## 用户问题
{question}

## 用户个人规则（来自 CLAUDE.md）
{claude_md}

{metadata_str}

## 执行指引
1. 结合用户规则和元数据，确定需要查询哪张表、哪些字段
2. 调用 mcp__bi_tools__query_bi_data 工具查询数据
3. 对返回数据进行计算分析
4. 输出简洁的业务结论
"""


async def bi_query(user_id: str, question: str) -> str:
    """
    BI 问数全流程：
      1. 读取用户 CLAUDE.md
      2. 加载元数据
      3. 构造 Prompt
      4. 调用 Claude Code CLI（stream-json）+ MCP query_bi_data
      5. 提取最终自然语言结论返回
    """
    # ── 准备材料 ──────────────────────────────────────────────
    claude_md   = read_claude_md(user_id)
    metas       = load_metadata()
    metadata_str = format_for_prompt(metas)
    mcp_config  = ensure_mcp_config(user_id)
    work_dir    = get_user_dir(user_id)

    user_prompt = _BI_USER_PROMPT_TMPL.format(
        question=question,
        claude_md=claude_md,
        metadata_str=metadata_str,
    )

    # ── 调用 CC CLI ────────────────────────────────────────────
    report = await _run_cc_agent(
        prompt=user_prompt,
        system_prompt=_BI_SYSTEM_PROMPT,
        work_dir=str(work_dir),
        mcp_config_path=str(mcp_config),
    )
    return report


# ════════════════════════════════════════════════════════════
#  CC CLI 执行引擎（stream-json 解析）
# ════════════════════════════════════════════════════════════

async def _run_cc_agent(
    prompt: str,
    system_prompt: str,
    work_dir: str,
    mcp_config_path: str,
) -> str:
    """
    启动 claude CLI 子进程，stream-json 模式逐行解析事件，
    返回最终 result 文本。
    """
    cmd = [
        "claude",
        "--print",                                          # 非交互模式（-p）
        "--output-format", "stream-json",                  # 流式 JSON 输出
        "--verbose",                                        # stream-json 必须带 --verbose
        "--max-turns", str(CC_MAX_TURNS),                  # 最大轮次
        "--system-prompt", system_prompt,                  # 系统提示词
        "--allowedTools", "mcp__bi_tools__query_bi_data",  # 只允许 BI 查询工具
        "--mcp-config", mcp_config_path,                   # MCP 配置
        "--dangerously-skip-permissions",                  # sandbox 环境跳过权限确认
        prompt,
    ]

    env = _build_env()

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=env,
        )

        result_text = ""
        thinking_chunks: list[str] = []

        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parsed = _parse_stream_line(line)
            if parsed["type"] == "done":
                result_text = parsed["content"]
            elif parsed["type"] == "thinking":
                thinking_chunks.append(parsed["content"])

        await process.wait()

        # 若 result 事件有内容，直接返回
        if result_text.strip():
            return result_text.strip()

        # 降级：返回最后一段 thinking 文本
        if thinking_chunks:
            return thinking_chunks[-1].strip()

        # 读取 stderr 排查问题
        stderr_bytes = await process.stderr.read()
        stderr_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
        if stderr_msg:
            return f"⚠️ 分析执行异常：{stderr_msg[:300]}"

        return "⚠️ 未获取到分析结果，请重试。"

    except FileNotFoundError:
        return "⚠️ 未找到 claude CLI，请确保已安装 Claude Code（npm install -g @anthropic-ai/claude-code）。"
    except Exception as e:
        return f"⚠️ 执行异常：{e}"


def _parse_stream_line(line: str) -> dict:
    """解析 claude stream-json 单行，返回 {type, content} dict"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return {"type": "raw", "content": line}

    event_type = obj.get("type", "")

    if event_type == "assistant":
        blocks = obj.get("message", {}).get("content", [])
        for block in blocks:
            if block.get("type") == "text":
                return {"type": "thinking", "content": block.get("text", "")}
            if block.get("type") == "tool_use":
                return {
                    "type": "tool_call",
                    "content": f"调用工具: {block.get('name','')}",
                    "tool_name": block.get("name", ""),
                    "tool_input": block.get("input", {}),
                }

    if event_type == "tool":
        content = obj.get("content", "")
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            content = "\n".join(texts)
        return {"type": "tool_result", "content": str(content)[:3000]}

    if event_type == "result":
        return {
            "type": "done",
            "content": obj.get("result", ""),
            "cost_usd": obj.get("cost_usd", 0),
            "num_turns": obj.get("num_turns", 0),
        }

    return {"type": "other", "content": ""}


def _build_env() -> dict:
    """构造子进程环境变量，确保 ANTHROPIC_API_KEY 传入"""
    env = os.environ.copy()
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        env["ANTHROPIC_API_KEY"] = key
    return env
