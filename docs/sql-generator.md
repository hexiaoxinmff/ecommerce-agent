# SQL Generator（Text2SQL 基础能力）说明

> 阶段：阶段 4-任务 5（SQL Generator / Text2SQL 基础能力）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 概述

建立最小 Text2SQL 生成链：

```text
User Question
    ↓
Schema Linking（复用阶段 4-任务 3）
    ↓
Few-shot Retrieval（复用阶段 4-任务 4）
    ↓
SQL Generator（Mimo V2.5 Pro，经 LLMProvider 抽象）
    ↓
SQL Safety Validation（sqlglot 只读单语句校验 + Schema 一致性）
    ↓
SQLGenerationResult
```

> **当前阶段只生成和校验 SQL，不执行 SQL，不进行自动 Repair、不做失败重试。**

## 2. SQL Generator 架构

```text
backend/app/sqlgen/
├─ errors.py          # 异常体系（OutputInvalid / SchemaMismatch / Unsafe / TableMismatch）
├─ prompt.py          # Prompt 构建（问题 + Schema Linking + Few-shot 完整内容）
├─ safety.py          # SQL 安全/结构校验（sqlglot）+ 表引用提取
├─ validator.py       # LLM 输出解析 + Schema 一致性 + 表引用一致
└─ generator.py       # SQLGenerator 编排
```

```text
API
 ↓
SQLGenerator
 ├── SchemaLinker      （复用，经 LLMProvider）
 ├── FewShotRetriever  （复用，纯本地）
 └── LLMProvider       （当前 MimoProvider）
```

SQLGenerator 只能依赖 `LLMProvider` 抽象；禁止 `SQLGenerator → OpenAI SDK / Mimo API`。

## 3. 输入

`SQLGenerationRequest{question}`（1~500 字符，空白拒收）。

## 4. Schema Linking 如何接入

`SQLGenerator` 内部组合 `SchemaLinker`（`schema_linker.link(question)`），
拿到 `SchemaLinkResult{tables, columns, reasons, confidence}`，
作为 Prompt 的「Schema Linking 结果」并用于后续校验的**允许对象集合**。

## 5. Few-shot 如何接入

`SQLGenerator` 内部组合 `FewShotRetriever`，
以 `FewShotQuery(question, tables=link.tables, columns=link.columns, top_k=3)`
检索 Top-3；**必须把 example 的 question / SQL / explanation 完整放入 Prompt**
（不只是 example_id）。结果中的 `fewshot_examples` 为实际检索到的 example_id。

## 6. Prompt 设计

- System：电商数据分析 Agent 的 SQL Generator，任务生成一条只读 SQLite SQL，不执行；
- User 包含：用户问题、Schema Linking 结果（相关表/字段）、Few-shot Examples
  （Top-3 完整内容）、业务语义（subtotal 明细金额 / total_amount 最终支付金额 /
  实际销售额排除 cancelled / ISO 日期）、硬性约束（只用提供对象、禁止创造、
  只读 SQL、禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/REPLACE/TRUNCATE、
  单语句、不执行 SQL）、输出要求（严格 JSON、SQL 不放代码块）。

## 7. LLM 输出格式

```json
{
  "sql": "SELECT ...",
  "explanation": "按商品汇总有效订单的明细销售额并降序排序。",
  "tables": ["orders", "order_items", "products"],
  "columns": ["orders.order_date", "orders.status", "..."]
}
```

不接受 "好的，下面是 SQL：```sql..." 形式；如带 ```json 围栏，程序自动剥离。

## 8. JSON 解析

- 剥离 ```json 围栏后取最外层 `{...}`；
- 解析失败 / 非对象 / sql 非空字符串 / tables/columns 非字符串数组 /
  explanation 非字符串 -> `SQLGenOutputInvalidError`（明确失败）。

## 9. SQL Safety Validation（safety.py，基于 sqlglot，SQLite 方言）

不执行 SQL，仅静态分析：

- SQLite 方言可解析；
- 必须单条语句；
- 顶层必须 SELECT / WITH（含 UNION 等集合查询）；
- 不得包含 Insert/Update/Delete/Drop/Create/Alter/Replace/Pragma 节点；
- 拒绝示例：`DELETE FROM orders`、`DROP TABLE orders`、
  `UPDATE orders SET total_amount=0`、`SELECT 1; DELETE FROM orders` 等。

## 10. Schema 一致性校验（validator.py）

- `tables`：必须真实存在且 ⊆ Schema Linking 提供的表（出现 `payments` 之类拒绝）；
- `columns`：必须 `表.字段`，表 ∈ Schema Linking 提供的表，字段真实存在；
- SQL 表引用一致：用 sqlglot AST 提取 FROM 表名（CTE 名称自动剔除），
  引用的表必须 ⊆ Schema Linking 提供的表，否则 `SQLTableMismatchError`。

所有校验失败 → 明确失败；**禁止 fake success（如偷偷返回 SELECT 1）**。

## 11. API

```http
POST /api/sql/generate
{ "question": "近30天销售额最高的商品有哪些？" }
```

成功（200）：

```json
{
  "success": true,
  "result": {
    "question": "近30天销售额最高的商品有哪些？",
    "sql": "SELECT ...",
    "tables": ["orders", "order_items", "products"],
    "columns": ["..."],
    "fewshot_examples": ["ex_001", "ex_006", "ex_003"],
    "explanation": "..."
  },
  "error": ""
}
```

- `result.question` 必须保留用户**原始问题**（不在结果中改写）；
- 错误状态码：参数校验 422；Few-shot 数据集 500；Schema Linking 输出非法 /
  LLM 输出非法 / SQL 不安全 / 多语句 / 表引用越界 502；Provider 失败
  （401/403->502，其余->503）；未预期异常 500（固定文案）。

## 12. 测试

- `backend/tests/test_sql_generator.py`（unit，mock SchemaLinker / FewShotRetriever /
  LLMProvider）：正常生成、八种非法 SQL 拒绝、不存在表/字段拒绝、
  Schema Linking 未提供对象拒绝、同名真实表拒绝（users）、非法 JSON 拒绝、
  代码块可解析、WITH CTE 成功且 CTE 名被过滤、SQL 表引用越界拒绝、question 保留、
  Prompt 含问题/Few-shot/业务语义；
- `backend/tests/test_sql_generate_api.py`（mock SQLGenerator）：
  正常 200、question 空 422、Unsafe/SchemaMismatch/TableMismatch/InvalidJSON/
  SchemaLinking 失败 502、Few-shot 数据集异常 500、Provider 认证 502、
  Key 未配置 503、未预期异常 500（不泄漏路径）。

```bash
pytest -q        # 165 passed（129 原有 + 36 新增）
```

## 13. 真实验证（scripts/test_sql_generator.py）

链路：Question -> Schema Linking -> Few-shot -> Mimo -> SQL Generation -> 安全校验
（**不执行生成 SQL**）。结果（2026-09-15，官方端点不稳）：

- Q1「近30天销售额最高的商品有哪些？」→ **成功**（few-shot ex_001/ex_006/ex_003），
  生成 SQL 为 `SELECT p.name, SUM(oi.subtotal) ... WHERE o.order_date >= date('now','-30 day') AND o.status != 'cancelled' GROUP BY p.id ORDER BY total_sales DESC`，校验 PASS；
- Q2「哪个地区的用户最多？」→ **失败**：`LLMNetworkError: Mimo network error`
  （官方端点间歇性单连接断连，非本项目代码问题；按任务要求不做生成重试）；
- Q3「哪个商品类别销售额最高？」→ **成功**（few-shot ex_003/ex_008/ex_001），
  生成 SQL 为 `SELECT c.name, SUM(oi.subtotal) ... JOIN categories ... WHERE o.status != 'cancelled' GROUP BY c.id ORDER BY total_sales DESC`，校验 PASS。

Live `POST /api/sql/generate`：路由注册正常（openapi 确认）；一次真实调用因上游
断连返回结构化 `{"success":false,"error":"Mimo network error"}`（HTTP 503），
无 traceback 泄漏。

> 未将 Mock 成功当作真实模型验证成功：上表中的成功均为 Mimo 真实返回并复核通过。

## 14. 当前限制

```text
SQL Executor：未实现（本阶段禁止执行生成的 SQL）
SQL Repair / 自动修复：未实现（禁止失败后自动再调用 Mimo）
SQL Auto Retry：未实现
LangGraph：未接入
Multi-turn：未实现
Chart / Result Analysis / Conclusion Generation：未实现
前端：未修改
数据库：未修改（全程只读，SHA256 前后一致）
```