"""
API 数据模型 - Pydantic 模型定义
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AnalyzeRequest(BaseModel):
    """分析请求"""
    query: str = Field(..., min_length=2, max_length=2000, description="自然语言分析问题")
    context: Optional[dict] = Field(default=None, description="背景信息")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "分析最近30天的订单趋势，找出异常波动",
                "context": {
                    "time_range": "2025-04-01 ~ 2025-04-30",
                    "compare_period": "环比上月"
                }
            }
        }


class AnalyzeResponse(BaseModel):
    """分析响应"""
    session_id: str
    query: str
    report: str
    success: bool
    tool_calls: list[dict] = []
    cost_usd: float = 0.0
    num_turns: int = 0
    error: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class StreamEvent(BaseModel):
    """WebSocket 流式事件"""
    session_id: str
    type: str       # thinking | tool_call | tool_result | done | error | progress
    content: str = ""
    tool_name: str = ""
    tool_input: dict = {}
    metadata: dict = {}
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class SchemaResponse(BaseModel):
    """数据库 Schema 响应"""
    tables: dict
    error: str = ""


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    version: str = "1.0.0"
    db_connected: bool = False
