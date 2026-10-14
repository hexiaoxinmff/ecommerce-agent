# Task 44：SQLGEN 语义规则定向修复（E-0065 / E-0075 / E-0082 / E-0088 / E-0098）

> 单一目标：让 Task 43 已确证的失败机制在 **SQL 生成层 / SQLGEN_EXTRA_RULES** 上得到
> 明确、可测试、可回归的约束。
> 边界：不改 Provider / 不改 `.env` / 不改 DB / 不改 Gold / 不改 FEWSHOT_V3 /
> 不跑 100Q / 不调用 Mimo / 不新增模型调用 / 不 commit / 不删 T37–T39L 工作树改动。

---

## 一、Phase 1 精确审计（只读，未改代码）

审计脚本：`F:/task44_sqlgen_semantic_rules/phase1_audit.py`（输出 `phase1_audit.txt`）

### A. 现有规则与四个机制的对应关系

| 机制 | 现有规则 | 结论 |
|---|---|---|
| 1. 输出列契约 | **E4 `OUTPUT_CONTRACT_RULES`**（标题「【输出列契约】（重要）」） | **已有** ⇒ 只增强 wording |
| 2. 全平台 / 整体口径 | **无任何规则覆盖** | 新增 **E9** |
| 3. ratio 分子/分母 | 仅 `BUSINESS_RULES` 有一句「占比：分子分母必须同一统计口径与时间窗口」；**没有方向契约** | 新增 **E10** |
| 4. Top-N 确定性排序 | **无任何规则覆盖** | 新增 **E11** |

补充事实：

- `E4~E7` 在 `_EXTRA_RULE_TABLE` 内，是**无条件**规则段（flag 打开即注入每一道题）。
- `E8` 不在表内，由 `entity_constraint_block()` 实现**条件性**注入（Task 38）。
- `enabled_extra_rules()` 是唯一解析点；`SQLGEN_EXTRA_RULES` **不在 `config.py`** 中，
  由 `prompt.py` 直接读环境变量（`os.getenv`）。
- prompt 拼装顺序（`build_prompt`）：
  `question → schema_linking → fewshot → BUSINESS_RULES(V1.3) → extra_rules → entity_block(E8) → CONSTRAINTS → OUTPUT_RULES → 请生成`
- `BUSINESS_RULES` 当前 sha256 前 8 位 = `10583478`，与冻结值一致（审计时未改任何代码）。

### B. E-0088「未定义别名」当前由谁兜底

**由执行层（`app/sqlcheck/scope_validator` + `app/sqlexec/executor`）兜底，不是生成层。**

- `executor.execute()` 的顺序：`check_sql_safety` → `check_sql_scope` → `get_connection()`。
  Scope 校验**早于任何数据库连接建立**（Task 37 已有测试锁定）。
- 命中后抛 `SQLExecutionScopeError`，其继承链刻意是
  `SQLExecutionScopeError → SQLExecutionDatabaseError → SQLExecutionError`，
  **不继承** `SQLExecutionSafetyError` ⇒ 生产图仍会给一次 Repair（安全边界不被隐性缩短）。
- `app/sqlrepair/validator.py` 也在 Repair 输出上复用了同一个 `check_sql_scope`。
- 生成层**没有任何**针对别名的规则段。

**责任层判定**：拦截职责由既有安全层**可靠承担**（Task 44 用重建 SQL 实测复现，
错误信息与 Task 43 运行期记录逐字一致）⇒ **不新增生成层规则**。
理由：① 拦截已可靠且错误信息可操作；② 生成规则无法保证消除该缺陷，只能降低概率；
③ 最小改动原则。**禁止为了通过 E-0088 削弱任何既有安全边界**（本任务未削弱，见 §六 Test E）。

### C. 默认开关状态与副作用风险

- `E4~E8` 与新增 `E9~E11` **全部默认关闭**：未设 `SQLGEN_EXTRA_RULES` 时
  `enabled_extra_rules() == ""`、`entity_constraint_block(q) == ""`、
  `semantic_contract_block(q) == ""` ⇒ Prompt 与冻结基线**逐字节相同**。
- 新增的三个 detector 在 100 题上的触发面（`phase1_candidate_scan.py` 预演 +
  §七 测试锁定）：

| flag | 触发面 | 说明 |
|---|---|---|
| E9 | **1 题**：`E-0065` | 刻意用**合取**判据（时间过滤 ∧ 平台级全局词） |
| E10 | **12 题**（其中 9 题可抽出确定方向） | 含比值/倍数/占比/增速语义 |
| E11 | **25 题** | 排除 5 道标量 Top-1（破平键不影响返回值） |

- 判据刻意窄化的理由（避免误伤）：**E9 不收「全部/所有」**。
  预演显示宽判据会把 `E-0083`「该季度**全部**商品销售金额」也算成全局口径，
  而该题的时间窗是同一句显式绑定的 —— 用它当判据会教模型**丢掉合法的时间过滤**。
  改成平台级词（`全平台/全站/整个平台/平台整体`）后触发面从 2 题收敛到 1 题。

---

## 二、RULES_CHANGED（生产代码改动）

| 文件 | 改动 | 性质 |
|---|---|---|
| `backend/app/sqlgen/semantic_contracts.py` | **新增**（3 个确定性 detector + 3 个不可变契约对象） | 新模块，纯 `re` + `dataclasses`，无 LLM / 无 DB / 无 Schema 依赖 |
| `backend/app/sqlgen/prompt.py` | ① 新增 `E9/E10/E11` 条件性注入函数与 `semantic_contract_block()`；② `build_prompt` 追加 `{semantic_text}` 一行；③ **E4 增强 wording**（新增第 5 条「实体维度契约」+ 第 6 条反例例外）；④ 模块 docstring 更新 | 增强 + 新增 |

`git diff HEAD -- backend/app/sqlgen/prompt.py`：**只有新增行**，唯一被修改的既有内容是
`OUTPUT_CONTRACT_RULES` 字符串（追加第 5/6 条），原有 1~4 条**逐字保留**（测试锁定）。

**没有**改 graph / provider / schema_link / DB / executor / repair / validator /
`.env` / Benchmark / FEWSHOT。

### 各机制的具体修复

1. **E-0065（全平台口径）—— 新增 E9 `GlobalScopeContract`**
   触发：题面**同时**出现时间过滤与平台级全局词（100 题中恰好 E-0065）。
   约束：全局口径作为**参照基准**时不得继承外层年份过滤；参照基准必须写成独立标量子查询；
   并显式给出「与同一时间窗绑定的例外」（保护 E-0083 类题）。
2. **E-0075（ratio 方向）—— 新增 E10 `RatioDirectionContract`**
   触发：题面含比值/倍数/占比/增速语义（12 题）。
   约束：生成 ratio 前必须显式写出 `numerator（被除数）/ denominator（除数）`；
   方向由题面语义决定而非 SQL 中出现顺序；增速类分母固定为**基期**；分母必须 `NULLIF` 保护。
   能从「A 是 B 的几倍 / A 相当于 B 的多少倍 / A 占 B 的比例」稳定抽取时，
   额外给出题面级方向提示（9 题）；抽到指示代词（如「它们各」）时**只给通用契约**，
   宁可不给也不给错（测试锁定）。
3. **E-0082（输出列契约）—— 增强 E4**
   新增第 5 条：当比例/指标针对**需要 JOIN 维度表才能限定**的实体（categories/products/users）时，
   必须同时输出实体标识列与指标列，**禁止用 `SUM(CASE WHEN 维度列='常量' …)` 把维度折叠掉**。
   新增第 6 条**反例例外**：实体由同表列直接限定、且只要求标量比值时不得凭空加列
   —— 这条是为保护 `E-0081`（gold 只有 1 列）而写的，删掉它就会把原本正确的题判错。
4. **E-0098（Top-N 破平）—— 新增 E11 `RankingTiebreakContract`**
   触发：Top-N 集合（显式 N）或「最X的是哪些」（25 题），**排除**标量 Top-1。
   约束：排名/截断时若排序键可能并列，必须追加稳定唯一键；优先业务主键
   （`orders.id/order_items.id/products.id/categories.id/users.id`），否则用业务唯一标识；
   **破平键只出现在 `ORDER BY` 中，不得新增 SELECT 列**；禁止对所有 `ORDER BY` 机械追加。
5. **E-0088（未定义别名）—— 责任层 = 既有安全层，生成层不新增规则**
   见 §一.B。拦截点：`executor.execute()` 在建立 DB 连接**之前**；Repair 侧同源校验。

---

## 三、TESTS_ADDED

新增 `backend/tests/test_task44_semantic_rules.py`（**43 个测试**，全部离线 deterministic）：
不调用任何 LLM / 网络；只做 ① detector 行为断言 ② Prompt 注入断言
③ **真实只读库上的机制复算** ④ gold 原样重放（identity replay）。

| 段 | 内容 |
|---|---|
| §0 | **identity replay**（5 题 × 2 次重放 + 与冻结 `gold_result_hash` 比对） |
| §1 | **Test A** E-0065：detector 触发面 / E-0083 反例 / 机制复算（1236 vs 1246、AVG 3329.7195 vs 3286.1395） |
| §2 | **Test B** E-0075：方向抽取 / 脏 span 抑制 / 机制复算（gold 0.48、pred 2.09） |
| §3 | **Test C** E-0082：E4 wording 逐字保留 + 新条款 / 机制复算（gold 2 列 vs pred 1 列 ⇒ 列数不一致判错）/ **E-0081 反例守卫** |
| §4 | **Test D** E-0098：N 抽取 / 标量 Top-1 排除 / **并列边界客观存在** / **诚实记录（见 §五）** |
| §5 | **Test E** E-0088：重建 SQL 前缀一致 / scope 拒绝 / 拦截早于 DB 连接 / Repair 可用 / 安全边界未被削弱 |
| §6 | 开关契约：默认关闭逐字节不变（100 题）/ 单变量 / E8 行为回归守卫 |
| §7 | 100 题触发面锁定（E9=1、E10=12、E11=25） |
| §8 | artifact 完整性：SQL 不得截断（最小 pred 236 字 / 最小 gold 172 字） |

同时**最小修改**既有测试 `backend/tests/test_sqlgen_prompt_rules.py`：
`test_unknown_flag_ignored` 原用 `"E9"` 当未知 flag，而 E9 在 Task 44 已成为真实 flag
⇒ 改为真正未定义的 `"E999"`，保持用例名与语义一致（否则是「名不副实但侥幸通过」）。

---

## 四、IDENTITY_REPLAY（§六 探针自检）

`backend/tests/test_task44_semantic_rules.py::§0`，5 题全部成立：

| 题 | gold 行数 | 两次重放一致 | 与冻结 `gold_result_hash` 一致 |
|---|---|---|---|
| E-0065 | 1 | ✅ | ✅ |
| E-0075 | 1 | ✅ | ✅ |
| E-0082 | 1 | ✅ | ✅ |
| E-0088 | 5 | ✅ | ✅ |
| E-0098 | 66 | ✅ | ✅ |

⇒ 探针（只读连接 + 归一化 + hash）可信，**后续归因有效**。

---

## 五、诚实记录：E-0098 的破平键假设**未被复现**

任务书给的实验结论是「variant A 结果集 ≠ gold；variant B 补 `, p.id` 后集合 == gold」。
本任务在**冻结 DB 上独立复算**得到的结果与之**不完全一致**，必须如实记录：

| 观测 | 结果 |
|---|---|
| rk3 与 rk4 销量并列的分类 | **3 个**：儿童玩具 105/105、家具 105/105、男装 118/118 ⇒ 并列边界**客观存在** |
| gold 去掉 `prod_id` 破平后 | 仍 66 行、**集合与 gold 相等** |
| `rk_no_tie != rk_tie` 的行数 | **0**（无任何名次位移） |
| Top-3 成员差异行数 | **0** |

⇒ 「无破平键 ⇒ 结果集不同」这一假设在**当前 DB 状态下不可复现**（Task 43 亦记为
「高度可能」而非「已确证」；其诊断文件本身也记录了「去掉破平后结果集仍相等」）。
原因可解释：`GROUP BY c.id, p.id` 的输出顺序恰好与 `p.id` 顺序一致，稳定排序下
`ORDER BY sold DESC` 与 `ORDER BY sold DESC, prod_id` 在本数据上给出相同结果。

**因此 E11 的定位是「防御性确定性约束」，不是「已复现失败的修复」。**
该实测被写成一条**会失败就会报错**的回归断言（`test_D_honest_record_no_observable_difference_without_tiebreak`）：
一旦将来数据变化让差异显性化，该测试会失败并提示重新评估 E11 的定位。

---

## 六、Test E 结论：E-0088 的责任层

- Task 43 记录的 pred SQL 前缀只有 400 字（harness 写盘时 `rec["pred_sql"] = sql[:400]`），
  该前缀**本身无法解析**（`ParseError`）。本任务把它**逐字节保留**，并补全为**可执行完整 SQL**
  （1020 字，`startswith(记录前缀) == True`）。
- 重建 SQL 的 `check_sql_scope` 违规集合 = `{('p','id'), ('p','name')}`，
  `execute()` 抛出 `SQLExecutionScopeError: SQL 引用了未定义的表别名: 未定义的别名 p: p.id, 未定义的别名 p: p.name`
  —— **与 Task 43 运行期记录逐字一致**。
- 拦截发生在 `get_connection()` **之前**（用 monkeypatch 把 `get_connection` 换成会炸的函数仍被拦截）。
- `DROP TABLE orders` / 多语句仍抛 `SQLExecutionSafetyError` ⇒ 安全边界未被削弱。
- ⇒ **结论：不需要生成层修复；责任层 = `sqlcheck/scope_validator`（拦截）+ 生成层漏 JOIN（根因，本任务不改）。**

---

## 七、验证结果

| 项 | 结果 |
|---|---|
| Task 44 targeted（T44 + prompt_rules + T38） | **71 passed / 0 failed** |
| 全 backend pytest（`backend/tests`） | **694 passed / 0 failed**（不含 T44 文件时为 651 ⇒ T44 净增 43） |
| identity replay | 5/5 成立 |
| 生产文件变更（tracked） | **2**：`backend/app/sqlgen/prompt.py`、`backend/tests/test_sqlgen_prompt_rules.py` |
| 生产代码新增（untracked） | **1**：`backend/app/sqlgen/semantic_contracts.py` |
| DB 变更 | **无**（`65e5d8b2727c…` 前后一致） |
| `.env` 变更 | **无**（`dce981d984dd…` 前后一致） |
| Benchmark Gold 变更 | **无**（`dba277cc0be7…` 前后一致） |
| FEWSHOT 变更 | **无**（`ee12fcc994c6…` 前后一致） |
| commit | **无** |

变更边界证明：`F:/task44_sqlgen_semantic_rules/boundary_proof.txt`
（824 个 tracked 文件逐文件 sha256 前后快照，只有 2 个变化，且都在白名单内）。

SQL artifact：`F:/task44_sqlgen_semantic_rules/task44_evidence.json`
（5 题的 `gold_sql_full` / `pred_sql_full` **完整保存**，最小长度 172 / 236 字，无截断）。

---

## 八、已知副作用风险

1. **E9（低）**：触发面 1 题，判据是「时间过滤 ∧ 平台级全局词」。剩余风险是题面用
   「全平台」但同时想限定时间（如「2025 年全平台销售额」）—— 这类表述不含 4 位年份之外的
   时间过滤时不会触发；若同时出现，prompt 里已写明**与同一时间窗绑定时必须保留过滤**。
2. **E10（低）**：触发面 12 题。风险是把原本正确的方向「改错」。缓解：只在题面有比值语义时注入；
   抽取不干净时不给出题面级方向；并给出「结果 < 1 时复查方向」的自检。
   增速题统一按「分母 = 基期」表述，与 gold（E-0094 同比、E-0096 环比）一致。
3. **E11（中低，但**收益未证实**）**：触发面 25 题。风险是模型把破平键写进 `SELECT`
   ⇒ 列数契约破坏（prompt 已显式禁止）。真实风险在另一侧：**该规则目前没有已复现的收益**
   （§五），打开它是在用「潜在确定性」换「Prompt 变更面」。
4. **E4 增强（低）**：风险是模型在「同表列限定的标量比值」题上多输出一列
   （E-0081 会因此判错）。已用第 6 条反例例外 + 测试守卫显式覆盖。
5. **E4~E11 默认关闭**：本任务**未改变生产默认行为**，是否转正需人工决策。
   转正建议：E9/E10 风险低、靶题明确，可优先；E11 建议先补一个「破平键确实改变结果」的
   数据集或题面证据再转正。
