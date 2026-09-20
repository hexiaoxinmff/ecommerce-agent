# SQL Executor（Read-only SQL Execution）说明

> 阶段：阶段 4-任务 6（SQL Executor / Read-only SQL Execution）
> 日期：2026-09-15
> 本文档只记录**已经真实实现**的内容。

---

## 1. 概述

首次真正执行生成的 SQL：

```text
SQL（来自 Generator / 人工）
    ↓
Executor Safety Validation（最后一道安全边界）
    ↓
现有 SQLite 只读层（mode=ro + PRAGMA query_only=ON）
    ↓
fetchmany 截断保护
    ↓
结构化结果（columns / rows / row_count / truncated / execution_time_ms）
```

本阶段**不做 SQL Repair、不做多次生成、不做图表、不做结论生成、
不做 LangGraph、不做 Multi-turn**。

## 2. 架构

```text
backend/app/sqlexec/
├─ errors.py        # 异常体系（基类 + Safety + DatabaseError）
├─ models.py        # SQLExecutionRequest / SQLExecutionResult / SQLExecutionResponse
└─ executor.py      # 只读执行核心，MAX_RESULT_ROWS = 500
```

依赖关系：

```text
SQL / API
    ↓
SQLExecutor（独立，不依赖 SQLGenerator / LLMProvider）
    ↓
app.sqlgen.safety.check_sql_safety（复用阶段 5 的安全校验）
    ↓
app.db.sqlite.get_connection（复用现有只读层，无第二套连接/路径配置）
```

## 3. 输入/输出结构

请求（只接收 SQL，不接收自然语言问题）：

```json
{ "sql": "SELECT region, COUNT(*) AS user_count FROM users GROUP BY region ORDER BY user_count DESC" }
```

- 非空、非空白、长度 ≤ 10000（超限 422）；
- 执行前**必须再次**通过 `check_sql_safety`（即使上游已校验过也不信任）。

结果：

```json
{
  "success": true,
  "result": {
    "columns": ["region", "user_count"],
    "rows": [["广东", 246], ["江苏", 205], "..."],
    "row_count": 15,
    "truncated": false,
    "execution_time_ms": 1.47
  },
  "error": ""
}
```

- `row_count` = **实际返回给调用方的行数**（≤ MAX_RESULT_ROWS），
  不是数据库完整总数（不为精确总数二次执行 SQL）；
- `truncated=true` 表示数据库实际结果超过上限被截断；
- NULL 保留为 `None` → JSON `null`，不做任何格式化/日期金额转换。

## 4. 结果集大小保护

- `MAX_RESULT_ROWS = 500`（单处常量配置，见 executor.py）；
- 使用 `cursor.fetchmany(MAX_RESULT_ROWS + 1)` 判断是否超过上限，
  不把全部结果载入内存；超过则 `truncated=True` 并只保留前 500 行；
- `execution_time_ms` 只统计 `cursor.execute + fetch`，不含任何 Mimo 时间。

## 5. 执行安全

- 复用 `app.sqlgen.safety.check_sql_safety`（sqlglot，SQLite 方言）：
  单语句、顶层 SELECT/WITH、无 Insert/Update/Delete/Drop/Create/Alter/
  Replace/Pragma 节点、可解析；
- 即使 SQL 通过校验，也只读连接（mode=ro + query_only=ON）从物理上
  拒绝任何写行为——双重保护，任何执行失败都不能绕过只读保护；
- 全部恶意 SQL 在执行前被拒绝，数据库中不产生任何变化。

## 6. API

```http
POST /api/sql/execute
```

| 场景 | HTTP | 说明 |
|---|---|---|
| sql 空/空白/超长 | 422 | 参数校验 |
| 安全校验失败（写操作/多语句/无法解析/PRAGMA） | 422 | `SQL rejected: ...` |
| 数据库执行异常（语法错误/表不存在等） | 500 | 简短错误，不泄漏路径/traceback |
| 结果超限 | 200 | `truncated=true`（查询本身成功） |
| 未预期异常 | 500 | 固定文案 |

## 7. 测试

新增两个测试文件（全部真实只读数据库执行，不调用 Mimo）：

- `backend/tests/test_sql_executor.py`：正常分组查询 / SELECT 1 / NULL /
  WITH / UNION / 可 JSON 序列化；INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/
  REPLACE/PRAGMA/多语句/无法解析/空白 全部在执行前拒绝；数据库执行异常；
  **截断保护（users 全表 → 500 行 + truncated）**；**数据库零变更
  （执行查询 + 尝试 8 类恶意 SQL 后 SHA256 前后一致）**；
- `backend/tests/test_sql_execute_api.py`：200 正常 / NULL 序列化 null /
  空/空白/超长 422 / 8 类恶意 SQL 422 / 数据库异常 500 / 截断仍 200 /
  未预期异常固定文案。

```bash
pytest -q        # 202 passed（165 原有 + 37 新增）
```

## 8. 真实验证（scripts/test_sql_executor.py，不调用 Mimo）

- 「用户按地区分布」`SELECT region, COUNT(*) ... GROUP BY region`：
  15 行、truncated=False、耗时 ~1.7ms；
- 「商品销售额 Top 5（排除 cancelled）」JOIN 三表 SUM(subtotal)：
  5 行、耗时 ~15.5ms；
- `SELECT NULL AS value`：`[[null]]` 正确序列化。

Live `POST /api/sql/execute`：200，返回真实结果（广东 246 / 江苏 205 / … 共 15 行）。

## 9. 与阶段 4-任务 5 的衔接

- Task 5 输出 `SQLGenerationResult`，Task 6 输出 `SQLExecutionResult`，
  两者暂时不强耦合；Executors 保持独立（核心能力 `SQLExecutor.execute(sql)`）；
- 后续完整 Agent（LangGraph）才会把 Question → Schema Linking → Few-shot →
  Generator → Validation → Executor → Result 串起来。

## 10. 当前限制

```text
SQL Repair：未实现（执行失败不会重新生成/重试）
SQL Auto Retry：未实现
结论生成 / 图表：未实现
LangGraph：未接入
Multi-turn：未实现
前端：未修改
数据库：未修改（全程只读，SHA256 前后一致）
```