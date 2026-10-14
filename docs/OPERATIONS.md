# 运行维护手册（Operations Manual）

> 适用范围：课程项目 **本地 Demo** 的日常运行、健康检查与常见故障排查。
> 所有错误码 / 文案均来自真实实现（见 `backend/app/api/routes/*` 与 `backend/app/llm/mimo.py`）。

---

## 1. 启动检查清单

> **推荐直接用正式启动入口**（第十阶段 P0-3）：它在启动前把下表的检查全部做完，
> 失败时给出明确文案与退出码，不需要人工逐项核对：
>
> ```bash
> python scripts/start_dev.py            # 启动；--check-only 只做预检
> python scripts/stop_dev.py             # 停止 --detach 拉起的服务
> ```
>
> Windows 也可双击 `scripts\start_dev.bat`（失败时窗口不闪退）。

| # | 检查项 | 命令 / 位置 | 期望 |
|---|---|---|---|
| 1 | Python / 依赖 | `.venv\Scripts\python.exe -m pytest --version` | pytest 可用 |
| 2 | `.env` 存在 | 项目根 `.env`（复制自 `.env.example`） | `DASHSCOPE_API_KEY` 已填写 |
| 3 | 数据库存在 | `db/ecommerce.db` + `db/app.db` | 均存在（缺失见 §7.6） |
| 4 | 后端启动 | `cd backend && uvicorn app.main:app --reload` | 监听 http://127.0.0.1:8000 |
| 5 | 健康检查 | `curl http://127.0.0.1:8000/api/health` | `status=ok` |
| 6 | 数据库信息 | `curl http://127.0.0.1:8000/api/system/database` | 返回 5 表行数 |
| 7 | 前端启动 | `cd frontend && npm run dev` | http://localhost:5173 可访问 |
| 8 | LLM 链路（可选） | `POST /api/llm/test` | `success=true` |

> ⚠️ **第 5 步的 `status=ok` 不代表 LLM 可用**：`/api/health` 只表达
> Backend / Database / Runtime 配置三件事，它不发起任何 LLM 请求。
> LLM 可用性看第 8 步的实际结果。详见 [API.md](API.md) §1 职责边界。

## 2. 健康检查

- 接口：`GET /api/health`
- 每次请求真实执行 `SELECT 1` 探活 SQLite 只读连接。
- 判定：

| 响应体 `status` | HTTP | 含义 |
|---|---|---|
| `ok` | 200 | 服务与数据库正常 |
| `degraded` | 503 | 数据库不可读（数据库文件缺失 / 无法以只读方式打开） |

> 注意：健康检查的 HTTP 状态与响应体 `status` 都可能变化，应以**响应体 status 字段**为准（服务可用性以 200 为准）。

## 3. 日志

- 本项目无独立日志框架；运行日志主要来自：

| 来源 | 说明 |
|---|---|
| `uvicorn` 终端 / 启动窗口 | 访问日志、LLM 调用异常（traceback 仅进日志，不回显客户端） |
| `pytest -s` 输出 | 测试期日志 |
| `.gitignore` 已忽略 `logs/`、`*.log` | 可自行重定向 `uvicorn ... > server.log 2>&1` |

- 需要排查时第一步：看 uvicorn 启动窗口是否有异常 traceback（`LLMError` vs `ZeroDivisionError` 等）。

## 4. API 错误码速查

统一响应格式：`{ "success": false, "error": "<固定文案>" }`。

| HTTP | 含义 | 常见固定文案 |
|---|---:|---|
| 422 | 参数非法 / SQL 安全拒绝 | `SQL rejected: …` |
| 500 | 未预期异常 | `… internal error`（固定文案） |
| 502 | 上游认证失败 / LLM 输出非法 | `Mimo authentication failed` / `SQL generation failed: …` |
| 503 | 上游不可用 / Key 未配置 / 数据库不可用 | `Mimo API key is not configured` / `Mimo service unavailable` / `Mimo request timeout` |

## 5. Mimo 502 / 503

LLM 相关接口（`/api/llm/test`、`/api/schema/link`、`/api/sql/generate`、`/api/sql/repair`、`/api/agent/analyze`）：

| 错误 | HTTP | 原因 |
|---|---|---|
| `Mimo authentication failed` | 502 | 上游 401/403（Key 失效 / 无权限） |
| `Mimo API key is not configured` | 503 | 未配置 `MIMO_API_KEY` |
| `Mimo rate limited` | 503 | 上游 429 限流 |
| `Mimo service unavailable` | 503 | 上游 5xx 或解析异常 |
| `Mimo request timeout` | 503 | 超过 `MIMO_TIMEOUT`（默认 30s） |
| `Mimo network error` | 503 | 网络不可达 / 连接断开（Provider 层对网络类错误最多重试 2 次） |

> 客户端只看到固定安全文案；底层异常详情只进日志（防 Secret / 路径泄漏）。

## 6. 数据库只读

- 所有连接：`file:…db?mode=ro`（文件级只读）+ `PRAGMA query_only=ON`（会话级只读）。
- 结果保护：单次最多返回 500 行，超出返回 `truncated=true`。
- 写操作（INSERT / UPDATE / DELETE / DROP / PRAGMA 等）在进入数据库前即被拒（HTTP 422）。

## 7. 常见问题（现象 → 原因 → 排查 → 处理）

### 7.1 Mimo API 失败（502 / 503 / timeout）

**现象**：请求返回 502 或 503；错误文案如 `Mimo service unavailable` / `Mimo request timeout` / `Mimo authentication failed`。

**原因**：上游 Mimo 服务不可用 / 限流 / 超时 / Key 失效 / 网络不可达。

**排查**：
1. `curl -X POST http://127.0.0.1:8000/api/llm/test -H "Content-Type: application/json" -d '{"prompt":"ping"}'` 复现最小链路；
2. 核对 `.env` 中 `MIMO_API_KEY` / `MIMO_BASE_URL` / `MIMO_MODEL`；
3. 在 uvicorn 启动窗口查看底层异常类型。

**处理**：
- Key / 端点错误 → 修正 `.env` 后重启后端；
- 上游 5xx / 429 / 超时 → 官方端点偶发电抖动，稍后重试（网络类错误 Provider 已自动重试 2 次）；
- 持续失败 → 等上游恢复，或调大 `MIMO_TIMEOUT`（`MIMO_TIMEOUT=60`）。

### 7.2 Backend 启动失败

**现象**：`uvicorn app.main:app` 启动报错退出。

**原因**：依赖缺失 / Python 版本不对 / `.env` 语法错误 / 端口被占用。

**排查**：
1. `python --version` 确认 3.12+；
2. `pip install -r requirements.txt` 后重试；
3. 检查 `.env` 引号 / 编码；检查端口：`netstat -ano | findstr :8000`。

**处理**：按上述修复；端口占用则换端口（`uvicorn app.main:app --port 8010`）并同步前端 `VITE_API_BASE_URL`。

### 7.3 Frontend 无法访问 Backend

**现象**：页面提示网络错误 / `AgentApiError`；浏览器控制台 `fetch` 失败。

**原因**：前端 `VITE_API_BASE_URL` 与后端地址不一致；后端未启动；CORS 未放行。

**排查**：
1. `frontend/.env` 中 `VITE_API_BASE_URL` 是否指向后端实际地址（默认 `http://127.0.0.1:8000`）；
2. 直接 `curl http://127.0.0.1:8000/api/health` 验证后端可达；
3. 检查 CORS：后端 `CORS_ORIGINS` 需包含前端来源（默认 `http://localhost:5173`）。注意 `localhost` 与 `127.0.0.1` 在 CORS 语义上不同。

**处理**：配置一致后重启前端（`npm run dev`）。修改后的 `.env` 需重新启动 vite 才能生效。

> **第十阶段 P0-1 起的行为变化**：后端**整个挂掉**（连接被拒绝 / 端口不通）时，
> 前端**不再把用户丢到登录页**，而是显示「后端服务不可用 / 请检查后端是否启动」+ **重试**按钮。
> 判定规则：
>
> | 后端返回 | 前端状态 | 行为 |
> |---|---|---|
> | `200` | `authenticated` | 正常进入系统 |
> | `401 / 403` | `anonymous` | 清理本地会话 → 登录页（服务在，凭证无效） |
> | 连不上 | `backend_unavailable` | **保留会话** + 显示不可用页 + 重试 |
> | `5xx` | `backend_error` | **保留会话** + 显示异常页 + 重试 |
>
> 所以：**看到登录页 = 后端是活的、只是凭证无效**；**看到"后端服务不可用" = 后端没起来**。
> 后者把后端拉起来后点「重试」即可，不需要重新登录（会话没有被清掉）。

### 7.4 SQLite database locked / 数据库不可读

**现象**：`/api/health` 返回 `degraded`；接口返回“数据库不可用”或 SQLite `database is locked`。

**原因**：
- `db/ecommerce.db` 文件缺失或路径被 `ECOMMERCE_DB_PATH` 指向别处；
- 有其他进程以写模式持有连接（如用 GUI 打开 db、另一进程正在 `init_db.py` 重建）。

**排查**：
1. `curl http://127.0.0.1:8000/api/system/database`；
2. 确认 `db/ecommerce.db` 存在且可读；
3. 检查是否有进程以写模式打开该文件。

**处理**：
- 文件缺失 → 运行 `python scripts/init_db.py`（固定 seed 重建）后重启后端；
- 路径错误 → 修正 `ECOMMERCE_DB_PATH`；
- 被占用 → 关闭占用方；本层只读连接每次独立打开、调用方负责关闭，正常并发读不冲突。

### 7.5 SQL validation failure

**现象**：`/api/sql/execute` 或 `/api/sql/generate` 返回 422，错误含 `SQL rejected: …`；或生成接口 502 `SQL generation failed`。

**原因**：SQL 语法错误 / 使用写操作（INSERT 等）/ 多语句 / 表或列不存在 / 超出允许范围；或 LLM 输出未通过结构校验。

**排查**：
1. 查看返回 `error` 中给出的拒绝原因；
2. 手动在 `scripts/init_db.py` 对应 SQLite 上验证表 / 列名；用 `/docs` 单独调用执行接口复现。

**处理**：属受控拒绝（安全边界按设计工作），换种问法 / 修正 SQL；若为 LLM 持续生成非法 SQL，检查 Prompt（`data/prompts/sql_generator_v1.3.txt`）与 Few-shot 示例是否覆盖该场景。

### 7.6 数据文件缺失（`db/ecommerce.db` / `db/app.db`）

**现象**：`python scripts/start_dev.py` 以退出码 `8` 中止；或登录 / 业务查询返回 500。

**原因**：新克隆的仓库不携带二进制库（`.gitignore` 排除了 `db/*.db`），必须先初始化。

**排查 / 处理**：

```bash
python scripts/init_db.py         # 业务库（固定 seed 20260914，可完全复现）
python scripts/init_auth_db.py    # 应用库（认证 / 会话 / 查询历史，幂等）
```

> 缺 `db/app.db` 时，`appdb` 会抛 `AppDbNotFoundError`，鉴权依赖若未接住它会
> 让伪造 token 返回 **500** 而不是 401（既有已知问题）。启动脚本因此在启动前
> 就把这个文件的存在性拦下来，而不是等用户点登录才发现。

### 7.7 端口被占用（8000 / 5173）

**现象**：`start_dev.py` 以退出码 `7` 中止并点名端口；或访问 5173 看到的不是本项目。

**原因**：上一次的服务没退干净；或 Vite 已**静默**换到了 5174。

**排查 / 处理**：

```bash
netstat -ano | findstr :8000      # Windows：查占用 PID
netstat -ano | findstr :5173
python scripts/stop_dev.py        # 若上次是 --detach 启动的
```

或换端口：`python scripts/start_dev.py --backend-port 8001 --frontend-port 5174`
（同时把 `frontend/.env` 的 `VITE_API_BASE_URL` 与后端 `CORS_ORIGINS` 改到一致）。

> `start_dev.py` 用 `--strictPort` 启动 Vite，**不会**静默换端口；
> 端口探测同时覆盖 IPv4 `127.0.0.1` 与 IPv6 `::1`（Vite 默认绑 `::1`）。

---

## 8. 每日巡检建议（本地 Demo）

```bash
# 1) 服务健康
curl http://127.0.0.1:8000/api/health
# 2) 数据库只读可用
curl http://127.0.0.1:8000/api/system/database
# 3) LLM 链路（演示前验证）
curl -X POST http://127.0.0.1:8000/api/llm/test -H "Content-Type: application/json" -d '{"prompt":"ping"}'
# 4) 单条 Agent 冒烟
curl -X POST http://127.0.0.1:8000/api/agent/analyze -H "Content-Type: application/json" -d '{"question":"哪个地区的用户最多？"}'
```

全部通过即可用于演示；任一步失败按 §7 逐项排查。

---

*编写：Task 24（2026-09-16）。不修改任何运行代码，仅沉淀排查路径。*