# 03 · API 参考

> 权威清单来源：`docs/API_ENDPOINTS.md`（由 `scripts/export_api_endpoints.py` 从运行中的 FastAPI app 自动生成，**不手工维护**；改代码＝改清单）。
> 总计 **18 个端点 / 12 个 router**；**需鉴权 6 个**，**公开 12 个**。
> 交互式文档：后端启动后访问 `http://127.0.0.1:8000/docs`。

---

## 1. 通用约定

| 项 | 约定 |
|---|---|
| Base URL | `http://127.0.0.1:8000` |
| 内容类型 | `application/json`（请求与响应） |
| 鉴权 | `Authorization: Bearer <access_token>`（仅标注「需鉴权」的端点） |
| 成功/失败包体 | 统一 `{ "success": bool, "result": {...} | null, "error": str }` 家族 |
| 错误文案 | **固定映射**，绝不回显底层异常文本 / traceback / 路径 / Secret |
| CORS | 允许 `GET/POST/DELETE`（`DELETE` 为前端删除历史所必需的预检方法） |

**Provider 错误 → HTTP 状态码映射**（`api/routes/llm._map_failure`，被 `/api/llm/test`、`/api/sql/repair`、`/api/agent/analyze` 复用）：

| 异常 | 状态码 | 客户端文案 |
|---|---|---|
| `LLMAuthenticationError`（上游 401/403） | **502** | `Mimo authentication failed` |
| `LLMApiKeyNotConfiguredError` | 503 | `Mimo API key is not configured` |
| `LLMProviderNotConfiguredError` | 503 | `LLM provider is not configured` |
| `LLMQuotaError`（403 + `AllocationQuota.*`） | 503 | `Provider quota / allocation exhausted (free tier) [<code>]` |
| `LLMInsufficientBalanceError`（402） | 503 | `Mimo insufficient account balance` |
| `LLMRateLimitError`（429） | 503 | `Mimo rate limited` |
| `LLMServiceUnavailableError`（5xx） | 503 | `Mimo service unavailable` |
| `LLMTimeoutError` | 503 | `Mimo request timeout` |
| `LLMNetworkError` | 503 | `Mimo network error` |
| 其他未预期异常 | 503 | `Mimo request failed` |

> `LLMQuotaError` 与 `LLMAuthenticationError` 都源自 HTTP 403，靠 `provider_error_code`（如 `AllocationQuota.FreeTierOnly`）区分——前者是**额度耗尽**（Key 有效），后者是**认证失败**。文案附带的错误码已经正则白名单校验，可安全透出。

---

## 2. 端点总览

| # | 方法 | 路径 | 用途 | 鉴权 |
|---:|---|---|---|---|
| 1 | GET | `/api/health` | 服务健康检查（含 SQLite 只读探活） | 公开 |
| 2 | GET | `/api/system/database` | 数据库信息（只读验证） | 公开 |
| 3 | GET | `/api/system/schema` | 数据库 Schema 元数据（只读） | 公开 |
| 4 | GET | `/api/insights/overview` | 首页业务概览（固定只读 SQL 聚合，不调 LLM） | **Bearer** |
| 5 | POST | `/api/llm/test` | LLM 连接测试（真实调用当前 Provider） | 公开 |
| 6 | POST | `/api/schema/link` | Schema Linking | 公开 |
| 7 | POST | `/api/fewshot/retrieve` | Few-shot 检索（规则型 Top-K） | 公开 |
| 8 | POST | `/api/sql/generate` | SQL 生成（只生成不执行） | 公开 |
| 9 | POST | `/api/sql/execute` | SQL 只读执行 | 公开 |
| 10 | POST | `/api/sql/repair` | SQL 修复（单独测试，不执行修复 SQL） | 公开 |
| 11 | POST | `/api/sql/execute-with-repair` | 有限 Repair 闭环（≤1 修复 / 2 执行） | 公开 |
| 12 | POST | `/api/auth/register` | 注册新用户（冲突 409） | 公开 |
| 13 | POST | `/api/auth/login` | 登录并签发 Bearer access_token | 公开 |
| 14 | GET | `/api/auth/me` | 当前登录用户 | **Bearer** |
| 15 | POST | `/api/auth/logout` | 登出（删除当前会话） | **Bearer** |
| 16 | GET | `/api/history` | 当前用户查询历史（倒序 + 分页） | **Bearer** |
| 17 | DELETE | `/api/history/{history_id}` | 删除本人一条历史 | **Bearer** |
| 18 | POST | `/api/agent/analyze` | **核心入口**：LangGraph Agent 编排（含 Trace） | **Bearer** |

---

## 3. 系统与健康

### 3.1 `GET /api/health`
响应模型 `HealthResponse`：`{status: "ok"|"degraded", service, database: {status, type:"sqlite", name}, llm?: {provider, model}}`。
- `status="degraded"`（HTTP **503**）当且仅当 SQLite 只读探活失败。
- `llm` 为**只读展示**信息（供前端 Header 的 Runtime LLM 徽标），**不发起 LLM 调用**；无法安全判定时为 `null`（前端显示中性占位，不伪造）。

### 3.2 `GET /api/system/database`
响应 `DatabaseInfo`：数据库名 + 表数 + 5 表行数（全部真实查询，`db/sqlite.get_database_info()`）。

### 3.3 `GET /api/system/schema`
响应 `SchemaResponse`：完整 Schema 元数据（`SchemaCatalog`，来自真实库 + 代码内业务描述）。

---

## 4. 业务概览

### 4.1 `GET /api/insights/overview`（**需 Bearer**）
响应 `OverviewResponse`：`{as_of, generated_at, kpis, sales_trend, category_distribution, top_products}`。

**设计约束**（`schemas/insights.py`）：
- 数值全部来自**固定只读 SQL 聚合**，接口**不接收任何用户输入**；
- **不返回趋势百分比**（`+12.4%` 之类无真实来源的数字一律不编）；
- **不返回用户私有数据**（历史走 `/api/history`）；
- `as_of = MAX(orders.order_date)` = **数据截止日**，前端**必须展示**，否则「本月销售额」会被误读为完整自然月；
- 空库返回 **200 + 空结构**（不是 500）。

| KPI | 字段 | 口径 |
|---|---|---|
| 本月销售额 | `kpis.month_sales` | 按 `as_of` 所在月，排除 `cancelled` |
| 本月订单数 | `kpis.month_orders` | 同上 |
| 用户总数 | `kpis.users_total` | `users` 表计数 |
| 客单价 | `kpis.avg_order_value` | 本月销售额 / 本月订单数 |

---

## 5. LLM 与 Text2SQL 能力端点

### 5.1 `POST /api/llm/test`
请求 `{prompt}`；响应 `LlmTestResponse{success, provider, model, content?, error?}`。
仅验证 `FastAPI → LLMProvider → Provider → 上游 API` 链路，**不是聊天接口**。状态码见 §1 映射表。

### 5.2 `POST /api/schema/link`
请求 `{question: str(1~500, 非空白)}`；响应 `{success, result: {question, tables, columns, reasons, confidence}, error}`。
`columns` 一律「表名.字段名」；`confidence ∈ [0,1]`。

### 5.3 `POST /api/fewshot/retrieve`
请求 `{question(1~500), tables: string[], columns: string[], scenario?: str, top_k: int=3(1~50)}`；响应 `{success, result: FewShotResult, error}`。
`columns` 必须「表名.字段名」；`top_k` 越界 → **422**。

### 5.4 `POST /api/sql/generate`
请求 `{question(1~500)}`；响应 `{success, result: {question, sql, tables, columns, fewshot_examples, explanation}, error}`。
**只生成不执行**。

### 5.5 `POST /api/sql/execute`
请求 `{sql}`；响应 `{success, result: {columns, rows, row_count, truncated, execution_time_ms}, error}`。

**状态码**：
| 场景 | 码 |
|---|---|
| 安全校验拒绝（写操作/多语句/无法解析） | **422** |
| Scope 校验拒绝（未定义别名） | 422 |
| 数据库执行异常（语法/表不存在） | **500** |
| 未预期异常 | 500（固定文案） |

> 结果超限**不是**错误：返回 200 + `truncated=true`（最多 500 行，`MAX_RESULT_ROWS`）。

### 5.6 `POST /api/sql/repair`
请求 `SQLRepairRequest{question, original_sql, error_message, tables, columns}`；响应 `{success, result: {repaired_sql, repair_reason}, error}`。**不执行修复后的 SQL**。

| 场景 | 码 |
|---|---|
| Repair 后 Safety 拒绝 | 422 |
| Repair 输出非法 / Schema 越界 | 502 |
| LLM Provider 错误 | 502 / 503（见 §1） |
| 未预期异常 | 500 |

### 5.7 `POST /api/sql/execute-with-repair`
请求 `SQLExecuteWithRepairRequest{question, sql, tables, columns}`；响应 `{success, result: SQLExecuteWithRepairResult, error}`。
闭环：`Safety → Execute →（数据库错误）→ Repair(一次) → 校验 → Execute(一次)`。最多 1 次修复 / 2 次执行。
最终仍失败 → **422**（`success=false` + 完整诊断：`original_error` / `repair_error` / 计数）。

---

## 6. 认证

| 端点 | 请求 | 成功 | 失败 |
|---|---|---|---|
| `POST /api/auth/register` | `{username(1~64), email(≤254, 基础格式), password(1~1024)}` | **201** + `UserOut{id, username, email, is_active}` | `username/email` 冲突 → **409**；格式非法 → 422 |
| `POST /api/auth/login` | `{username, password}` | **200** + `LoginResponse{access_token, token_type:"bearer", expires_at, user}` | 认证失败 → 401（统一文案） |
| `GET /api/auth/me` | Bearer | 200 + `UserOut` | 无/无效/过期 token → 401 |
| `POST /api/auth/logout` | Bearer | **204**（无响应体） | 401 |

**模型要点**（`schemas/auth.py`）：
- 响应模型**刻意不含** `password_hash` / `token_hash` 等任何内部安全字段；
- `username` trim 后非空；`email` trim + 小写 + 基础格式校验；`password` 不 trim 但拒绝纯空白；
- `access_token` 是**原始令牌**，只出现在登录响应中；数据库只保存 `hash_session_token(token)`（SHA-256）；
- 口令哈希：**PBKDF2-HMAC-SHA256，iterations=600,000**（`auth/security.py`）。

**已知限制**（如实声明）：登录无限流/验证码；失败响应统一文案但未做恒时模糊；过期会话无后台清理（仅登录校验时惰性失效）；无 refresh token（TTL 默认 7 天）；token 存于浏览器 `localStorage`（有 XSS 暴露面，已配套统一 401 清会话）。

---

## 7. 查询历史

### 7.1 `GET /api/history`（需 Bearer）
查询参数：`page`（≥1）、`page_size`（1~100）。
响应 `HistoryListResponse{items: HistoryItem[], page, page_size, total}`，按 `created_at DESC, id DESC`。
- 响应**不含** `user_id` / `session_id`（内部隔离字段，暴露无收益且有探测风险）。
- **强制 `user_id = ?` 隔离**（以服务端登录态为准，绝不信任前端参数）。

`HistoryItem`：`{id, question, sql, success, error_message, result_summary, row_count, total_time_ms, created_at}`。

### 7.2 `DELETE /api/history/{history_id}`（需 Bearer）
删除本人一条历史；不属于本人或不存在 → **404**；成功 → 204。

---

## 8. 核心端点：`POST /api/agent/analyze`

**鉴权**：必须 Bearer（`Depends(get_current_session)`）。

**请求**：`AgentRequest{question: str(1~500)}`（空/纯空白 → 422）。

**响应**：`AgentResponse`：
```jsonc
{
  "success": true,
  "result": {
    "question": "...",
    "success": true,
    "generated_sql": "SELECT ...",
    "repaired_sql": "",
    "execution_result": { "columns": [...], "rows": [[...]], "row_count": 12,
                          "truncated": false, "execution_time_ms": 3.21 },
    "execution_error": "",
    "repair_reason": "",
    "repair_error": "",
    "execute_count": 1,
    "repair_count": 0,
    "final_error": "",
    "trace": [ { "sequence": 1, "node": "schema_link", "status": "success",
                 "duration_ms": 1234.5, "message": "",
                 "input_summary": {...}, "output_summary": {...} }, ... ],
    "http_status": null,
    "error_type": "",
    "total_time_ms": 10900.0
  },
  "error": ""
}
```

**状态码**：
| 场景 | 码 |
|---|---|
| 参数校验失败 | 422 |
| Provider 认证失败（`result.http_status=502`） | **502** |
| 其他 Provider 错误（`result.http_status=503`） | **503** |
| 未预期异常 | 500（固定文案 `Agent analysis internal error`） |
| Agent 终态失败（如 Safety 拒绝、Repair 失败） | **200** + `success=false` + `trace` 保留失败节点 |

**落库行为**（P4）：
- **成功或失败都尽力写入一条 `query_history`**（`user_id` 来自服务端登录态）；
- 落库失败只记 `warning` 日志（仅异常类型），**绝不改变已产生的响应/状态码**；
- 入库的 `error_message` 经 `_scrub()` **凭据脱敏**（`token/password/secret/api_key=...`、`Bearer ...`、`sk-...`、`eyJ...` → 打码）；
- 最终 SQL 取 `repaired_sql or generated_sql`；`result_summary` 由 `execution_result` 拼装轻量摘要（如 `12 行 · 列: month, sales`），**不塞结果全集**。

---

## 9. 调用示例

```bash
# 1) 注册
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","email":"demo@example.com","password":"demo123456"}'

# 2) 登录拿 token
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"demo123456"}'

# 3) 核心分析
curl -X POST http://127.0.0.1:8000/api/agent/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"question":"2025年每月销售额是多少？"}'

# 4) 历史
curl "http://127.0.0.1:8000/api/history?page=1&page_size=20" \
  -H "Authorization: Bearer <access_token>"
```

---

## 10. 未实现（不虚构）

- **多轮 conversation API**（Multi-turn 属 PRD 阶段 2，当前为单轮 Agent）；
- 结论生成、图表规格生成 API（前端 ECharts 映射为规则 Map）。
