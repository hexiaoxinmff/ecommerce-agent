# API 参考文档

> 本文档为 FastAPI 实际 route 的独立版 API 参考（自动核对自 `backend/app/main.py` 与 `backend/app/api/routes/*`，非凭记忆编写）。
> 交互式文档：启动后端后访问 http://127.0.0.1:8000/docs

---

## 0. 基础约定

| 项 | 约定 |
|---|---|
| Base URL | `http://127.0.0.1:8000`（默认） |
| 数据格式 | JSON |
| CORS | 默认仅允许 `http://localhost:5173`（可用环境变量 `CORS_ORIGINS` 覆盖） |
| 认证 | **当前版本无登录 / Token 机制** |
| 只读 | 所有 SQL 相关接口最终经只读执行器（`mode=ro` + `query_only=ON`） |
| 错误响应 | 统一 `{ "success": false, "error": "<固定文案>" }`（`/api/system/database` 例外，使用 HTTPException） |

通用错误码约定（与 LLM Provider 相关的接口一致）：

| HTTP | 含义 |
|---|---:|
| 422 | 参数校验失败 / SQL 安全拒绝 |
| 500 | 未预期异常（固定文案，不回显 traceback / 路径 / Secret） |
| 502 | LLM Provider 认证失败（401/403）或 LLM/SQL 输出非法 |
| 503 | LLM Provider 未配置 / 限流（429）/ 服务不可用（5xx）/ 超时 / 网络错误；数据库不可用 |

**当前版本未实现的 API（不虚构）**：

- 登录 API（login / auth）；
- 用户管理 API（User Management）；
- 多轮 conversation API（Multi-turn / 上下文）。

---

## 1. 健康检查

- **方法**：`GET`
- **路径**：`/api/health`
- **用途**：服务与 SQLite 只读连接探活（真实执行 `SELECT 1`）。

Request：无 Body / Query。

Response JSON（200）：

```json
{
  "status": "ok",
  "service": "ecommerce-analysis-agent",
  "database": { "status": "ok", "type": "sqlite", "name": "ecommerce.db" }
}
```

Response JSON（503，数据库不可用）：

```json
{
  "status": "degraded",
  "service": "ecommerce-analysis-agent",
  "database": { "status": "error", "type": "sqlite", "name": "ecommerce.db" }
}
```

错误码：

| HTTP | 场景 |
|---|---:|
| 200 | 服务与数据库均正常 |
| 503 | 数据库不可读（响应体 `status=degraded`，客户端以响应体为准） |

示例：

```bash
curl http://127.0.0.1:8000/api/health
```

---

## 2. 数据库信息

- **方法**：`GET`
- **路径**：`/api/system/database`
- **用途**：返回数据库名称与各表真实行数（只执行固定 SQL，不接收用户 SQL）。

Request：无 Body / Query。

Response JSON（200）：

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

错误码：

| HTTP | 场景 |
|---|---:|
| 200 | 正常 |
| 503 | 数据库不可用（HTTPException `detail` 提示确认 db/ecommerce.db 存在且可读） |

示例：

```bash
curl http://127.0.0.1:8000/api/system/database
```

---

## 3. LLM 连接测试

- **方法**：`POST`
- **路径**：`/api/llm/test`
- **用途**：验证 FastAPI → LLMProvider → Mimo API 链路（真实调用）。非聊天接口。

Request JSON：

```json
{ "prompt": "你好" }
```

| 字段 | 类型 | 约束 |
|---|---|---|
| prompt | string | 1~2000 字符，不可为空白 |

Response JSON（200）：

```json
{ "success": true, "provider": "mimo", "model": "mimo-v2.5-pro", "content": "…" }
```

Response JSON（失败）：

```json
{ "success": false, "provider": "mimo", "model": "mimo-v2.5-pro", "content": "", "error": "Mimo API key is not configured" }
```

错误码：

| HTTP | 场景 |
|---|---:|
| 200 | 调用成功 |
| 422 | prompt 参数非法（FastAPI 自动） |
| 502 | Mimo 认证失败（上游 401/403） |
| 503 | Key 未配置 / Provider 未配置 / 限流（429）/ 服务不可用 / 超时 / 网络错误 / 未知异常（全部固定文案） |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/llm/test \
  -H "Content-Type: application/json" \
  -d '{"prompt": "你好"}'
```

---

## 4. Schema Linking

- **方法**：`POST`
- **路径**：`/api/schema/link`
- **用途**：识别用户问题相关的表 / 字段 / 理由 / 置信度（经真实 Schema 复核；不生成 / 执行 SQL）。

Request JSON：

```json
{ "question": "2025年每月销售额是多少？" }
```

| 字段 | 类型 | 约束 |
|---|---|---|
| question | string | 1~500 字符，不可为空白 |

Response JSON（200）：

```json
{
  "success": true,
  "result": {
    "question": "2025年每月销售额是多少？",
    "tables": ["orders"],
    "columns": ["orders.order_date", "orders.total_amount"],
    "reasons": ["…"],
    "confidence": 0.95
  }
}
```

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 正常 |
| 422 | question 空 / 超长（FastAPI 自动） |
| 502 | LLM 输出非法（JSON 解析失败 / 表字段不存在 / confidence 越界）；Mimo 认证失败 |
| 503 | Mimo 未配置 / 限流 / 服务不可用 / 超时 / 网络错误 |
| 500 | 未预期异常（固定文案） |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/schema/link \
  -H "Content-Type: application/json" \
  -d '{"question": "2025年每月销售额是多少？"}'
```

---

## 5. Few-shot 检索

- **方法**：`POST`
- **路径**：`/api/fewshot/retrieve`
- **用途**：规则型本地示例检索（Top-K），不调用 Mimo。返回按 (score 降序, example_id 升序) 排序的参考示例；`score` 是检索相似度，不是 SQL 正确性。

Request JSON：

```json
{
  "question": "2025年每月销售额是多少？",
  "tables": ["orders"],
  "columns": ["orders.order_date"],
  "scenario": null,
  "top_k": 3
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| question | string | 1~500 字符，不可为空白 |
| tables | string[] | 可选 |
| columns | string[] | 可选；必须使用「表名.字段名」格式，否则 422 |
| scenario | string \| null | 可选 |
| top_k | int | 可选，默认 3，范围 1~50（0 或超大值 → 422） |

Response JSON（200）：

```json
{
  "success": true,
  "result": {
    "examples": [
      {
        "example_id": "…",
        "question": "…",
        "sql": "…",
        "score": 0.87,
        "matched_reasons": ["…"]
      }
    ]
  }
}
```

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 正常 |
| 422 | question 空 / top_k 越界 / columns 格式非法 |
| 500 | 数据集加载失败（文件缺失 / JSON 非法 / 表字段不存在等）或未预期异常 |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/fewshot/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "2025年每月销售额是多少？", "top_k": 2}'
```

---

## 6. SQL 生成

- **方法**：`POST`
- **路径**：`/api/sql/generate`
- **用途**：question → SchemaLinker → FewShotRetriever → SQLGenerator(Mimo) → SQL Validation → SQL。**只生成与校验 SQL，不执行。**

Request JSON：

```json
{ "question": "2025年每月销售额是多少？" }
```

| 字段 | 类型 | 约束 |
|---|---|---|
| question | string | 1~500 字符，不可为空白 |

Response JSON（200）：

```json
{
  "success": true,
  "result": {
    "question": "2025年每月销售额是多少？",
    "sql": "SELECT strftime('%Y-%m', order_date) AS ym, ROUND(SUM(total_amount), 2) AS total_sales FROM orders WHERE status != 'cancelled' AND strftime('%Y', order_date) = '2025' GROUP BY ym ORDER BY ym",
    "tables": ["orders"],
    "columns": ["orders.order_date", "orders.total_amount", "orders.status"],
    "fewshot_examples": ["…"],
    "explanation": "…"
  }
}
```

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 正常 |
| 422 | question 空 / 超长 |
| 500 | Few-shot 数据集异常 / 未预期异常 |
| 502 | Schema Linking 输出非法；LLM 输出非法 JSON / 非法表字段 / SQL 不安全 / 多语句 / 表引用越界；Mimo 认证失败 |
| 503 | Mimo 未配置 / 限流 / 服务不可用 / 超时 / 网络错误 |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/sql/generate \
  -H "Content-Type: application/json" \
  -d '{"question": "2025年每月销售额是多少？"}'
```

---

## 7. SQL 执行

- **方法**：`POST`
- **路径**：`/api/sql/execute`
- **用途**：只读执行 SELECT / WITH（含 UNION）。只接收 SQL，不接收自然语言；执行前再次做 SQL Safety Validation。结果超限不崩溃：返回 200 + `truncated=true`。

Request JSON：

```json
{ "sql": "SELECT region, COUNT(*) AS user_count FROM users GROUP BY region ORDER BY user_count DESC LIMIT 1" }
```

| 字段 | 类型 | 约束 |
|---|---|---|
| sql | string | 1~10000 字符，不可为空白；单条只读语句 |

Response JSON（200）：

```json
{
  "success": true,
  "result": {
    "columns": ["region", "user_count"],
    "rows": [["广东", 246]],
    "row_count": 1,
    "truncated": false,
    "execution_time_ms": 3.214
  }
}
```

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 执行成功（含 `truncated=true` 的截断场景） |
| 422 | sql 空 / 空白 / 超长；安全校验失败（写操作 / 多语句 / 无法解析等） |
| 500 | 数据库执行异常（语法错误 / 表不存在等）；未预期异常 |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/sql/execute \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT COUNT(*) AS n FROM orders"}'
```

---

## 8. SQL 修复（单独测试）

- **方法**：`POST`
- **路径**：`/api/sql/repair`
- **用途**：单独测试 Repair 能力（不回馈执行；输出修复后 SQL，不执行修复 SQL）。

Request JSON：

```json
{
  "question": "2025年每月销售额是多少？",
  "original_sql": "SELECT strftime('%Y-%m', order_date) AS ym, SUM(total_amount) AS total FROM orders GROUP BY ym",
  "error_message": "no such column: xxx",
  "tables": ["orders"],
  "columns": ["orders.order_date"]
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| question | string | 1~500，不可为空白 |
| original_sql | string | 1~10000，不可为空白 |
| error_message | string | 1~2000，不可为空白 |
| tables / columns | string[] | 可选 |

Response JSON（200）：

```json
{
  "success": true,
  "result": {
    "original_sql": "…",
    "repaired_sql": "…",
    "repair_reason": "…"
  }
}
```

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 正常 |
| 422 | 参数非法；Safety 校验拒绝（Repair 前/后） |
| 502 | Repair LLM 输出非法 / Schema 越界；Mimo 认证失败 |
| 503 | Mimo 未配置 / 限流 / 服务不可用 / 超时 / 网络错误 |
| 500 | 未预期异常 |

---

## 9. SQL 执行（有限 Repair 闭环）

- **方法**：`POST`
- **路径**：`/api/sql/execute-with-repair`
- **用途**：Safety → Execute → 失败 → Repair(一次) → Safety/Schema → Execute(一次)。**最多 1 次 Repair / 2 次执行，绝不循环。**

Request JSON：

```json
{
  "question": "2025年每月销售额是多少？",
  "sql": "SELECT strftime('%Y-%m', order_date) AS ym, SUM(total_amount) AS total FROM orders GROUP BY ym",
  "tables": ["orders"],
  "columns": ["orders.order_date"]
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| question | string | 1~500，不可为空白 |
| sql | string | 1~10000，不可为空白 |
| tables / columns | string[] | 可选 |

Response JSON（200，直接成功）：

```json
{
  "success": true,
  "result": {
    "question": "…",
    "sql": "…",
    "execute_count": 1,
    "repair_count": 0,
    "original_error": "",
    "repaired_sql": "",
    "repair_reason": "",
    "repair_error": "",
    "result": { "columns": ["…"], "rows": [], "row_count": 0, "truncated": false, "execution_time_ms": 3.5 }
  }
}
```

Response JSON（422，闭环最终失败）：`success=false` + `result`（含 `original_error` / `repair_error` 等完整诊断）+ `error`。

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 闭环成功（含 Repair 后成功） |
| 422 | 参数非法；Repair 后仍失败（success=false + 完整诊断） |
| 500 | 未预期异常（固定文案） |

> 注意：本接口对 LLM Provider 错误不单独映射 HTTP 状态（作为闭环内部步骤处理），失败统一以 422 + 诊断返回。

---

## 10. Agent 编排分析（核心入口）

- **方法**：`POST`
- **路径**：`/api/agent/analyze`
- **用途**：Question → SchemaLinking → Few-shot → SQL 生成 → Safety → Execute →（Repair ≤1）→ 二次执行 → Result + Trace。有界：`repair_count ≤ 1`、`execute_count ≤ 2`。

Request JSON：

```json
{ "question": "2025年每月销售额是多少？" }
```

| 字段 | 类型 | 约束 |
|---|---|---|
| question | string | 1~500 字符，不可为空白 |

Response JSON（200）：

```json
{
  "success": true,
  "result": {
    "question": "2025年每月销售额是多少？",
    "success": true,
    "generated_sql": "…",
    "repaired_sql": "",
    "execution_result": {
      "columns": ["ym", "total_sales"],
      "rows": [["2025-01", 725433.47]],
      "row_count": 12,
      "truncated": false,
      "execution_time_ms": 5.5
    },
    "execution_error": "",
    "repair_reason": "",
    "repair_error": "",
    "execute_count": 1,
    "repair_count": 0,
    "final_error": "",
    "trace": [
      {
        "sequence": 1,
        "node": "schema_link",
        "status": "success",
        "duration_ms": 3200.5,
        "message": "",
        "input_summary": {},
        "output_summary": {}
      }
    ],
    "total_time_ms": 12500.4,
    "http_status": null,
    "error_type": ""
  },
  "error": ""
}
```

错误码：

| HTTP | 场景 |
|---|---|
| 200 | 分析成功（含 200 级业务失败，见 `result.success` / `final_error`） |
| 422 | question 参数非法 |
| 502 | LLM Provider 认证失败（401/403） |
| 503 | Mimo 未配置 / 限流 / 服务不可用 / 超时 / 网络错误 |
| 500 | 未预期异常（固定文案 `Agent analysis internal error`） |

Trace 节点序列：`schema_link` → `fewshot_retrieve` → `sql_generate` → `sql_safety` → `sql_execute` →（可选）`sql_repair` → `sql_execute_repaired`；每个 TraceEvent 含 `status ∈ {success, error, skipped}`。

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/agent/analyze \
  -H "Content-Type: application/json" \
  -d '{"question": "2025年每月销售额是多少？"}'
```

---

## 11. 错误码汇总

| 状态码 | 通用含义 | 说明 |
|---|---:|---|
| 200 | 成功 | 业务失败以 `success=false` + `error` 表达（部分场景仍 HTTP 200） |
| 422 | 请求参数非法 / SQL 安全拒绝 | question/sql 空/超长、top_k 越界、columns 格式、写操作/多语句 SQL |
| 500 | 服务内部异常 | 固定文案，不回显 traceback / 路径 / Secret |
| 502 | 上游认证失败 / LLM 输出非法 | Mimo 401/403；非法 JSON / 表字段 / 不安全 SQL / Schema 越界 |
| 503 | 上游不可用 / 未配置 / 数据库不可用 | Key 未配置、429 限流、5xx、超时、网络错误；health 数据库失败 |

---

*本文档内容核对时间：2026-09-16（Task 24）。若与 `/docs` 自动文档不一致，以实际代码为准。本版本无登录 / 用户管理 / 多轮 API。*