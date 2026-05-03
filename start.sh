#!/usr/bin/env bash
# 一键启动脚本

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 问数分析智能体 启动中..."

# 1. 检查 .env
if [ ! -f ".env" ]; then
  echo "📋 未找到 .env，从模板创建..."
  cp .env.example .env
  echo "⚠️  请编辑 .env 填入 ANTHROPIC_API_KEY 后重新运行"
  exit 1
fi

# 2. 检查依赖
echo "📦 检查 Python 依赖..."
pip install -r requirements.txt -q

# 3. 初始化数据库
if [ ! -f "data/demo.db" ]; then
  echo "🗄️  初始化 Demo 数据库..."
  python3 scripts/init_demo_data.py
fi

# 4. 运行测试
echo "🧪 运行组件测试..."
python3 tests/test_components.py

# 5. 启动服务
echo ""
echo "✅ 启动 FastAPI 服务..."
echo "   访问地址: http://localhost:8000"
echo "   API 文档: http://localhost:8000/docs"
echo ""
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
