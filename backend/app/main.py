"""FastAPI 应用入口。

负责：创建 FastAPI app、注册路由、基础 metadata、开发环境 CORS。

启动方式（在本 backend 目录下）：
    uvicorn app.main:app --reload

当前阶段（阶段 4-任务 1~6）包含：
- GET /api/health            健康检查（含 SQLite 只读探活）
- GET /api/system/database   数据库信息（只读验证）
- GET /api/insights/overview 首页业务概览（只读聚合，不调用 LLM）
- POST /api/llm/test         LLM Provider 连接测试（真实调用 Mimo）
- POST /api/schema/link      Schema Linking（识别问题相关表与字段）
- POST /api/fewshot/retrieve Few-shot 示例检索（规则型，Top-K）
- POST /api/sql/generate     SQL 生成（Text2SQL，只生成不执行）
- POST /api/sql/execute      SQL 执行（只读 SELECT/WITH，结构化结果）
- POST /api/sql/repair       SQL 修复（单独测试，最多 1 次）
- POST /api/sql/execute-with-repair  SQL 执行（有限 Repair 闭环：≤1 次修复/2 次执行）
- POST /api/agent/analyze     Text2SQL Agent 编排（LangGraph，需登录，自动落库历史）
- /api/auth/*                 认证（注册 / 登录 / 当前用户 / 登出，Bearer 会话）
- /api/history                查询历史（当前用户，分页 / 删除）
- /docs、/redoc              FastAPI 自带交互式文档

已接入：可插拔 LLM Provider（默认 Mimo V2.5 Pro）、Schema Linking、
Few-shot Retrieval（规则型本地检索）、SQL Generator（生成 + 只读校验）、
SQL Executor（只读执行 + 结果保护）、SQL Repair（有限单次自修复）、
LangGraph Agent 编排（有界循环）。
未接入：结论与图表生成 / 自由 ReAct Agent / SQL 无限自循环。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agent,
    auth,
    fewshot,
    health,
    history,
    insights,
    llm,
    schema_link,
    sql_execute,
    sql_generate,
    sql_repair,
    system,
)
from app.core.config import CORS_ORIGINS

app = FastAPI(
    title="电商智能数据分析 Agent API",
    description=(
        "《基于 Text2SQL 的电商智能数据分析 Agent》后端服务。"
        "当前阶段：骨架 + 健康检查 + SQLite 只读访问 + LLM Provider（Mimo）"
        "+ Schema Linking。"
    ),
    version="0.1.0",
)

# 开发环境 CORS：默认仅允许 Vite 前端 http://localhost:5173，
# 可通过环境变量 CORS_ORIGINS（逗号分隔）配置。
# allow_methods 含 DELETE：P5 前端跨源调用 DELETE /api/history/{id} 的预检必需。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(system.router, prefix="/api/system")
app.include_router(insights.router, prefix="/api/insights")
app.include_router(llm.router, prefix="/api")
app.include_router(schema_link.router, prefix="/api")
app.include_router(fewshot.router, prefix="/api")
app.include_router(sql_generate.router, prefix="/api")
app.include_router(sql_execute.router, prefix="/api")
app.include_router(sql_repair.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(agent.router, prefix="/api")