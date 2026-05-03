"""
FastAPI 主入口 - 启动 HTTP 服务，挂载路由和静态文件
"""

import os
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from api.routes import router

load_dotenv()

app = FastAPI(
    title="问数分析智能体",
    description="基于 Claude Code 的自然语言数据分析系统",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(router, prefix="/api")

# 静态文件（前端）
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "src"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "问数分析智能体 API", "docs": "/docs"}


# ------------------------------------------------------------------ #
#  启动时生成 MCP 配置文件                                               #
# ------------------------------------------------------------------ #

def write_mcp_config():
    """生成 Claude Code 使用的 MCP Server 配置"""
    config = {
        "mcpServers": {
            "data_tools": {
                "command": "python3",
                "args": [
                    str(Path(__file__).parent.parent / "mcp_server" / "server.py")
                ],
                "env": {
                    "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite:///./data/demo.db"),
                    "PYTHONPATH": str(Path(__file__).parent.parent),
                }
            }
        }
    }
    config_path = Path(__file__).parent.parent / "mcp_config.json"
    config_path.write_text(json.dumps(config, indent=2))
    print(f"✅ MCP config written to {config_path}")


@app.on_event("startup")
async def on_startup():
    write_mcp_config()
    print("🚀 问数分析智能体启动完成")
    print(f"   API Docs : http://localhost:{os.getenv('PORT', 8000)}/docs")
    print(f"   前端界面 : http://localhost:{os.getenv('PORT', 8000)}/")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("DEBUG", "false").lower() == "true",
        log_level="info",
    )
