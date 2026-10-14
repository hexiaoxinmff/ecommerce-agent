# Task 48：E11 Query-Block Visibility 最小收口验证

> 目标：只修复 Task 47 暴露的**唯一** E11 归因回归（`E-0093` 的破平键 `c.id` 引用了
> 当前 CTE 不存在的列），并用**最小真实 smoke**（1 次调用）验证收口是否成立。
>
> ⚠️ **调用预算严格分开记账**：本任务 `REAL_API_CALLS = 1`；Task 47 历史 `REAL_API_CALLS = 25`
> （本任务**复用**其记录，0 次新调用）。**绝不写成 Task47 = 26。**

---

## 一、执行摘要

| 项 | 结果 |
|---|---|
| NEW_REAL_API_CALLS | **1**（硬门 1） |
| E0093 | **FIXED**（scope_ok=True / 执行成功 / 结果 == gold） |
| SCOPE_FIX | **CONFIRMED**（离线 fixtures 全过 + 1 次真实 smoke） |
| OFFLINE_SCOPE_TESTS | **14/14 PASS**（另有 77 项既有 pytest 全过） |
| TASK47_REUSED | **25 records**（0 次新调用，只读复核） |
| E11_OVERALL_STATUS | **`NEEDS_FULL_TRIGGER_REVALIDATION`** |
| PROD_TRACKED_CHANGED | **NONE** |
| PROD_UNTRACKED_MODIFIED | **`backend/app/sqlgen/semantic_contracts.py`**（未跟踪生产文件） |
| ENV / DB / GOLD / FEWSHOT CHANGED | **NO / NO / NO / NO** |
| commit | **无** |

---

## 二、Phase 1：规则最小收口（0 API）

### 2.1 改了什么

在 `backend/app/sqlgen/semantic_contracts.py::RankingTiebreakContract.to_prompt_block()`
的「正确写法示例」之后**插入**两条（**只增不减**）：

1. ❌ **破平键必须属于当前 query block 可见且实际存在的列**：只能引用当前 `FROM`/`JOIN` 中
   **真实存在的关系**的列，或当前 `CTE` / 子查询**已经暴露**（出现在其输出列中）的列；
   不得引用当前 `FROM`/`JOIN` 里不存在的关系，也不得引用当前 `CTE` / 子查询未暴露的列。
   反例直接写进文本：`WITH s AS (SELECT o.region, c.name AS category_name, …) …
   ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC)`
   ⇒ `c` 是 CTE 别名而该 CTE 无 `id` ⇒ `no such column: c.id`。
2. 若当前 query block 确实**没有**任何可用主键或业务唯一标识，则**宁可不追加破平键**，
   也不要臆造一个不可见 / 不存在的列。

### 2.2 Task 46 的禁止项**全部逐字保留**

| 禁止项 | 在文本中 |
|---|---|
| 不得进 SELECT | ✅ `禁止把破平键写进 SELECT` |
| 不得进 GROUP BY | ✅ `禁止把破平键写进 GROUP BY` + `GROUP BY …, p.id` |
| 不得改 WHERE / HAVING | ✅ `禁止因为本契约改动 WHERE / HAVING 中的任何过滤条件` |
| 不得改 JOIN | ✅ 由 WHERE/HAVING 与「唯一作用是 ORDER BY 追加」共同覆盖 |
| 不得改聚合 / 聚合粒度 | ✅ `禁止因为本契约改变原有聚合粒度` |
| 不得改 LIMIT/OFFSET | ✅ `除排序外，不得改动 SQL 的任何其他部分` |
| 不得改日期过滤 | ✅ 反例 `substr(order_date, 1, 7) = '2025-10'` |

### 2.3 字节级证据（未跟踪文件怎么证「只改了一处」）

`semantic_contracts.py` 是 **untracked** ⇒ git 里没有基线（这正是 T46 记下的坑）。改用**反推重建法**：

| 项 | 值 |
|---|---|
| 开工前实测文件 sha256 | `418f495032f90938c33fa610c06f8a021aaff2fec102c1ba433cd1823994bb82` |
| 反推（new_string → old_string）后 sha256 | `418f495032f90938c33fa610c06f8a021aaff2fec102c1ba433cd1823994bb82` |
| ⇒ 字节精确重建 | **True** |
| 收工后文件 sha256 | `fcbf8437ea2a0e72780d6594d6c36a9b407e65942f32379d17154c8fefb9a17c` |
| 行级差异 | 新增 **11** 行 / 删除 **0** 行 |
| E11 文本块 sha256（前 → 后） | `de2b2094…b5bbf4f5`（1145B） → `9f4084d3…7f45f783`（1663B） |

> 重建哈希与开工前实测值**逐字符相同** ⇒ 反推是字节精确的 ⇒ 本次改动**就是且仅是**那一处。

**Trigger 定义未动**：`_RANK_TOPN_PATTERN` / `_RANK_SUPERLATIVE_SET_PATTERN` /
`_RANK_EXPLICIT_PATTERN` / `_RANK_SCALAR_ONLY_PATTERN` / `detect_ranking_tiebreak()`
全部未修改（见 §2.3 行级差异 0 删除 + §三 触发面未变）。
**E4 / E9 / E10 未动**；`.env` 内 `LLM_PROVIDER` 仍是 `mimo`。

---

## 三、Phase 2：离线 scope fixtures A~H（0 API）

新增 `e11_scope.py`：**query-block 可见性解析器**（与 Task 47 的结构增量检查器互补）。

**判据**：对每个排名子句（最外层 ORDER BY + 排名函数的窗口 ORDER BY）里的**裸列键**，
解析到它所属 query block 的可见列集合（各 FROM/JOIN 源 ∪ 本块输出别名 ∪ 祖先块相关引用）；
解析不到 ⇒ `SCOPE_UNRESOLVED_COLUMN` / `SCOPE_UNKNOWN_RELATION`。

| Fixture | 内容 | 期望 | 实测 | 结果 |
|---|---|---|---|---|
| A | 当前 query block 可见 `p.id` | VALID | scope_ok=True | ✅ |
| B1 | CTE 只暴露 `product_id`，直接写 `p.id` | INVALID | `SCOPE_UNKNOWN_RELATION: p.id` | ✅ |
| B2 | 同上，直接写 `c.id` | INVALID | `SCOPE_UNKNOWN_RELATION: c.id` | ✅ |
| C | CTE 内部有 `id`，但输出别名是 `pid` ⇒ 外层 `s.id` | INVALID | `SCOPE_UNRESOLVED_COLUMN: s.id` | ✅ |
| D-fabricated | 聚合后只剩 `region/rev`，却写 `o.id` | INVALID | `SCOPE_UNKNOWN_RELATION: o.id` | ✅ |
| D-compliant | 改用可见的业务唯一标识 `region` | VALID | scope_ok=True | ✅ |
| D-text | 规则文本含「宁可不追加破平键」+ 可见性约束 | True | True | ✅ |
| E | `E-0098` 合法 ORDER BY tie-breaker（T47 真实 pred） | VALID | scope_ok=True | ✅ |
| F-groupby | T47 结构检查器仍能检出 GROUP BY 粒度回归 | True | `K_pk_cols_added_to_groupby=['id']` | ✅ |
| F-select | 仍能检出 SELECT 列数变化 | True | 列数 2→3 检出 | ✅ |
| F-timefilter | 仍能检出日期过滤改写 | True | `C_date_rewritten=True` | ✅ |
| G | `E-0093`（T47 真实 pred） | INVALID | `SCOPE_UNRESOLVED_COLUMN: c.id` | ✅ |
| H | 故意构造**合法可见**的破平键（`region` / `category_name`） | VALID | 不误报 | ✅ |
| G-strip | 剥离探针：删掉 `c.id` 后 SQL 可执行 | True | `removed=['c.id']` | ✅ |

**OFFLINE_SCOPE_TESTS = 14/14 PASS**

补充：`pytest backend/tests/test_task46_e11_narrowing.py test_task44_semantic_rules.py
test_sqlgen_prompt_rules.py` ⇒ **77 passed**（旧守卫 + 规则文本契约 + 开关默认关闭逐字节不变）。

### 3.1 检查器自身的两个真实坑（已修，记录在案）

1. ⭐ **`sqlglot` 把 `FROM` / `WITH` 归一化成 `from_` / `with_`**（本仓库 `sqlglot==30.18.0`）。
   第一版写 `sel.args.get("from")` ⇒ **静默返回 None** ⇒ 所有 FROM 源被漏掉
   ⇒ 把 CTE 已暴露的 `product_id` 误报成 scope 违规（`E-0098` 假阳性）。
   **教训：解析器 API 的键名必须实测，不能凭记忆。**
2. ⭐ **两个检查器的键规范化方向相反**：`e11_structure._key_of` 会**去掉表限定符**
   （`c.id asc` → `id asc`），而 `e11_scope` 的违规键保留原文（`c.id`）。
   直接取交集 ⇒ 交集恒为空 ⇒ **归因假阴性**（第一版实测「0 条可归因」）。
   修法：按**裸列名**对齐。

---

## 四、Phase 3：离线复核 Task 47 原始结果（0 API，只读）

**完整性门（全部通过）**：records = **25** / `sum(api_call_count)` = **25** /
`max per question` = **1** / SQL 全文（`full_gold_sql`、`full_pred_sql` 或
`gold_sql_full`、`pred_sql_full`）全部存在 / 含 `[:400]` 截断 = **0**。

**用新 scope checker 重算 25 条 pred**（**不修改** Task47 原始 verdict）：

| 项 | 结果 |
|---|---|
| E11 可归因 scope violation | **1 条 = `E-0093`**（`c.id`） |
| E-0093 是唯一 scope regression | **True** |
| GROUPBY_REGRESSION | **0** |
| SELECT_REGRESSION | **0** |
| TIMEFILTER_REGRESSION | **0** |
| E11_STRUCTURE_OK | **25/25** |

> 日期过滤必须用 Task 47 的 **DB 语义探针**（比较命中的 `order_date` 集合）。
> 第一版漏配探针、退化成语法比较 ⇒ 跑出 **9 条假 TIMEFILTER 回归**、`E11_STRUCTURE_OK` 掉到 16/25。
> 与 T47 的已知结论一致：纯语法比较对等价日期写法必然误报。

---

## 五、Phase 4：单次真实调用（E-0093，硬门 1）

| 项 | 值 |
|---|---|
| Provider | `bailian` / `qwen3.7-flash-2026-07-15`（`BailianProvider`） |
| `SQLGEN_EXTRA_RULES` | `E11`（**仅进程内**） |
| `LLM_PROVIDER` | `bailian`（**仅进程内**；`.env` 仍 `mimo`） |
| NEW_REAL_API_CALLS | **1**（`api_call_count = 1`） |
| `e11_injected` | **True**（`on_hash=7e70820fbe892c05` ≠ `off_hash=195fb62db4cf1b98`） |
| E11 文本块 sha256 | `9f4084d3e7522e6e9f43b92c35d85fa74620703e9e4f1fb976018c807f45f783` |
| thinking 锁（AST） | `enable_thinking` 值节点 = `Constant(False)`；被禁 kwarg/dict 键 = `[]` |
| latency | 5318.09 ms |
| 网络重试 | `_NETWORK_RETRY_DELAYS_SECONDS` 置空（**仅内存**） |

**pred SQL（全文）**：

```sql
WITH region_category_sales AS (SELECT o.region, c.name AS category_name, SUM(oi.subtotal) AS total_sales FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND o.order_date LIKE '2025%' GROUP BY o.region, c.id), ranked AS (SELECT region, category_name, total_sales, ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC) AS rn FROM region_category_sales rcs JOIN categories c ON c.name = rcs.category_name) SELECT region, category_name, ROUND(total_sales, 2) AS total_sales FROM ranked WHERE rn <= 3 ORDER BY region, rn
```

**gold SQL（全文）**：

```sql
WITH region_cat AS (SELECT o.region, c.name AS cat_name, SUM(oi.subtotal) AS revenue FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2025-01-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' GROUP BY o.region, c.id, c.name), ranked AS (SELECT region, cat_name, revenue, ROW_NUMBER() OVER (PARTITION BY region ORDER BY revenue DESC) AS rk FROM region_cat) SELECT region, cat_name, ROUND(revenue, 2) AS revenue FROM ranked WHERE rk <= 3 ORDER BY region, rk
```

**scope 检查（逐键）**：

| 键 | 所属子句 | 判定 |
|---|---|---|
| `region` | outermost_order_by | RESOLVED |
| `rn` | outermost_order_by | RESOLVED |
| `total_sales` | window_order_by(RowNumber) | RESOLVED |
| `c.id` | window_order_by(RowNumber) | **RESOLVED**（`c` = 本块 JOIN 进来的 `categories` 基表） |

⇒ `scope_ok = True`，`violations = []`。

**执行与结果**：`validation_pass=True` / `execution_pass=True` / `result_match=True`
（`compare_results` 判定，`value_type`/`tolerance`/`order_sensitive` 取 benchmark `answer_slots`）。
⇒ **verdict = `FIXED`**，`failure_cause = NONE`。

### 5.1 修复机制（关键，必须如实说明）

Task 47 的 pred：`… ROW_NUMBER() OVER (… ORDER BY total_sales DESC, c.id ASC) … FROM region_category_sales c JOIN categories cat ON c.category_name = cat.name`
—— 此处 `c` 是 **CTE 别名**，该 CTE 无 `id` 列 ⇒ `no such column: c.id`。

Task 48 的 pred：`… ORDER BY total_sales DESC, c.id ASC) … FROM region_category_sales rcs JOIN categories c ON c.name = rcs.category_name`
—— `c` 现在是**本 query block 里真实 JOIN 进来的 `categories` 基表** ⇒ `c.id` 可见。

⭐ **但这不是「纯粹的 ORDER BY 追加」**：为了拿到一个**可见的**标识列，模型在外层
额外加了一个 `JOIN categories c ON c.name = rcs.category_name`。该差异被 Task 47 的
`NON_E11_STRUCTURAL_DIFFS` 记作 `JOIN_CONDITION_DIFF`（**不计入** `E11_STRUCTURE_OK`，因为
它不是 E11 能负责的那部分）。**如实报告：这条 JOIN 是 E11 收口的副作用**（结果未被破坏）。

**安全性核查**：`categories` 共 30 行，`COUNT(DISTINCT name) = 30 = COUNT(DISTINCT id)`
⇒ 按 `name` 连接是 1:1，不会放大行数。`result_match=True` 也印证了这一点。

**其他非 E11 差异**（`NON_E11_STRUCTURAL_DIFFS`，均不改变判定）：
别名差异（`category_name`/`total_sales` vs `cat_name`/`revenue`）、
`WHERE` 的 `rn <= 3` vs `rk <= 3`、以及日期写法 `LIKE '2025%'` vs 年区间。

---

## 六、Phase 5：E-0093 因果探针

**未触发**——E-0093 本次**没有失败**（执行成功且结果与 gold 一致），
因此无需剥离探针来证明因果。为完整性仍离线确认：新增的尾部破平键在
`strip_unresolved_tiebreak` 下**不再被判为未解析**（`violations=[]` ⇒ `changed=False`，无可剥离项）。

> 对照：Task 47 的同一探针在旧 pred 上 `removed=['c.id']` 且剥离后可执行（45 行）——
> 这正是当时判定 `E11_STRUCTURE` 归因的机制级证据。

---

## 七、Phase 6：最终结论

| 条件 | 结果 |
|---|---|
| E-0093 scope regression = 0 | ✅（`scope_ok=True`，`violations=[]`） |
| 离线 scope fixtures 全 PASS | ✅（14/14） |
| Task 47 三类旧副作用仍为 0 | ✅（GROUPBY/SELECT/TIMEFILTER = 0/0/0，离线重算） |
| E-0098 历史正向控制保持 PASS | ✅（**未重新调用**；沿用 Task 47 记录，且本次离线重算 `scope_ok=True`） |

⇒ **E11_SCOPE_FIX = CONFIRMED**

**但 `E11_OVERALL_STATUS = NEEDS_FULL_TRIGGER_REVALIDATION`，不写 `READY_FOR_100Q`。**
原因（与任务书一致）：
Task 47 的 25 题是在**旧 wording**下取得的；本次只有 `E-0093` 用**新 wording** 重新 smoke 了 1 次。
**不能用 1 题新结果去覆盖 24 题旧结果**——新 wording 是否让另外 24 题全部保持通过，**未验证**。

---

## 八、Phase 7：调用预算（严格分开记账）

| 任务 | REAL_API_CALLS | 说明 |
|---|---|---|
| **Task 48（本任务）** | **1** | 只测 `E-0093`，硬门 = 1，实际 = 1 |
| Task 47（历史） | 25 | **本任务 0 次重跑**，仅只读复核其 `raw_results.json` |
| 合计 | — | **不写 Task47 = 26**；两笔账各自独立 |

---

## 九、Phase 8：隔离

| 项 | 结果 |
|---|---|
| HEAD 不变 | **True**（`6c5f51c1d25c703cc04d93a3577072552800fa51`） |
| index 不变 | **True**（staged = 0） |
| tracked 文件 sha256（824 个） | **0 个变化** |
| 冻结物（benchmark / fewshot / db / .env） | **0 个变化** |
| `.env` 的 `LLM_PROVIDER` | 仍为 `mimo` |
| E4 / E9 / E10 | 未打开（`SQLGEN_EXTRA_RULES` 仅进程内为 `E11`） |
| Task37 / Task38 / Task39-L 原有改动 | 保持不变（未触碰） |
| Task46 的 `semantic_contracts.py` / `test_task44_semantic_rules.py` | **未删除、未修改（前者被本任务有意增量修改，见 §2）** |
| commit | **无** |

**PROD_TRACKED_CHANGED = NONE**（5 个 tracked 修改全部是 T37/T38/T44 的既有改动，非本任务产生）。

**PROD_UNTRACKED_MODIFIED**（本任务修改的未跟踪**生产**文件，共 1 个）：

```
backend/app/sqlgen/semantic_contracts.py      ← E11 文本收口（untracked ⇒ git 看不见，用反推重建证明）
```

**NEW_UNTRACKED_FILES（仓库内，非生产代码）**：

```
reports/task48_e11_scope_fix.md               ← 报告副本（项目惯例）
```

**仓库外 harness**：`F:/task48_e11_scope_fix/`（snapshot.py、phase1_verify.py、e11_scope.py、
phase2_fixtures.py、phase3_recompute.py、run_task48.py、phase8_isolation.py + 各 `.json`/`.txt` 产物）。

---

## 十、限制

1. **n=1**：`E-0093` 只采样 1 次。`FIXED` 是**单次抽样观测**，不是「新 wording 稳定修复该类缺陷」的证明。
2. **单臂**：本次仍是 `E11_ON` 单臂，没有 `E11_OFF` 基线 ⇒ 无法排除「模型自身波动恰好写对」。
   §5.1 的机制说明是**文本级对照**（T47 旧 pred vs 本次 pred），不是随机对照实验。
3. **scope 检查器看不见语义**：它只回答「这个列在当前 query block 解析得到吗」，
   不回答「这个列作为破平键是否业务合理」。例如把破平键换成 `region`（字符串）能通过 scope，
   但排序语义可能不合预期。
4. **日期谓词探测器不识别 `LIKE`**：本次 pred 的 `o.order_date LIKE '2025%'` 未被识别为日期谓词
   （`exp.Like` 不在 `(EQ, GT, GTE, LT, LTE, NEQ)` 内），因此 `C_date_missing_in_pred=True`
   这一标签在此题**名不副实**。已实测 `LIKE '2025%'` 与 gold 的年区间命中同一 4013 行 ⇒ 语义等价。
   该标签按设计**不计入** `E11_STRUCTURE_OK`，故不影响判定。
5. **`E-0098` 未重新调用**：其正向控制状态沿用 Task 47 记录 + 本次离线 scope 复算（`scope_ok=True`）。
6. **不计算综合分**：只给逐条判定与计数。

---

## 十一、下一步建议

1. **用同样 25 题、新 wording 跑一次单臂复验**（25 次调用）——这是把
   `E11_OVERALL_STATUS` 从 `NEEDS_FULL_TRIGGER_REVALIDATION` 推进到
   `READY_FOR_100Q` 的**唯一**合法路径。判据：`E11 可归因 scope violation = 0`
   且 `GROUPBY/SELECT/TIMEFILTER = 0/0/0` 且 `E-0098` 仍 PASS。
2. **把 `e11_scope.py` 并入常规离线回归**：它抓的是 T47 结构检查器**结构性看不见**的
   一类缺陷（合法裸列 + 作用域错），两者必须同时跑。
3. **若 25 题复验通过再谈 100Q**（约 200+ 次调用，需单独批预算）。
4. **不建议**把 E11 转为生产默认：本任务未改变任何默认开关，E4/E9/E10/E11 仍全部 OFF。

---

## 十二、固定字段输出

```
TASK48=COMPLETE
NEW_REAL_API_CALLS=1
E0093=FIXED
SCOPE_FIX=CONFIRMED
OFFLINE_SCOPE_TESTS=14/14 PASS
TASK47_REUSED=25 records (0 new calls)
E11_OVERALL_STATUS=NEEDS_FULL_TRIGGER_REVALIDATION
PROD_TRACKED_CHANGED=NONE
PROD_UNTRACKED_MODIFIED=backend/app/sqlgen/semantic_contracts.py
ENV_CHANGED=NO
DB_CHANGED=NO
GOLD_CHANGED=NO
FEWSHOT_CHANGED=NO
```
