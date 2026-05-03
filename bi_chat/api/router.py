"""
api/router.py — FastAPI 路由层

唯一对外接口：POST /api/chat
入参：user_id, question
出参：answer (str)

内部流程：
  1. intent_classify → edit_rule | query_data
  2. edit_rule  → save_rule()
  3. query_data → bi_query()
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from bi_chat.core.intent import intent_classify, save_rule, bi_query

router = APIRouter()


# ── 请求 / 响应模型 ────────────────────────────────────────────

class ChatRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "summary": "查询数据",
                    "value": {"user_id": "u_001", "question": "查看今天的经营情况"},
                },
                {
                    "summary": "修改规则",
                    "value": {
                        "user_id": "u_001",
                        "question": "我期望看经营情况时默认展示利润、成本、目标收入完成率",
                    },
                },
            ]
        }
    )

    user_id: str = Field(..., description="用户唯一标识")
    question: str = Field(..., min_length=1, max_length=2000, description="用户提问")


class ChatResponse(BaseModel):
    user_id: str
    question: str
    intent: str          # edit_rule | query_data
    answer: str


# ── 路由 ───────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, summary="BI 智能问数统一入口")
async def chat(req: ChatRequest) -> ChatResponse:
    """
    统一问答入口。

    - **edit_rule**：识别为规则修改 → 调用 save_rule，写入用户 CLAUDE.md，返回保存提示
    - **query_data**：识别为数据查询 → 调用 bi_query，驱动 CC + MCP 全流程，返回自然语言结论
    """
    # Step 1: 意图识别
    intent = intent_classify(req.user_id, req.question)

    # Step 2: 按意图分发
    if intent == "edit_rule":
        answer = await save_rule(req.user_id, req.question)
    else:
        answer = await bi_query(req.user_id, req.question)

    return ChatResponse(
        user_id=req.user_id,
        question=req.question,
        intent=intent,
        answer=answer,
    )
