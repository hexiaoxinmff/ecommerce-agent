"""FastAPI 服务：托管前端 + 提供 /api/chat 接口。"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from config import settings
from src.agent.graph import run_agent

app = FastAPI(title="云栖数码 · Agent 智能客服")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class ChatRequest(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((FRONTEND / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mock_mode": settings.MOCK_MODE,
        "provider": settings.LLM_PROVIDER,
        "embedding": "real" if settings.USE_REAL_EMBED else "mock",
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    result = run_agent(req.message)
    _log(req.message, result)
    return JSONResponse(result)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """意图分布可视化看板（ECharts）。每次动态生成（不依赖落盘，适配只读/非 root 环境）。"""
    from src.eval import intent_dashboard

    html = intent_dashboard.build_dashboard()
    return HTMLResponse(html)


def _log(query: str, result: dict):
    try:
        with open(settings.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "time": datetime.now().isoformat(),
                        "query": query,
                        "intent": result.get("intent"),
                        "answer": result.get("answer"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
