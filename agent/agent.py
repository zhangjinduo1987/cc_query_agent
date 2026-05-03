"""
Claude Code Agent 核心 - 通过 subprocess 调用 claude CLI 实现智能体交互
支持流式输出、MCP 工具集成、实时事件回调
"""

import asyncio
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Optional
from pathlib import Path

from agent.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT_TEMPLATE


@dataclass
class AgentEvent:
    """智能体实时事件"""
    type: str          # thinking | tool_call | tool_result | text | done | error
    content: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """智能体最终结果"""
    success: bool
    report: str
    query: str
    events: list[AgentEvent] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    num_turns: int = 0
    error: str = ""


class ClaudeCodeAgent:
    """
    Claude Code 智能体执行器
    
    通过 subprocess 调用 `claude` CLI，以 stream-json 格式
    获取实时事件流，支持 MCP Server 工具扩展。
    """

    def __init__(
        self,
        work_dir: str = "/tmp/cc_agent_workspace",
        max_turns: int = 30,
        mcp_config_path: Optional[str] = None,
        on_event: Optional[Callable[[AgentEvent], None]] = None,
    ):
        self.work_dir = work_dir
        self.max_turns = max_turns
        self.mcp_config_path = mcp_config_path
        self.on_event = on_event
        os.makedirs(self.work_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    async def analyze(
        self,
        query: str,
        context: dict | None = None,
        stream_callback: Optional[Callable[[AgentEvent], None]] = None,
    ) -> AgentResult:
        """
        主入口：接受自然语言 query，流式执行分析，返回结构化结果

        :param query:           用户自然语言问题
        :param context:         可选背景信息 dict
        :param stream_callback: 实时事件回调 (可接 WebSocket)
        :return:                AgentResult
        """
        callback = stream_callback or self.on_event
        full_prompt = self._build_prompt(query, context or {})
        events: list[AgentEvent] = []
        tool_calls: list[dict] = []

        try:
            async for event in self._run_claude_stream(full_prompt):
                events.append(event)
                if callback:
                    await self._safe_callback(callback, event)

                # 收集工具调用记录
                if event.type == "tool_call":
                    tool_calls.append({
                        "tool": event.tool_name,
                        "input": event.tool_input,
                    })

            # 从事件流提取最终报告
            report = self._extract_report(events)
            cost, turns = self._extract_stats(events)

            return AgentResult(
                success=True,
                report=report,
                query=query,
                events=events,
                tool_calls=tool_calls,
                cost_usd=cost,
                num_turns=turns,
            )

        except Exception as exc:
            err_event = AgentEvent(type="error", content=str(exc))
            if callback:
                await self._safe_callback(callback, err_event)
            return AgentResult(
                success=False,
                report="",
                query=query,
                events=events,
                error=str(exc),
            )

    # ------------------------------------------------------------------ #
    #  Internal: build prompt                                              #
    # ------------------------------------------------------------------ #

    def _build_prompt(self, query: str, context: dict) -> str:
        context_lines = []
        if context.get("time_range"):
            context_lines.append(f"- 分析时间范围: {context['time_range']}")
        if context.get("dimensions"):
            context_lines.append(f"- 关注维度: {', '.join(context['dimensions'])}")
        if context.get("compare_period"):
            context_lines.append(f"- 对比周期: {context['compare_period']}")
        context_str = "\n".join(context_lines) if context_lines else "无特殊背景说明"

        return ANALYSIS_PROMPT_TEMPLATE.format(
            query=query,
            context=context_str,
        )

    # ------------------------------------------------------------------ #
    #  Internal: run claude CLI                                            #
    # ------------------------------------------------------------------ #

    async def _run_claude_stream(
        self, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        启动 claude CLI 子进程，以 stream-json 逐行解析事件。
        """
        cmd = self._build_cmd(prompt)
        env = self._build_env()

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.work_dir,
            env=env,
        )

        # 逐行读取 stdout（stream-json 格式每行一个 JSON 对象）
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            event = self._parse_stream_line(line)
            if event:
                yield event

        await process.wait()

        # 如果进程异常退出，读取 stderr 作为错误信息
        if process.returncode not in (0, None):
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            if stderr_text:
                yield AgentEvent(type="error", content=f"Claude CLI error: {stderr_text[:500]}")

    def _build_cmd(self, prompt: str) -> list[str]:
        """构建 claude CLI 命令行参数"""
        cmd = [
            "claude",
            "--output-format", "stream-json",   # 流式 JSON 输出
            "--max-turns", str(self.max_turns),
            "--no-interactive",                  # 非交互模式
            "--print",                           # 执行完后退出
            "--system-prompt", SYSTEM_PROMPT,
            "--allowedTools", "Bash,Read,Write,Edit",  # 允许的内置工具
        ]

        # 注入 MCP 配置（数据工具层）
        if self.mcp_config_path and Path(self.mcp_config_path).exists():
            cmd += ["--mcp-config", self.mcp_config_path]

        cmd.append(prompt)
        return cmd

    def _build_env(self) -> dict:
        """构建进程环境变量"""
        env = os.environ.copy()
        # 确保 API Key 传入子进程
        if "ANTHROPIC_API_KEY" not in env:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.getenv("ANTHROPIC_API_KEY", "")
            if key:
                env["ANTHROPIC_API_KEY"] = key
        return env

    # ------------------------------------------------------------------ #
    #  Internal: parse stream-json lines                                   #
    # ------------------------------------------------------------------ #

    def _parse_stream_line(self, line: str) -> Optional[AgentEvent]:
        """
        解析 claude stream-json 格式的单行事件。

        主要事件类型：
          system   → 初始化信息
          assistant→ 模型输出 (text block / tool_use block)
          tool     → 工具调用结果
          result   → 最终结果 + 统计
        """
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # 非 JSON 行当作纯文本输出
            return AgentEvent(type="text", content=line)

        event_type = obj.get("type", "")

        # ── system 初始化 ──────────────────────────────────────────
        if event_type == "system":
            return AgentEvent(
                type="thinking",
                content=f"初始化: {obj.get('subtype', '')}",
                metadata=obj,
            )

        # ── assistant 消息：包含 text 或 tool_use block ────────────
        if event_type == "assistant":
            content_blocks = obj.get("message", {}).get("content", [])
            for block in content_blocks:
                btype = block.get("type", "")
                if btype == "text":
                    return AgentEvent(type="thinking", content=block.get("text", ""))
                if btype == "tool_use":
                    return AgentEvent(
                        type="tool_call",
                        tool_name=block.get("name", ""),
                        tool_input=block.get("input", {}),
                        content=f"调用工具: {block.get('name', '')}",
                    )

        # ── tool 执行结果 ──────────────────────────────────────────
        if event_type == "tool":
            content = obj.get("content", "")
            if isinstance(content, list):
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                content = "\n".join(texts)
            return AgentEvent(
                type="tool_result",
                content=str(content)[:2000],   # 截断超长结果
                metadata={"tool_use_id": obj.get("tool_use_id", "")},
            )

        # ── result 最终结果 ────────────────────────────────────────
        if event_type == "result":
            return AgentEvent(
                type="done",
                content=obj.get("result", ""),
                metadata={
                    "cost_usd": obj.get("cost_usd", 0),
                    "num_turns": obj.get("num_turns", 0),
                    "is_error": obj.get("is_error", False),
                },
            )

        return None

    # ------------------------------------------------------------------ #
    #  Internal: extract from events                                       #
    # ------------------------------------------------------------------ #

    def _extract_report(self, events: list[AgentEvent]) -> str:
        """从事件列表中提取最终报告文本"""
        # 优先取 done 事件的 content
        for ev in reversed(events):
            if ev.type == "done" and ev.content.strip():
                return ev.content
        # 降级：拼接所有 thinking 文本
        parts = [ev.content for ev in events if ev.type == "thinking" and ev.content.strip()]
        return "\n\n".join(parts[-5:]) if parts else "分析完成，未获取到报告内容。"

    def _extract_stats(self, events: list[AgentEvent]) -> tuple[float, int]:
        """提取费用和轮次信息"""
        for ev in reversed(events):
            if ev.type == "done":
                return (
                    float(ev.metadata.get("cost_usd", 0)),
                    int(ev.metadata.get("num_turns", 0)),
                )
        return 0.0, 0

    # ------------------------------------------------------------------ #
    #  Internal: safe async callback                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _safe_callback(cb: Callable, event: AgentEvent) -> None:
        """兼容同步/异步回调"""
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(event)
            else:
                cb(event)
        except Exception:
            pass  # 回调失败不影响主流程
