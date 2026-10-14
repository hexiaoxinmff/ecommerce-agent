# Task 37 — SQL Scope / Alias 静态校验（E-0099 确定性缺陷修复）

- **报告 ID**：`task37_sql_scope_alias_validation`
- **日期**：2026-09-20
- **基线**：`35a9ad6`（`master` = `HEAD` = `release_baseline_20260920`）
- **状态**：`COMPLETE`
- **性质**：单变量确定性校验任务，**零 LLM 调用**

---

## 1. 任务目标

针对已确认的 E-0099 类错误：SQL 能通过语法解析，但 SELECT / WHERE / JOIN
引用了**未定义的表别名**，直到执行阶段才报 `no such column: r.region`。

目标是在 SQL 执行前**尽可能提前发现**「未定义 alias / column qualifier」错误，
阻止这类必然失败的 SQL 进入 execute 阶段。**不**以提高整体准确率为目标，
**不**修改 Prompt / Few-shot / Schema Linking / Repair 策略。

---

## 2. 审计结论（先审计后编码）

### 2.1 当前 SQL validation 在哪里？

| 层 | 文件 | 职责 |
|---|---|---|
| 生成后校验 | `backend/app/sqlgen/validator.py` | JSON 结构、tables/columns ⊆ Schema Linking、安全性 |
| 安全/结构 | `backend/app/sqlgen/safety.py` | sqlglot 解析、单条语句、只读 SELECT/WITH、提取引用表 |
| Graph 节点 | `backend/app/agent/nodes.py::sql_safety_node` | 调用 `check_sql_safety`，失败则直接终态 |
| 执行前 | `backend/app/sqlexec/executor.py` | **再次** Safety 校验（最后一道边界） |
| Repair 输出 | `backend/app/sqlrepair/validator.py` | Safety + 表一致性 + 有前缀列存在性 |

### 2.2 最合适的插入点

**主插入点 = `sqlexec/executor.py::execute`**，在 Safety 校验之后、
**打开数据库连接之前**。

理由：这是唯一一个「首次执行」与「Repair 后执行」都必须经过的收窄口，
一处接入即可覆盖两条执行路径，且不需要改动 Graph 结构或新增节点。

**次插入点 = `sqlrepair/validator.py::validate_repair_output`**，
拒绝「Repair 后仍引用不存在别名」的输出。

### 2.3 项目使用什么 SQL parser？是否已依赖 sqlglot？

**是**。`sqlglot==30.18.0`（已冻结在 `requirements-lock.txt`），
在 `sqlgen/safety.py`、`sqlcheck/fanout_detector.py`、`sqlrepair/validator.py`
中已被广泛使用。**无需引入新依赖**。

### 2.4 没有 sqlglot 的话有无其他解析能力？

不适用 —— sqlglot 已是既成事实的解析层，且其 `optimizer.scope` 模块提供了
现成的**查询块作用域分析**（`traverse_scope` / `Scope.sources` /
`Scope.external_columns`），正是本任务所需。

### 2.5 静态校验失败后应返回什么类型的内部错误？

**`SQLExecutionScopeError`，继承 `SQLExecutionDatabaseError`**（而非
`SQLExecutionSafetyError`）。这是一个**关键设计决策**：

- 语义上，该错误**等同于**数据库会报的 `no such column`，只是被提前发现，
  因此归入「数据库阶段」故障域才是诚实的；
- `route_after_execute` 对 `execute_error_kind == "database"` 且
  `repair_count == 0` 时返回 `"repair"`。继承 DatabaseError 保证
  **Repair 流程不被静默缩短**；
- 若继承 SafetyError，SQL 会被直接判死、永不进入 Repair —— 这是对既有
  行为的隐性破坏，本任务明确禁止。

### 2.6 是否会影响现有 execute-with-repair 行为？

**不会**。已通过两条独立证据验证：

1. **路由层**：`route_after_execute({executed_ok:False, execute_error_kind:"database", repair_count:0})`
   仍返回 `"repair"`；
2. **端到端**：打桩 provider 场景下，Scope 错误触发 Repair（provider 调用 1 次），
   修复后 SQL 成功执行 15 行。

---

## 3. E-0099 真实执行路径（来自冻结基线）

```
schema_link       success   8107.3 ms
fewshot_retrieve  success      0.2 ms
sql_generate      success   9394.6 ms
sql_safety        success      3.4 ms   ← 别名错误在此处完全无法被发现
sql_execute       error        4.2 ms   ← 这里才报 no such column: r.region
sql_repair        error     8283.2 ms   ← Repair 输出被 Schema 校验拒绝
sql_execute_repaired skipped
result            success
```

**失败机理**：

```sql
WITH region_sales AS (SELECT o.region, SUM(oi.subtotal) AS total_sales
                      FROM order_items oi JOIN orders o ON o.id = oi.order_id
                      GROUP BY o.region)
SELECT r.region, rs.total_sales      -- 引用了 r，但下面定义的是 rs
FROM region_sales rs
```

SQLite 把 `r` 当作**列名**而非限定符解析，因此语法层完全通过。
Repair 拿到的是模糊的 "no such column: r.region"，改错方向
（基线实际输出了 `rs.region`，又被 Schema 校验拒绝）。

**全库扫描**：冻结基线 100 题中，`sql_execute` 节点 `status=error` 的题
**仅 1 道**，即 E-0099；报错信息为 `no such column` 的也仅此 1 道。

---

## 4. 实现内容

### 4.1 新增模块 `backend/app/sqlcheck/scope_validator.py`

放在既有 `sqlcheck` 包内 —— 该包已有 `fanout_detector.py`，契约完全一致
（只读 AST、非干预、无 LLM 依赖）。

对外 API：

```python
check_sql_scope(sql: str) -> ScopeCheckResult   # ok / violations
```

### 4.2 可见性规则（决定假阳性率的核心）

> 带限定符的列引用 `q.col` 在某查询块内合法，当且仅当限定符 `q` 出现在
> **该查询块自身或其任意外层祖先查询块**的 FROM/JOIN 数据源中（含 CTE 名）。

**为什么必须回溯祖先链**：相关子查询会合法地引用外层别名：

```sql
SELECT ... FROM orders o
WHERE o.total > (SELECT AVG(p2.price) FROM products p2
                 WHERE p2.category_id = o.category_id)   -- o 来自外层，合法
```

朴素地只看「本查询块 sources」（sqlglot `Scope` 的默认语义）会在 100 题
gold SQL 上产生 **3 处误报**（E-0060 / E-0087 / E-0095）—— 因为相关子查询
里对外层别名的引用全部落在 `external_columns` 中。

### 4.3 接入点

| # | 文件 | 变更 |
|---|---|---|
| 1 | `sqlexec/errors.py` | 新增 `SQLExecutionScopeError(SQLExecutionDatabaseError)` |
| 2 | `sqlexec/executor.py` | Safety 之后、建连之前加 Scope 校验 |
| 3 | `sqlrepair/validator.py` | Repair 输出加同名校验（抛 `SQLRepairSchemaError`） |

**净变更：3 个已有文件 +43/−5，1 个新模块。**

---

## 5. 验证结果

### 5.1 混淆矩阵（100 题冻结基线，零 LLM）

| 指标 | 值 | 门槛 | 结论 |
|---|---|---|---|
| gold SQL 假阳性 | **0 / 100** | 0 | PASS |
| pred 误报（命中但实际未失败） | **0** | 空 | PASS |
| pred 漏报（实际失败但未命中） | **0** | 空 | PASS |
| 真阳性 | **1**（E-0099） | ≥1 | PASS |

命中集合 `{E-0099}` 与真实 `no such column` 失败集合 `{E-0099}`
**完全相等**。

### 5.2 合法 SQL 回归（15 类形态，全部放行）

基础别名 / 表名限定符 / 裸列名 / JOIN / CTE 引用 / CTE 带别名 /
子查询别名 / UNION / 嵌套子查询 / ORDER BY 引用 SELECT 别名 / HAVING /
GROUP BY 未选中列 / 三个真实相关子查询案例（E-0060/0087/0095）/ CROSS JOIN CTE。

### 5.3 测试

```
backend/tests/test_task37_sql_scope.py    33 passed
backend/tests（全量）                     470 passed, 0 failed  (25.77 s)
```

`470 = 437（Task 36 结束时）+ 33（本次新增）`。**零回归。**

### 5.4 Repair 路由行为

```
route_after_execute(database, repair_count=0) = 'repair'   ✔ 保持
route_after_execute(safety,   repair_count=0) = 'result'   ✔ 保持
SQLExecutionScopeError 是 DatabaseError 子类   ✔
SQLExecutionScopeError 不是 SafetyError 子类   ✔
端到端：Scope 错误 -> Repair 触发 -> 修复后执行 15 行 ✔
```

---

## 6. 错误信息改进（对 Repair 的可操作性）

| | 修复前 | 修复后 |
|---|---|---|
| 消息 | `SQL 执行失败: no such column: r.region` | `SQL 引用了未定义的表别名: 未定义的别名 r: r.region` |
| 可定位性 | 低（SQLite 不指出这是别名问题） | 高（明确指出限定符 `r` 未定义） |

---

## 7. 重要发现：一个**既有**缺陷（不属本任务边界）

在验证 Repair 路径时发现：`sqlrepair/validator.py::_check_spelled_columns`
（**master 基线既有实现，未被我修改逻辑**）把 `Column.table` 直接当作真实表名
送去 catalog 查列：

```python
if table and not catalog.has_column(table, name):
    raise SQLRepairSchemaError(f"Repair SQL 引用了不存在的字段: {table}.{name}")
```

由于 catalog 只含真实表（`users/categories/products/orders/order_items`），
**任何 CTE 别名限定符都会被判为「字段不存在」**：

| 测试用例 | 结果 |
|---|---|
| `SELECT orders.region FROM orders` | PASS |
| `WITH t AS (...) SELECT rs.region FROM t rs` | **REJECT**（rs 不是真实表） |
| `WITH t AS (...) SELECT ps.region FROM t ps` | **REJECT** |

**已用与 `git HEAD` 逐字相同的实现独立复现，确认它是基线既有行为，
非 Task 37 引入。**

**对本任务目标的影响（诚实披露）**：

- ✅ 本次修复能**准确诊断** E-0099 类错误，不再给出模糊的 `no such column`；
- ❌ **无法**让该类 Repair 自动成功 —— 因为修复后的 CTE SQL 仍会被上述
  既有缺陷拒绝；
- 未在本任务中修复该缺陷：修它会**改变 Repair 的接受行为**，违反
  「单变量确定性校验」纪律。已固化为测试
  `test_baseline_spelled_column_check_rejects_cte_alias`，防止将来被误认
  为 Task 37 的回归。

**建议后续独立任务处理**：让 `_check_spelled_columns` 区分
「真实表名」与「别名/CTE 名」，仅对前者做 catalog 查列。

---

## 8. 变更边界合规性

| 禁止项 | 状态 |
|---|---|
| Benchmark Gold SQL | 未改（sha256 `dba277cc…`） |
| benchmark questions | 未改 |
| evaluation normalization / metrics | 未改 |
| baseline 数据 | 未改 |
| Few-shot 数据 | 未改（sha256 `3c8dc8ea…`） |
| Prompt V1.3 | 未改（sha256 `31244e61…`） |
| Schema Linking 算法 | 未改 |
| Repair Prompt | 未改 |
| Agent 主体无关逻辑 | 未改 |
| provider 配置 / Mimo API Key | 未改 |
| 数据库 schema / 数据 | 未改（sha256 `65e5d8b2…`） |
| Prompt 重写 / Few-shot 扩充 | 未做 |
| 新增 LLM 调用 | **零** LLM 调用 |
| 自动 SQL rewrite / AST 改写 | 未做（只读检查） |

**本次改动文件**：

```
 M backend/app/sqlexec/errors.py        (+16/-1)
 M backend/app/sqlexec/executor.py      (+18/-2)
 M backend/app/sqlrepair/validator.py   (+14/-2)
?? backend/app/sqlcheck/scope_validator.py   (新模块)
?? backend/tests/test_task37_sql_scope.py
?? scripts/task37_scope_impact_check.py
?? scripts/task37_repair_routing_check.py
```

---

## 9. 产物哈希

| 文件 | SHA256 |
|---|---|
| `backend/app/sqlcheck/scope_validator.py` | `ed3bcd6532ff11560dc0e92b7a9e6bc6e45476e8abfb12227debf45d399b1ddd` |
| `backend/app/sqlexec/errors.py` | `904199edce69c74fe2007da38286346e0fc8598ac9cc2ffe73936c0e67e642b9` |
| `backend/app/sqlexec/executor.py` | `56886c8a6cd37aac85f4583663898c50e8ec2d20262e3cf8a845e34488621104` |
| `backend/app/sqlrepair/validator.py` | `c30bfd97230bf6fea76b3fabf7b70a8cf4e1409a96fedb4b83bcd35b9368fe69` |
| `backend/tests/test_task37_sql_scope.py` | `ad99131e19ba713935b168af5edee374636aede41594c9f08b8517c38a662fca` |
| `scripts/task37_scope_impact_check.py` | `fe735cbc57fcefe9fc8562dada6ca430b02712e62fea9e9e0f10366a1c2842f3` |
| `scripts/task37_repair_routing_check.py` | `5b56bc5d3563014b9471655f8bc43a544c01bcabe67e3dc1fb3d010a1227ee57` |

---

## 10. 局限性与申报口径

- 本任务**只**处理「带限定符的列引用指向未定义别名」这一类错误。
  **裸列名**（无限定符）的多义性、拼写错误、语义错误不在范围内。
- 未做真实端到端评测。本次修复的效果以**确定性混淆矩阵**呈现
  （TP=1 / FP=0 / FN=0），**不宣称任何准确率或延迟提升**。
- 「提前发现」不等于「修复成功」：见 §7，Repair 仍受既有缺陷阻塞。
- 校验对合法 SQL 是**零成本语义**的（仅多了 1 次已解析 AST 的作用域遍历），
  但本报告**不给出性能数字** —— 未做受控测量。

---

## 11. 结论

| 项 | 结果 |
|---|---|
| 审计 | 完成 |
| 实现 | 1 个新模块 + 3 个接入点 |
| gold 假阳性 | **0/100** |
| E-0099 检出 | **YES**（准确指出未定义限定符 `r`） |
| pred 误报 / 漏报 | **0 / 0** |
| 全量测试 | **470 passed / 0 failed** |
| Repair 路由 | **行为不变**（仍触发一次） |
| 变更边界 | **完全合规** |
| LLM 调用 | **0** |

**Status: TASK_37_COMPLETE**
