# SQL Repair（有限异常自修复）说明

> 阶段：阶段 4-任务 7（SQL Repair / 有限异常自修复）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 概述

首次实现有限自修复：

```text
SQL
 ↓
Safety Validation
 ↓
Execute
 ↓ 成功 → Result
 ↓ 失败（数据库执行错误）
Repair LLM（一次）
 ↓
Safety Validation（二次）
 ↓
Execute（第二次，一次）
 ↓ 成功 → Result / 失败 → 明确失败
```

> **当前系统只进行一次有限 SQL Repair，不进行无限自循环**（repair_count ≤ 1，execute_count ≤ 2）。

## 2. Repair 触发条件

只针对**数据库执行阶段**产生的 SQL 错误触发，例如：

```text
no such table: xxx
no such column: xxx
ambiguous column name: xxx
near "...": syntax error
```

## 3. Repair 禁止条件

SQL 在 Safety Validation 阶段就被拒绝（DELETE/UPDATE/DROP/ALTER/CREATE/
PRAGMA/多语句/无法解析）→ **直接失败，禁止触发 Repair**（execute_count=0, repair_count=0）。

## 4. 架构

```text
backend/app/sqlrepair/
├─ errors.py        # SQLRepairError / OutputInvalid / Safety / Schema
├─ models.py        # 请求/结果/闭环诊断模型 + sanitize_execution_error
├─ prompt.py        # Repair Prompt 构建
├─ validator.py     # Repair 输出二次校验（Safety + Schema）
└─ repairer.py      # SQLRepairer + SQLExecuteWithRepairOrchestrator
```

依赖：Repair 只依赖 `LLMProvider` 抽象（当前 MimoProvider）；执行复用
`app.sqlexec.executor`（只读）；校验复用 `app.sqlgen.safety` 与
`SchemaCatalog`，不重写第二套。

## 5. Repair Prompt

System：电商 SQL Repair 组件，修复一条执行失败的 SQLite SQL，只修复不执行。

User 输入上下文（完整）：用户问题 + 原始 SQL + SQLite 执行错误（已清洗）+
Schema Linking（允许的表/字段）+ 当前真实 Schema + Few-shot 参考。

约束：保留用户分析意图；只允许提供的表/字段；只允许 SELECT/WITH；
禁写操作/多语句；不执行；输出严格 JSON；**Repair ≠ 重新生成**——
尽可能保持原 SQL，只修导致失败的具体问题（如 user -> users、user_name -> username）。

业务语义保持：subtotal=明细行金额、total_amount=最终支付金额、
实际销售额/销量默认排除 `orders.status='cancelled'`。

## 6. Repair 输出结构

```json
{ "repaired_sql": "SELECT ...", "repair_reason": "原 SQL 使用了不存在的表 user，改为 users。" }
```

- 支持 ```json 围栏清理；
- 修复前后证据完整保留：`original_sql / repaired_sql / repair_reason /
  original_error / repair_error / repair_success`。

## 7. Safety 二次校验

Repair 出的 SQL 必须重新调用 `app.sqlgen.safety.check_sql_safety`
（与首次同一道闸），**不信任 Repair LLM**。
Repair LLM 返回 DELETE 等 -> `SQLRepairSafetyError`（422 "Repair Safety Rejected"），
且不进入第二次 Execute。

## 8. Schema 二次校验

- SQL 引用表（sqlglot 提取，CTE 名剔除）⊆ Schema Linking tables；
- 有表前缀的列引用（table.column）必须真实存在；
- 越界 -> `SQLRepairSchemaError`（502），不执行。

## 9. 最大次数与计数语义

```text
execute_count <= 2
repair_count  <= 1
```

| 场景 | execute_count | repair_count |
|---|---|---|
| 无错误 | 1 | 0 |
| 一次 Repair 成功 | 2 | 1 |
| Repair 后仍失败 | 2 | 1 |
| Safety 阶段失败（首次） | 0 | 0 |
| Repair 输出 Safety/Schema 拒绝 | 1 | 1 |

## 10. API

### POST /api/sql/repair（Repair 能力单独测试，不执行 Repair SQL）

请求：`{question, original_sql, error_message, tables, columns}`

成功（200）返回 `{success, result:{original_sql, repaired_sql, repair_reason}, error}`。

### POST /api/sql/execute-with-repair（有限 Repair 闭环）

请求：`{question, sql, tables, columns}`

- 闭环成功（200）：`result` 含 `execute_count / repair_count / original_error /
  repaired_sql / repair_reason / result(执行结果)`；
- 最终失败（422，success=false）：同样返回上述诊断字段 + `repair_error`。

### POST /api/sql/execute（保持不变）

纯 `Safety -> Execute`，不自动 Repair。

状态码：参数 422；Safety 拒绝 422；Repair JSON 非法 / Schema 越界 502；
Provider 认证 502 / 其他 503；闭环最终失败 422；未预期 500。

## 11. 错误信息清洗

`sanitize_execution_error`：仅将错误主体（如 no such column: xxx）传给
Repair LLM；过滤 Windows/POSIX 绝对路径、疑似密钥长串，截断超长文本。

## 12. 测试

新增两个测试文件（26 项）：

- `test_sql_repair.py`（unit + 真实 SQLite 闭环）：表名修复、字段名修复、
  JSON 围栏、Prompt 上下文完整、非 JSON/缺字段/写操作/多语句/表越界/列越界拒绝、
  计数矩阵（1/0、2/1、2/1 失败、0/0、非法 Repair 1/1 不二次执行）、
  **数据库零变更**（修复+恶意 Repair 后 SHA256 一致）、错误清洗；
- `test_sql_repair_api.py`：/api/sql/repair 正常 200、Safety 422、非法 JSON 502、
  空参数 422；/api/sql/execute-with-repair 成功闭环 200（2/1）、无错误 1/0、
  Safety 0/0 422、仍失败 422（诊断保留）、恶意 Repair 1/1 422、空 sql 422。

```bash
pytest -q        # 230 passed（202 原有 + 28 新增）
```

## 13. 真实验证（scripts/test_sql_repair.py，真实 Mimo + 真实 SQLite）

- **Demo A（错误表名 user -> users）**：真实执行成功 ——
  第一次执行错误 `no such table: user` → 真实 Mimo 单次修复 →
  第二次执行成功（15 行，广东 246 / 江苏 205 / …），execute_count=2, repair_count=1；
- **Demo B（错误字段 user_name -> username）**：执行失败 ——
  原因：Repair 阶段官方端点断连（`LLMNetworkError: Mimo network error`），
  如实记录（非代码问题；Mock 测试中同场景修复成功）。
- Live `POST /api/sql/execute-with-repair`：真实成功（user->users，第二次执行
  15 行，execute_count=2, repair_count=1）；
- Live `POST /api/sql/repair`：一次调用遇上游断连返回结构化 503 `Mimo network error`。

## 14. 当前限制

```text
只允许 1 次 Repair / 2 次执行：绝不无限自循环 / 不重试
SQL Auto Retry / retry loop：未实现
LangGraph：未接入
Multi-agent / Multi-turn：未实现
结论生成 / 图表：未实现
Trace UI / Evaluation Benchmark：未实现（后续阶段）
前端：未修改
数据库：未修改（全程只读，SHA256 前后一致 65E5D8B2...）
```