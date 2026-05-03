"""
API 路由 - 分析接口、Schema 查询、历史记录
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from agent.agent import ClaudeCodeAgent, AgentEvent
from api.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    SchemaResponse,
    StreamEvent,
)
from mcp_server.db_tools import get_schema

router = APIRouter()

# 简易内存会话存储（生产环境替换为 Redis）
_sessions: dict[str, dict] = {}

# MCP 配置文件路径
MCP_CONFIG_PATH = "/home/user/webapp/mcp_config.json"


def _get_agent(session_id: str, ws_send=None) -> ClaudeCodeAgent:
    """创建 Agent 实例，可注入 WebSocket 回调"""

    async def on_event(event: AgentEvent):
        if ws_send:
            ev = StreamEvent(
                session_id=session_id,
                type=event.type,
                content=event.content[:1000] if event.content else "",
                tool_name=event.tool_name,
                tool_input=event.tool_input,
                metadata=event.metadata,
            )
            await ws_send(ev.model_dump_json())

    return ClaudeCodeAgent(
        work_dir=f"/tmp/cc_agent_{session_id}",
        max_turns=30,
        mcp_config_path=MCP_CONFIG_PATH,
        on_event=on_event,
    )


# ------------------------------------------------------------------ #
#  REST 接口                                                           #
# ------------------------------------------------------------------ #

@router.get("/health")
async def health_check():
    """健康检查"""
    db_ok = False
    try:
        result = get_schema(include_sample=False)
        db_ok = "error" not in result
    except Exception:
        pass
    return {"status": "ok", "version": "1.0.0", "db_connected": db_ok}


@router.get("/schema")
async def get_db_schema(table_name: Optional[str] = None):
    """获取数据库表结构"""
    result = get_schema(table_name=table_name, include_sample=True)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return SchemaResponse(tables=result)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """
    同步分析接口（等待完整结果）
    适合短时分析，建议改用 WebSocket 实时接收流式进度
    """
    session_id = str(uuid.uuid4())[:8]
    agent = _get_agent(session_id)
    result = await agent.analyze(query=req.query, context=req.context)

    # 存入会话
    _sessions[session_id] = {
        "query": req.query,
        "result": result,
        "created_at": datetime.now().isoformat(),
    }

    return AnalyzeResponse(
        session_id=session_id,
        query=result.query,
        report=result.report,
        success=result.success,
        tool_calls=result.tool_calls,
        cost_usd=result.cost_usd,
        num_turns=result.num_turns,
        error=result.error,
    )


@router.get("/history")
async def get_history():
    """获取最近 20 条分析历史"""
    history = []
    for sid, s in list(_sessions.items())[-20:]:
        history.append({
            "session_id": sid,
            "query": s["query"],
            "success": s["result"].success if s.get("result") else False,
            "created_at": s["created_at"],
        })
    return {"history": list(reversed(history))}


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取指定会话结果"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    result = session["result"]
    return AnalyzeResponse(
        session_id=session_id,
        query=result.query,
        report=result.report,
        success=result.success,
        tool_calls=result.tool_calls,
        cost_usd=result.cost_usd,
        num_turns=result.num_turns,
        error=result.error,
    )


# ------------------------------------------------------------------ #
#  WebSocket 流式接口                                                  #
# ------------------------------------------------------------------ #

@router.websocket("/ws/analyze")
async def ws_analyze(websocket: WebSocket):
    """
    WebSocket 流式分析接口

    客户端发送:
        {"query": "...", "context": {...}}

    服务端推送事件:
        {"type": "thinking",    "content": "..."}
        {"type": "tool_call",   "tool_name": "...", "tool_input": {...}}
        {"type": "tool_result", "content": "..."}
        {"type": "done",        "content": "<完整报告>"}
        {"type": "error",       "content": "错误信息"}
    """
    await websocket.accept()
    session_id = str(uuid.uuid4())[:8]

    try:
        # 接收请求
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        query_text = payload.get("query", "").strip()
        context = payload.get("context", {})

        if not query_text:
            await websocket.send_text(
                StreamEvent(session_id=session_id, type="error", content="query 不能为空").model_dump_json()
            )
            return

        # 发送开始事件
        await websocket.send_text(
            StreamEvent(
                session_id=session_id,
                type="progress",
                content=f"开始分析: {query_text[:80]}...",
                metadata={"session_id": session_id},
            ).model_dump_json()
        )

        # 创建带 WS 回调的 Agent
        async def ws_send(json_str: str):
            try:
                await websocket.send_text(json_str)
            except Exception:
                pass

        agent = _get_agent(session_id, ws_send=ws_send)
        result = await agent.analyze(query=query_text, context=context)

        # 存入会话
        _sessions[session_id] = {
            "query": query_text,
            "result": result,
            "created_at": datetime.now().isoformat(),
        }

        # 若 done 事件未推送报告，在此补发
        if result.success:
            await websocket.send_text(
                StreamEvent(
                    session_id=session_id,
                    type="done",
                    content=result.report,
                    metadata={
                        "cost_usd": result.cost_usd,
                        "num_turns": result.num_turns,
                        "session_id": session_id,
                    },
                ).model_dump_json()
            )
        else:
            await websocket.send_text(
                StreamEvent(
                    session_id=session_id,
                    type="error",
                    content=result.error or "分析失败",
                ).model_dump_json()
            )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(
                StreamEvent(session_id=session_id, type="error", content=str(exc)).model_dump_json()
            )
        except Exception:
            pass
