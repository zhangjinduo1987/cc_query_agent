"""
main.py — FastAPI 应用主入口

启动：
  cd bi_chat
  python3 main.py
  或
  uvicorn bi_chat.main:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from bi_chat.api.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──────────────────────────────────────────────
    ws_root = Path(os.getenv("CC_WORKSPACE_ROOT", "./cc_workspace")).resolve()
    ws_root.mkdir(parents=True, exist_ok=True)
    print("🚀 BI 智能问数服务启动")
    print(f"   工作区: {ws_root}")
    print(f"   API 文档: http://localhost:{os.getenv('PORT', 8100)}/docs")
    yield
    # ── shutdown ─────────────────────────────────────────────


app = FastAPI(
    title="BI 智能问数服务",
    description="基于 Claude Code + MCP 的自然语言 BI 分析系统",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"service": "BI 智能问数", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "bi_chat.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8100)),
        reload=os.getenv("DEBUG", "false").lower() == "true",
        log_level="info",
    )
