# 后端架构说明（Backend Architecture）

> 阶段：阶段 4（任务 1 骨架 + 任务 2 LLM Provider + 任务 3 Schema Linking）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 后端目录结构

```text
backend/
├─ __init__.py
├─ app/
│  ├─ __init__.py
│  ├─ main.py                 # 创建 FastAPI app、注册路由、metadata、CORS
│  ├─ core/
│  │  ├─ __init__.py
│  │  └─ config.py            # 全局配置：数据库路径、服务名、CORS、LLM Provider
│  ├─ db/
│  │  ├─ __init__.py
│  │  └─ sqlite.py            # SQLite 只读访问层
│  ├─ llm/
│  │  ├─ __init__.py
│  │  ├─ provider.py          # LLMProvider 抽象 + 异常体系 + 工厂
│  │  └─ mimo.py              # MimoProvider（OpenAI-compatible 默认实现）
│  ├─ fewshot/
│  │  ├─ __init__.py
│  │  ├─ models.py            # FewShotExample / FewShotQuery / FewShotMatch / FewShotResult
│  │  ├─ dataset.py           # 本地 JSON 数据集加载与校验（含缓存）
│  │  └─ retriever.py         # 规则型 Top-K 检索器（不依赖 Mimo）
│  ├─ sqlgen/
│  │  ├─ __init__.py
│  │  ├─ errors.py            # SQL Generator 异常体系
│  │  ├─ prompt.py            # SQL Generation Prompt 构建
│  │  ├─ safety.py            # SQL 安全/结构校验（sqlglot 只读单语句）
│  │  ├─ validator.py         # LLM 输出校验 + Schema 一致性 + 表引用一致
│  │  └─ generator.py         # SQLGenerator（SchemaLinker+FewShotRetriever+LLMProvider）
│  ├─ sqlexec/
│  │  ├─ __init__.py
│  │  ├─ errors.py            # SQL Executor 异常体系
│  │  ├─ models.py            # SQLExecutionRequest / Result / Response
│  │  └─ executor.py          # 只读执行（复用 sqlgen.safety + db 只读层，结果保护）
│  ├─ sqlrepair/
│  │  ├─ __init__.py
│  │  ├─ errors.py            # SQL Repair 异常体系
│  │  ├─ models.py            # Repair 请求/结果/闭环诊断 + 错误清洗
│  │  ├─ prompt.py            # Repair Prompt 构建（问题+原SQL+错误+Schema+Few-shot）
│  │  ├─ validator.py         # Repair 输出二次校验（Safety + Schema）
│  │  └─ repairer.py          # SQLRepairer + 有限闭环 Orchestrator（≤1 次修复）
│  ├─ agent/
│  │  ├─ __init__.py
│  │  ├─ state.py             # AgentState（LangGraph 显式状态 + trace reducer）
│  │  ├─ nodes.py             # 节点 + Trace 包装 + 条件边路由 + 结果组装
│  │  ├─ graph.py             # build_agent / run_agent（compile + invoke + total_time）
│  │  └─ models.py            # AgentRequest / AgentResult / AgentResponse（含 trace）
│  ├─ trace/
│  │  ├─ __init__.py
│  │  ├─ models.py            # TraceEvent（sequence/status/duration/摘要）
│  │  └─ recorder.py          # 事件构建 / skipped 补全 / 排序编号
│  ├─ schema/
│  │  ├─ __init__.py
│  │  ├─ introspector.py      # 从真实 SQLite 读取表/字段结构
│  │  ├─ metadata.py          # SchemaCatalog：真实结构 + 代码内业务描述
│  │  ├─ validation.py        # Schema 合法性校验（拒绝不存在表/字段）
│  │  └─ linker.py            # Schema Linker（经 LLMProvider 调用）
│  ├─ schemas/
│  │  ├─ __init__.py
│  │  ├─ health.py            # HealthResponse / DatabaseHealth
│  │  ├─ system.py            # DatabaseInfo
│  │  ├─ llm.py               # LlmTestRequest / LlmTestResponse
│  │  ├─ schema_link.py       # SchemaLinkRequest / SchemaLinkResult / Response
│  │  ├─ fewshot.py           # FewShotRetrieveRequest / FewShotRetrieveResponse
│  │  └─ sql_generate.py      # SQLGenerationRequest / Result / Response
│  └─ api/
│     ├─ __init__.py
│     └─ routes/
│        ├─ __init__.py
│        ├─ health.py         # GET /api/health
│        ├─ system.py         # GET /api/system/database
│        ├─ llm.py            # POST /api/llm/test
│        ├─ schema_link.py    # POST /api/schema/link
│        ├─ fewshot.py        # POST /api/fewshot/retrieve
│        ├─ sql_generate.py   # POST /api/sql/generate
│        ├─ sql_execute.py    # POST /api/sql/execute
│        ├─ sql_repair.py     # POST /api/sql/repair + /api/sql/execute-with-repair
│        └─ agent.py          # POST /api/agent/analyze（LangGraph 编排）
└─ tests/
   ├─ __init__.py
   ├─ conftest.py             # sys.path 配置 + TestClient fixture
   ├─ test_health.py
   ├─ test_database.py
   ├─ test_llm_provider.py    # LLM Provider 单元测试（mock）
   ├─ test_llm_api.py         # POST /api/llm/test API 测试（mock）
   ├─ test_schema_linking.py  # Schema Metadata/Linking/Validation 单测（mock）
   ├─ test_schema_link_api.py # POST /api/schema/link API 测试（mock）
   ├─ test_fewshot_dataset.py # Few-shot 数据集加载/校验测试
   ├─ test_fewshot_retriever.py # Few-shot 检索器单测（不依赖 Mimo）
   ├─ test_fewshot_api.py     # POST /api/fewshot/retrieve API 测试
   ├─ test_sql_generator.py   # SQL Generator 单测（mock 三件套）
   ├─ test_sql_generate_api.py # POST /api/sql/generate API 测试
   ├─ test_sql_executor.py    # SQL Executor 单测（只读执行 + 零变更）
   ├─ test_sql_execute_api.py # POST /api/sql/execute API 测试
   ├─ test_sql_repair.py      # SQL Repair 单测（修复成功/拒绝/计数 + 零变更）
   ├─ test_sql_repair_api.py  # POST /api/sql/repair + execute-with-repair API 测试
   ├─ test_agent_graph.py     # LangGraph 编排单测（fake 组件 + 真实 SQLite）
   ├─ test_agent_api.py       # POST /api/agent/analyze API 测试
   └─ test_agent_trace.py     # Agent Trace 测试（正常/Repair/Safety/Provider错误/零变更）
```

## 2. FastAPI 启动方式

在 `backend/` 目录下执行：

```bash
uvicorn app.main:app --reload
```

- 服务默认监听 `http://127.0.0.1:8000`
- Python：3.12.10，FastAPI：0.141.1，仅在 `/backend` 目录下以
  `uvicorn app.main:app` 方式启动，不依赖 PYTHONPATH 等临时环境变量。

## 3. API

### 3.1 GET /api/health —— 健康检查

真实执行 `SELECT 1` 探活 SQLite 只读连接，返回：

```json
{
  "status": "ok",
  "service": "ecommerce-analysis-agent",
  "database": {
    "status": "ok",
    "type": "sqlite",
    "name": "ecommerce.db"
  }
}
```

- 数据库可用：HTTP 200，`status = "ok"`；
- 数据库不可用（文件不存在或不可读）：HTTP 503，`status = "degraded"`，
  `database.status = "error"`，不含任何绝对路径信息。

### 3.2 GET /api/system/database —— 数据库信息（只读验证）

仅用于验证只读连接真实打通，全部数值来自真实 SQL 查询（非写死）：

```json
{
  "database": "ecommerce.db",
  "tables": 5,
  "users": 2000,
  "categories": 30,
  "products": 500,
  "orders": 10000,
  "order_items": 30457
}
```

数据库不可用时返回 HTTP 503 与明确错误信息，不泄漏绝对路径。

### 3.3 接口文档

FastAPI 自带 `/docs`（Swagger UI）与 `/redoc`（ReDoc），已验证可正常访问。

## 4. SQLite 只读策略

- 纯 Python 标准库 `sqlite3`，未引入 SQLAlchemy；
- **双重只读保障**：
  1. 连接统一使用 SQLite URI 只读模式 `file:<path>?mode=ro`（文件级只读）；
  2. 附加 `PRAGMA query_only = ON`（会话级只读）；
- `row_factory` 设置为 `sqlite3.Row`；
- 每次获取独立连接、调用方负责关闭，无连接池（当前规模不需要）；
- INSERT / UPDATE / DELETE / REPLACE / DROP / ALTER / CREATE 等写入语句
  会被 SQLite 以 `OperationalError: attempt to write a readonly database` 拒绝；
- 数据库文件不存在时抛出 `DatabaseNotFoundError`（清晰错误信息）。

## 5. 数据库路径配置

- 环境变量 `ECOMMERCE_DB_PATH`（绝对或相对路径均可）；
- 未设置时使用项目默认路径 `db/ecommerce.db`（由代码位置向上推导项目根目录，
  不依赖进程工作目录，不硬编码任何个人电脑绝对路径）；
- 已在本机 Windows 环境验证中文路径下 URI 只读连接可用。

## 6. CORS

- 默认仅允许前端本地开发地址 `http://localhost:5173`（不是 `*`）；
- 可通过环境变量 `CORS_ORIGINS`（逗号分隔）显式配置；
- 当前阶段仅开放 `GET` 方法。

## 7. 安全边界（本阶段已保证）

- SQLite 访问从设计上默认只读；
- 数据库路径只来自服务端配置/环境变量，**不接受前端传入任意路径**；
- `/api/health` 与 `/api/system/database` 只执行固定 SQL，**不执行用户 SQL**；
- 不存在类似 `/api/query?sql=xxx` 的接口；
- 内部异常不向客户端泄漏 Python traceback（FastAPI 默认 500 处理）。

## 8. 当前未实现的功能

```text
Mimo：已接入（可插拔 LLM Provider，见 docs/llm-integration.md）
Schema Linking：已接入（真实 Schema 复核，见 docs/schema-linking.md）
Few-shot Retrieval：已接入（规则型本地检索，见 docs/fewshot-retrieval.md）
SQL Generator：已接入（生成 + 只读校验，不执行 SQL，见 docs/sql-generator.md）
SQL Executor：已接入（只读执行 + 结果保护，见 docs/sql-executor.md）
SQL Repair：已接入（有限单次自修复，见 docs/sql-repair.md）
LangGraph Agent 编排：已接入（有界循环，见 docs/langgraph-agent.md）
Agent Trace：已接入（结构化节点执行轨迹，见 docs/agent-trace.md）
前端 ↔ Agent API 联调：已接通（AnalysisPage 真实调用 POST /api/agent/analyze，
阶段 4-任务 10；首页仍保留 Demo）
结论与图表生成：未实现（Agent Response 无 conclusion，未额外调 LLM）
自由 ReAct Agent：未实现（采用控制式编排）
```

## 9. 测试

- 位置：`backend/tests/`；
- `test_health.py`：health 正常/退化路径、/docs、/redoc、OpenAPI 路由注册；
- `test_database.py`：只读连接打开、SELECT 1、真实行数回归（2000/30/500/10000/30457）、
  7 类写语句全部被拒、写失败后数据库行数与文件哈希不变、
  /api/system/database 真实行数；
- 运行方式（项目根目录）：`python -m pytest`（当前 34 个测试全部通过）。