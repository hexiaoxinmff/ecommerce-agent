# Schema Linking（Schema Understanding）说明

> 阶段：阶段 4-任务 3（Schema Understanding / Schema Linking 基础能力）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 目标

用户自然语言问题 → Schema Linking → 输出相关表、相关字段、选择理由、置信度。

本任务**不生成 SQL、不执行 SQL**，为后续 Text2SQL 提供可复用输入。

## 2. Schema Metadata 设计

```text
backend/app/schema/
├─ introspector.py   # 从真实 SQLite 读取表名/字段名/字段类型/约束
├─ metadata.py       # SchemaCatalog：真实结构 + 代码内业务描述
├─ validation.py     # Schema 合法性校验
└─ linker.py         # Schema Linker（经 LLMProvider 调用）
```

- **表名 / 字段名 / 字段类型**：来自真实 SQLite 数据库
  （`sqlite_master` + `PRAGMA table_info`），不硬编码整套 Schema；
- **业务描述**（中文表/字段说明）：保存在 `metadata.py` 中，供 Prompt 与后续 SQL Generator 复用；
- 数据结构：

  ```python
  TableMeta(name, description, columns: tuple[ColumnMeta, ...])
  ColumnMeta(name, type, description, not_null, primary_key)
  ```

- `SchemaCatalog.from_database()` 每次从真实数据库构建（5 张业务表，只读访问）。

## 3. Schema Linking 流程

```text
用户问题
   ↓
SchemaLinker.link(question)
   ↓
SchemaCatalog.from_database()          # 读取真实 Schema
   ↓
build_link_prompt(catalog, question)   # 组装 Prompt
   ↓
LLMProvider.generate()                 # 当前默认 MimoProvider
   ↓
_parse_llm_output()                    # 提取 JSON
   ↓
validate_schema_link()                 # 真实 Schema 复核（必须通过）
   ↓
SchemaLinkResult                       # 结构化结果
```

- 上层只依赖 `LLMProvider` 抽象（`backend/app/llm/provider.py`），
  不 import `openai`、不直接调用 Mimo API；
- Provider 失败时 LLMError 原样透传，由 API 路由按统一映射处理。

## 4. 输出结构（Pydantic）

```python
class SchemaLinkResult(BaseModel):
    question: str
    tables: list[str]          # 只出现真实存在的表
    columns: list[str]         # 一律使用「表名.字段名」格式
    reasons: list[str]         # 中文选择理由（1~5 条）
    confidence: float          # 0~1
```

## 5. Prompt 思路

- System Prompt：Schema Linking 组件身份，只做 Linking，不生成/执行 SQL、不修改数据库；
- User Prompt 包含：
  1. 真实数据库 Schema（JSON 文本，来自 SchemaCatalog）；
  2. 业务语义：`order_items.subtotal`=明细行金额；`orders.total_amount`=订单最终支付金额；
     **“实际销售额/实际销量”默认排除 `orders.status='cancelled'` 订单**；日期为 ISO 格式；
  3. 硬性要求：只允许使用给定 Schema、禁止创造表/字段、字段用 `表.字段`、
     reasons 中文、confidence 0~1、只输出严格 JSON；
  4. 无关问题（天气等）→ tables/columns 返回空数组、低置信度。

## 6. Schema 合法性校验（validation.py）

LLM 输出不能默认正确，必须用真实 Schema 复核：

- 表必须存在（如 `payments` → 拒绝）；
- 字段必须为「表名.字段名」且真实存在（如 `orders.xxx` → 拒绝）；
- 字段所属表必须出现在 tables 中（保持自洽，如 columns 含 `products.name`
  但 tables 无 `products` → 拒绝）；
- confidence 必须为 0~1 之间的数字；
- 非法 JSON / 缺失字段 / 类型错误 → SchemaLinkingInvalidError。

**禁止**静默降级为假成功：校验失败即明确报错。

## 7. API

```http
POST /api/schema/link
Content-Type: application/json

{ "question": "近30天销售额最高的商品有哪些？" }
```

成功响应（HTTP 200）：

```json
{
  "success": true,
  "result": {
    "question": "近30天销售额最高的商品有哪些？",
    "tables": ["orders", "order_items", "products"],
    "columns": [
      "orders.order_date", "orders.status", "orders.total_amount",
      "order_items.product_id", "order_items.subtotal",
      "products.id", "products.name"
    ],
    "reasons": ["...", "..."],
    "confidence": 0.92
  },
  "error": ""
}
```

错误状态码约定：

| 场景 | HTTP | error 示例 |
|---|---|---|
| question 空 / 超长 / 空白 | 422 | FastAPI 参数校验 |
| LLM 输出非法（JSON/表/字段/confidence） | 502 | `Schema linking failed: 表不存在: payments` |
| Provider 认证失败（401/403） | 502 | `Mimo authentication failed` |
| Provider 限流/超时/5xx/Key 未配置等 | 503 | `Mimo network error` 等 |
| 未预期异常 | 500 | `Schema linking internal error` |

未接入前端：本任务不修改 frontend。

## 8. 测试

位置 `backend/tests/`（全部 mock LLMProvider，不真实调用 Mimo）：

- `test_schema_linking.py`：SchemaCatalog 来自真实数据库（5 表、真实字段）、
  Prompt 含 Schema 与 cancelled 语义、正常链接、JSON 围栏解析、
  非 JSON/缺字段/非法表/非法字段/字段表不匹配/confidence 越界全部拒绝、
  无关问题空匹配、Provider 异常透传、去重；
- `test_schema_link_api.py`：POST /api/schema/link 200 正常、空/空白/超长 422、
  非 JSON 502、非法表 502、Provider 认证 502、Key 未配置 503、无关问题 200。

运行：

```bash
pytest -q            # 89 通过（58 原有 + 31 新增）
python -m compileall backend
```

## 9. 真实验证（scripts/test_schema_linking.py）

```bash
python scripts/test_schema_linking.py
```

- 真实调用 Mimo V2.5 Pro 完成 3 个问题的 Schema Linking；
- 输出 Question / Linked Tables / Linked Columns / Confidence / Result；
- 禁止输出 API Key；结果诚实上报。

### 2026-09-15 验证记录

- `pytest`、`compileall`、`GET /api/health`、`GET /api/system/database`、
  `/docs`、路由注册：全部通过；
- **真实 Mimo 调用：执行失败**。

  **原因**：Xiaomi MiMo 官方端点（`api.xiaomimimo.com`）当天持续不可用——
  通过 curl 直接探测 `/v1/models` 与 `/v1/chat/completions` 均在 TLS 层
  连接失败（`SSL connect error`，HTTP 000，重复多次）；此前数小时相同的
  Provider 代码与配置通过 `POST /api/llm/test` 真实调用多次成功
  （记录于 docs/llm-integration.md）。判断为上游服务不稳定，非本项目代码问题。
  后端对 `POST /api/schema/link` 的 Live 请求正确返回结构化错误
  （503 `Mimo network error`），无 traceback 泄漏。

## 10. 当前限制

```text
SQL Generator：未实现
SQL Validator：未实现
SQL Executor：未实现
SQL Repair：未实现
Few-shot Retrieval：未实现
RAG / Vector DB：未实现
LangGraph 完整 Agent：未接入
multi-turn：未实现
```