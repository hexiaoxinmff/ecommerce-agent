# Task 45：SQLGEN Semantic Contract 定向真实验证（E4 / E9 / E10 / E11）

> 单一目标：验证 Task 44 新增 / 增强的 **E4 / E9 / E10 / E11** 在**真实 Bailian 生成链路**
> 中的实际行为，并按预注册的因果归因纪律给出可复核的判定。
>
> 边界（全部遵守）：默认 Provider 保持 `mimo`（仅进程内临时 `LLM_PROVIDER=bailian`，**不写 `.env`**）/
> 不改 DB / Gold / FEWSHOT / 不 commit / 不调用 Mimo / 不跑 100Q /
> **单题单臂最多 1 次真实 LLM 调用、总调用 ≤ 20** / 不输出 API Key / 不计算人为总分。

---

## 一、实验设计

- Provider：`bailian`（类 `BailianProvider`，模型 `qwen3.7-flash-2026-07-15`）
- 生成口径：**单次调用变体**（继承 Task 43）——Schema Linking 用「全量 Schema 注入」这一
  **确定性**步骤替代（无 LLM），随后**恰好 1 次** `provider.generate()`，再离线走
  安全校验 → Scope 校验 → 只读执行 → 结果等价判定。
- ⚠️ 本 harness 的管线与**完整生产图（每题 ≥2 次 LLM：schema_link + sql_generate，Repair 题 3 次）
  不等价**；结论只适用于「生成层规则 + 单次生成」这一场景。
- 实验臂（**禁止多规则同开**）：

| 臂 | `SQLGEN_EXTRA_RULES` | 题目数 |
|---|---|---|
| OFF | `None` | 4 |
| E4_ON | `E4` | 2 |
| E9_ON | `E9` | 4 |
| E10_ON | `E10` | 4 |
| E11_ON | `E11` | 3 |
| OFF | `None` | 3 |

- 判定逻辑与机制判据在**运行前**即写入 harness（`run_task45.py`），合并阶段（`merge_and_report.py`）
  **逐字复用**同一份 `judge()` / `MECHANISM`，并断言主运行 verdict 可复现。

### 1.1 防自欺的三道硬检查

| 检查 | 结果 |
|---|---|
| 每条记录的 prompt hash 与**确定性重算**一致 | **20/20** |
| 主运行 13 组 verdict 可用「主运行当时可见的 OFF」精确复现 | **13/13** |
| Identity Replay Gate（先于任何对照） | **13/13 PASS** |

第 1 条的意义：`build_prompt` 的输出被逐字节重算并比对，因此「规则是否真的注入了 Prompt」
是**可证明的事实**，而不是靠 harness 自述的 `rule_blocks` 字段。第 2 条的意义：合并阶段
**没有**悄悄改变任何结论。

## 二、样本（13 题）

| 分组 | 题号 |
|---|---|
| Task 43 确证失败机制（CORE） | E-0065 / E-0075 / E-0082 / E-0098 |
| 负例（不应被误触发） | E-0083 / E-0076 / E-0081 |
| 普通 Top-N | E-0074 / E-0042 |
| 普通 ratio | E-0064 / E-0089 |
| 日期区间 | E-0053 / E-0073 |

### 2.1 规则实际注入情况（确定性口径）

| 臂 | 注入 | 未注入 | 未注入的题 |
|---|---|---|---|
| E4_ON | 2 | 0 | — |
| E9_ON | 1 | 3 | E-0083, E-0053, E-0073 |
| E10_ON | 4 | 0 | — |
| E11_ON | 3 | 0 | — |

**E9 的 3 个未注入题（E-0083 / E-0053 / E-0073）是 detector 的正确行为**（条件性注入：
detector 未命中 ⇒ 返回 `None` ⇒ Prompt 与 OFF **逐字节相同**）。这同时说明 E9 的触发面
确实是「合取判据」而不是「看到全平台就触发」。

## 三、Identity Replay Gate（先于任何对照）

对 13 题分别把 `gold_sql` **重放两次**并与冻结的 `gold_result_hash` 比对：

| 题号 | replay_deterministic | replay_equals_frozen | pass |
|---|---|---|---|
| E-0042 | True | True | True |
| E-0053 | True | True | True |
| E-0064 | True | True | True |
| E-0065 | True | True | True |
| E-0073 | True | True | True |
| E-0074 | True | True | True |
| E-0075 | True | True | True |
| E-0076 | True | True | True |
| E-0081 | True | True | True |
| E-0082 | True | True | True |
| E-0083 | True | True | True |
| E-0089 | True | True | True |
| E-0098 | True | True | True |

**13/13 PASS** ⇒ `PROBE_INVALID` 数 = **0**，探针自身可用，可以进入归因。

## 四、E4（输出列契约增强）OFF vs ON

`SQLGEN_EXTRA_RULES=E4` 实际注入到 Prompt 的文本（由 `build_prompt` 确定性重算、
与 OFF 逐行 diff 得到；同一规则对**所有命中题**注入同一段文本，仅方向 / N 值等插值不同）：

**代表题 E-0082**：休闲零食类别在全部非取消订单明细中的销售金额占全平台商品销售总额的比例是多少？（百分比，保留两位小数）

```diff
+【输出列契约】（重要）
+1. 生成 SQL 前先枚举问题要求返回的所有信息，SELECT 的每一列都必须对应用户问题中要求给的一项字段；
+2. 数量占比/比例题：若问题要求「给出分类与占比」，必须同时输出「分类名称」与「占比」两列；
+3. 结构统计题若问题注明「含取消订单的结构统计 / 总订单数」，必须额外输出总计数列（如 COUNT(*) AS total_cnt）；
+4. SELECT 列数必须与问题要求完全匹配，禁止遗漏列（列数缺失会导致结果无法对齐判错）。
+5. 实体维度契约：当题目要求的比例/指标针对某个**需要 JOIN 维度表才能限定**的实体时（如「某类别」的名称来自 categories、「某商品」来自 products、「某用户」来自 users），SELECT 必须同时输出该实体的标识列（名称或 ID）与指标列；不得用 SUM(CASE WHEN 维度列 = '常量' THEN …) 把维度折叠掉、只返回一个标量；
+6. 第 5 条的反例（不适用）：实体由**同一张表的列**直接限定、且题目只要求一个标量比值时（如 users.region = '广东' 的占比），不要凭空增加实体列 —— 多输出一列同样会判错。
+
+
```

下表为逐题对照（SQL **完整保存**，未截断）。

### 四.E-0082　`NO_OBSERVED_EFFECT`

**题面**：休闲零食类别在全部非取消订单明细中的销售金额占全平台商品销售总额的比例是多少？（百分比，保留两位小数）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**False**；ON 正确：**False**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MISMATCH | `['ratio']` | 1 | `27221d84e979` | 2381 ms |
| OFF | EXEC_MISMATCH | `['ratio']` | 1 | `27221d84e979` | 2824 ms |

- **GOLD**：`SELECT c.name, ROUND(SUM(oi.subtotal) * 100.0 / (SELECT SUM(oi2.subtotal) FROM order_items oi2 JOIN orders o2 ON o2.id = oi2.order_id WHERE o2.status != 'cancelled'), 2) AS pct FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' AND c.name = '休闲零食' GROUP BY c.id, c.name`
- **OFF SQL**：      `SELECT ROUND(100.0 * SUM(CASE WHEN c.name = '休闲零食' THEN oi.subtotal ELSE 0 END) / SUM(oi.subtotal), 2) AS ratio FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled'`
- **ON SQL**：      `SELECT ROUND(100.0 * SUM(CASE WHEN c.name = '休闲零食' THEN oi.subtotal ELSE 0 END) / SUM(oi.subtotal), 2) AS ratio FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled'`

> **归因注记**：规则已注入，但 ON/OFF 产出的 SQL 与结果完全一致（同 hash 27221d84e979）⇒ 规则未产生任何可观测变化。两臂均 EX✗（gold=2 列 / pred=1 列），即 E4 未能修复其目标失败模式（列契约）。

### 四.E-0081　`RULE_TRIGGERED`

**题面**：广东省的用户占全部用户的比例是多少？（百分比，保留两位小数）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**False**；归因质量：`NO_OFF_RULE_INJECTED_EFFECT_INDETERMINATE`
- 机制改变（预注册判据）：**True**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['percentage']` | 1 | `4b6a662fcc6d` | 2224 ms |
| OFF | (未运行) | — | — | — | — |

- **GOLD**：`SELECT ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM users), 2) AS pct FROM users WHERE region = '广东'`
- **OFF SQL**：      `(未运行)`
- **ON SQL**：      `SELECT ROUND(CAST(SUM(CASE WHEN region = '广东' THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(*), 2) AS percentage FROM users`

> **归因注记**：⚠️ 无 OFF 基线，且预注册 mechanism 判据 `_cols(on) != _cols(off)` 在 off={} 时**退化为恒 True** ⇒ RULE_TRIGGERED 不成立，应记为「不可判定」。ON 与 gold 一致（EX✓）只说明当前生成正确，不能归因于 E4。

## 五、E9（全局口径 / 时间过滤）OFF vs ON

`SQLGEN_EXTRA_RULES=E9` 实际注入到 Prompt 的文本（由 `build_prompt` 确定性重算、
与 OFF 逐行 diff 得到；同一规则对**所有命中题**注入同一段文本，仅方向 / N 值等插值不同）：

**代表题 E-0065**：2026年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？

```diff
+【全局口径 / 参照基准约束】（本题同时出现时间过滤与「全平台」类全局口径，请注意）
+- 本题的时间过滤表达：2026年
+- 本题的全局口径表达：全平台
+- 「全平台 / 全站 / 平台整体」描述的是一个**不受本题时间窗限制**的整体口径；
+  当它作为**参照基准**出现时（如「高于全平台平均实付金额」中的平均值），
+  该参照基准的聚合**不得继承**外层的年份 / 季度 / 半年过滤条件，否则阈值会被抬高、命中数会偏少；
+- 正确写法：把参照基准写成独立的标量子查询，子查询内只保留题面为该基准显式声明的过滤条件（如「非取消订单」），不要复制外层的日期条件；
+- 反例（不要这样做）：外层 `WHERE order_date >= '2026-01-01'` 时，内层 `SELECT AVG(total_amount) FROM orders WHERE order_date >= '2026-01-01'`；
+- 例外：若题面把全局口径**与同一时间窗绑定**（如「该季度全部商品销售金额」「2025 年全平台销售额」），则该基准**必须**保留该时间窗，不得去掉过滤。
+- 只有本题被识别为「全局口径」时才适用本段；其他题目不要无理由去掉时间过滤。
+
```

下表为逐题对照（SQL **完整保存**，未截断）。

### 五.E-0065　`FIXED`

**题面**：2026年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**True**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['order_count']` | 1 | `ce05666e665c` | 2510 ms |
| OFF | EXEC_MISMATCH | `['order_count']` | 1 | `6d8ed7dd9de3` | 3403 ms |

- **GOLD**：`SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`
- **OFF SQL**：      `SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled')`
- **ON SQL**：      `SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`

> **归因注记**：四条件齐备：OFF 内层继承了全局时间过滤 strftime('%Y',order_date)='2026'（结构判据 True）⇒ 结果 1246；ON 去掉内层过滤（False）⇒ 1236 = gold。FIXED 成立（n=1，机制层有结构证据支撑）。

### 五.E-0083　`NO_OBSERVED_EFFECT`

**题面**：2025年第四季度中，家用电器类目销售金额占该季度全部商品销售金额的比例是多少？（百分比，保留两位小数）

- 规则注入（确定性）：**False**（harness 自述：False）；OFF 基线可用：**False**；归因质量：`NO_OFF_RULE_NOT_INJECTED_CAUSALLY_EQUIVALENT_TO_OFF`
- 机制改变（预注册判据）：**False**；ON 正确：**False**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MISMATCH | `['percentage']` | 1 | `bd801fbdf68d` | 3152 ms |
| OFF | (未运行) | — | — | — | — |

- **GOLD**：`SELECT c.name, ROUND(SUM(oi.subtotal) * 100.0 / (SELECT SUM(oi3.subtotal) FROM order_items oi3 JOIN orders o3 ON o3.id = oi3.order_id WHERE o3.order_date >= '2025-10-01' AND o3.order_date <= '2025-12-31' AND o3.status != 'cancelled'), 2) AS pct FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.order_date >= '2025-10-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' AND c.name = '家用电器' GROUP BY c.id, c.name`
- **OFF SQL**：      `(未运行)`
- **ON SQL**：      `SELECT ROUND(100.0 * SUM(CASE WHEN c.name = '家用电器' THEN oi.subtotal ELSE 0 END) / SUM(oi.subtotal), 2) AS percentage FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 7) = '2025-10'`

> **归因注记**：无 OFF 基线，但规则**未注入**（prompt 与 OFF 逐字节相同）⇒ 该臂在因果上等价于 OFF，NO_OBSERVED_EFFECT 成立。ON 为 EX✗ 属采样噪声，与规则无关。

### 五.E-0053　`NO_OBSERVED_EFFECT`

**题面**：2026年7月至8月，订单数量最高的5个收货地区是哪些？（请给出地区名称与订单数量）

- 规则注入（确定性）：**False**（harness 自述：False）；OFF 基线可用：**False**；归因质量：`NO_OFF_RULE_NOT_INJECTED_CAUSALLY_EQUIVALENT_TO_OFF`
- 机制改变（预注册判据）：**False**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['region', 'order_count']` | 5 | `62135bdb083a` | 2291 ms |
| OFF | (未运行) | — | — | — | — |

- **GOLD**：`SELECT region, COUNT(*) AS order_count FROM orders WHERE order_date >= '2026-07-01' AND order_date <= '2026-08-31' GROUP BY region ORDER BY order_count DESC, region LIMIT 5`
- **OFF SQL**：      `(未运行)`
- **ON SQL**：      `SELECT region, COUNT(id) AS order_count FROM orders WHERE substr(order_date, 1, 7) IN ('2026-07', '2026-08') GROUP BY region ORDER BY order_count DESC LIMIT 5`

> **归因注记**：无 OFF 基线，但规则未注入（prompt 与 OFF 逐字节相同）⇒ 因果上等价于 OFF，NO_OBSERVED_EFFECT 成立（负例未误触发）。

### 五.E-0073　`NO_OBSERVED_EFFECT`

**题面**：最近90天（2026年6月14日至9月12日）内，日均销售额最高的5个商品分类是哪些？（请给出分类名称与日均销售额）

- 规则注入（确定性）：**False**（harness 自述：False）；OFF 基线可用：**False**；归因质量：`NO_OFF_RULE_NOT_INJECTED_CAUSALLY_EQUIVALENT_TO_OFF`
- 机制改变（预注册判据）：**False**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['category_name', 'daily_avg_sales']` | 5 | `45ef6cf335e0` | 3516 ms |
| OFF | (未运行) | — | — | — | — |

- **GOLD**：`SELECT c.name, ROUND(SUM(oi.subtotal) * 1.0 / COUNT(DISTINCT o.order_date), 2) AS daily_avg_revenue FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-06-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY c.id, c.name ORDER BY daily_avg_revenue DESC, c.name LIMIT 5`
- **OFF SQL**：      `(未运行)`
- **ON SQL**：      `SELECT c.name AS category_name, ROUND(SUM(oi.subtotal) * 1.0 / COUNT(DISTINCT o.order_date), 2) AS daily_avg_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-06-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY c.id ORDER BY daily_avg_sales DESC LIMIT 5`

> **归因注记**：无 OFF 基线，但规则未注入（prompt 与 OFF 逐字节相同）⇒ 因果上等价于 OFF，NO_OBSERVED_EFFECT 成立（负例未误触发）。

## 六、E10（比值方向契约）OFF vs ON

`SQLGEN_EXTRA_RULES=E10` 实际注入到 Prompt 的文本（由 `build_prompt` 确定性重算、
与 OFF 逐行 diff 得到；同一规则对**所有命中题**注入同一段文本，仅方向 / N 值等插值不同）：

**代表题 E-0075**：2026年下半年的订单数量是上半年订单数量的几倍？（保留两位小数）

```diff
+【比值方向契约】（本题要求计算比值 / 倍数 / 占比 / 增速，请先确定方向再写 SQL）
+- 生成 ratio 前必须先显式写出两件事：numerator（被除数 / 分子）= ？ denominator（除数 / 分母）= ？
+- 本题题面识别到的方向：numerator（被除数）= 「2026年下半年的订单数量」，denominator（除数）= 「上半年订单数量」
+  依据：题面片段「2026年下半年的订单数量是上半年订单数量的几倍」；「A 是 B 的几倍」⇒ numerator = A，denominator = B
+- 方向由**题面语义**决定，不得由两个数字在 SQL 中出现的先后顺序决定：
+  「A 是 B 的几倍」⇒ A / B；「A 相当于 B 的多少倍」⇒ A / B；「A 占 B 的比例」⇒ A / B；
+  「A 比 B 增长 / 同比 / 环比」⇒ (A − B) / B（分母是**基期**，不是本期）；
+- 写完 SQL 后自检一次方向：若题面说「下半年是上半年的几倍」，而结果 < 1，必须复查分子分母是否颠倒；
+- 分母必须做除零保护（NULLIF(x, 0)）。
+
```

下表为逐题对照（SQL **完整保存**，未截断）。

### 六.E-0075　`REGRESSION`

**题面**：2026年下半年的订单数量是上半年订单数量的几倍？（保留两位小数）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**True**；ON 正确：**False**；OFF 正确：**True**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MISMATCH | `['ratio']` | 1 | `9a0579d60bc4` | 3327 ms |
| OFF | EXEC_MATCH | `['ratio']` | 1 | `4d97c94095ae` | 3846 ms |

- **GOLD**：`SELECT ROUND((SELECT COUNT(*) FROM orders WHERE order_date >= '2026-07-01') * 1.0 / (SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01' AND order_date <= '2026-06-30'), 2) AS h2_to_h1_ratio`
- **OFF SQL**：      `SELECT ROUND(CASE WHEN SUM(CASE WHEN substr(order_date,1,4) = '2026' AND CAST(substr(order_date,6,2) AS INTEGER) BETWEEN 1 AND 6 THEN 1 ELSE 0 END) + 0.0001 THEN SUM(CASE WHEN substr(order_date,1,4) = '2026' AND CAST(substr(order_date,6,2) AS INTEGER) BETWEEN 7 AND 12 THEN 1 ELSE 0 END) * 1.0 / (SUM(CASE WHEN substr(order_date,1,4) = '2026' AND CAST(substr(order_date,6,2) AS INTEGER) BETWEEN 1 AND 6 THEN 1 ELSE 0 END)) ELSE 0 END, 2) AS ratio FROM orders WHERE substr(order_date,1,4) = '2026'`
- **ON SQL**：      `SELECT ROUND(CASE WHEN SUM(CASE WHEN substr(o.order_date,1,4) = '2026' AND CAST(substr(o.order_date,6,2) AS INTEGER) BETWEEN 7 AND 12 THEN 1 ELSE 0 END) * 1.0 / NULLIF(SUM(CASE WHEN substr(o.order_date,1,4) = '2026' AND CAST(substr(o.order_date,6,2) AS INTEGER) BETWEEN 1 AND 6 THEN 1 ELSE 0 END), 0) THEN 0 ELSE 1 END, 2) AS ratio FROM orders o WHERE substr(o.order_date,1,4) = '2026'`

> **归因注记**：⚠️ 方向抽取是**正确**的（numerator=下半年 / denominator=上半年），但 ON 的 SQL 被写成退化的 `CASE WHEN ratio THEN 0 ELSE 1 END` ⇒ 生成质量失败，不是方向错误。差异可归因于「prompt 变化」，但**无法**归因到规则任何一条具体子句；n=1 亦不能排除采样噪声。

### 六.E-0076　`NO_OBSERVED_EFFECT`

**题面**：订单数量最多的5个收货地区是哪几个？它们各占订单总量的百分之几？（请给出地区、订单数与占比）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**False**；归因质量：`NO_OFF_RULE_INJECTED_EFFECT_INDETERMINATE`
- 机制改变（预注册判据）：**False**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['region', 'order_count', 'pct']` | 5 | `afee0c55d9c5` | 2483 ms |
| OFF | (未运行) | — | — | — | — |

- **GOLD**：`SELECT region, COUNT(*) AS order_count, ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM orders), 2) AS pct FROM orders GROUP BY region ORDER BY order_count DESC, region LIMIT 5`
- **OFF SQL**：      `(未运行)`
- **ON SQL**：      `WITH region_stats AS (SELECT region, COUNT(*) AS order_count FROM orders GROUP BY region), total_orders AS (SELECT SUM(order_count) AS total FROM region_stats) SELECT rs.region, rs.order_count, ROUND(rs.order_count * 100.0 / NULLIF(t.total, 0), 2) AS pct FROM region_stats rs CROSS JOIN total_orders t ORDER BY rs.order_count DESC LIMIT 5`

> **归因注记**：无 OFF 基线，规则已注入 ⇒ 无法判断 OFF 是否同样正确，NO_OBSERVED_EFFECT 属**弱结论**。ON 结果与 gold 一致（EX✓）。

### 六.E-0064　`REGRESSION`

**题面**：2025年各订单状态的订单数及其占2025年总订单数的比例是多少？

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**False**；ON 正确：**False**；OFF 正确：**True**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MISMATCH | `['status', 'order_count', 'proportion']` | 5 | `b782afbf1f93` | 3102 ms |
| OFF | EXEC_MATCH | `['status', 'order_count', 'proportion']` | 5 | `4a3a85d5bd2f` | 2859 ms |

- **GOLD**：`SELECT status, COUNT(*) AS order_count, ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM orders WHERE order_date >= '2025-01-01' AND order_date <= '2025-12-31'), 2) AS pct FROM orders WHERE order_date >= '2025-01-01' AND order_date <= '2025-12-31' GROUP BY status ORDER BY order_count DESC`
- **OFF SQL**：      `WITH total_orders AS (SELECT COUNT(*) AS total_count FROM orders WHERE substr(order_date, 1, 4) = '2025') SELECT o.status, COUNT(o.id) AS order_count, ROUND(COUNT(o.id) * 100.0 / total_orders.total_count, 2) AS proportion FROM orders o CROSS JOIN total_orders WHERE substr(o.order_date, 1, 4) = '2025' GROUP BY o.status`
- **ON SQL**：      `WITH status_counts AS (SELECT o.status, COUNT(o.id) AS cnt FROM orders o WHERE substr(o.order_date, 1, 4) = '2025' GROUP BY o.status), total_count AS (SELECT SUM(cnt) AS total FROM status_counts) SELECT s.status, s.cnt AS order_count, ROUND(s.cnt * 1.0 / NULLIF(t.total, 0), 4) AS proportion FROM status_counts s CROSS JOIN total_count t ORDER BY s.status`

> **归因注记**：⚠️ 规则字面子句「A 占 B 的比例 ⇒ A / B」与 benchmark 隐含的「比例 = 百分比数值（×100）」口径冲突：gold 用 `* 100.0`，而题面只说「比例」。ON SQL 使用了规则要求的 `NULLIF(x,0)`（OFF 未用）⇒ 规则被遵循，存在**可追溯的文本机制**；但仍不能排除 n=1 的采样噪声。

### 六.E-0089　`NO_OBSERVED_EFFECT`

**题面**：销售金额高于全部分类平均销售金额的叶子分类有哪些，并给出它们占全平台总销售金额的比例？（请给出分类名、销售额与占比百分比）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**False**；归因质量：`NO_OFF_RULE_INJECTED_EFFECT_INDETERMINATE`
- 机制改变（预注册判据）：**False**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['category_name', 'sales_amount', 'percentage']` | 5 | `97521bad4dc6` | 4154 ms |
| OFF | (未运行) | — | — | — | — |

- **GOLD**：`WITH cat_sales AS (SELECT c.name, SUM(oi.subtotal) AS sales FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY c.id, c.name) SELECT name, ROUND(sales, 2) AS revenue, ROUND(sales * 100.0 / (SELECT SUM(sales) FROM cat_sales), 2) AS pct FROM cat_sales WHERE sales > (SELECT AVG(sales) FROM (SELECT sales FROM cat_sales)) ORDER BY revenue DESC`
- **OFF SQL**：      `(未运行)`
- **ON SQL**：      `WITH category_sales AS (SELECT c.id AS category_id, c.name AS category_name, SUM(oi.subtotal) AS total_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id), total_platform_sales AS (SELECT SUM(total_sales) AS grand_total FROM category_sales), avg_category_sales AS (SELECT AVG(total_sales) AS avg_sales FROM category_sales) SELECT cs.category_name, ROUND(cs.total_sales, 2) AS sales_amount, ROUND((cs.total_sales * 100.0 / tps.grand_total), 2) AS percentage FROM category_sales cs CROSS JOIN total_platform_sales tps CROSS JOIN avg_category_sales acs WHERE cs.total_sales > acs.avg_sales ORDER BY cs.total_sales DESC`

> **归因注记**：无 OFF 基线，规则已注入 ⇒ NO_OBSERVED_EFFECT 属**弱结论**。ON 结果与 gold 一致（EX✓）；本题题面明说「占比百分比」，与 gold 的 ×100 口径一致，未出现 E-0064 那种口径冲突。

## 七、E11（Top-N 确定性破平键）OFF vs ON

`SQLGEN_EXTRA_RULES=E11` 实际注入到 Prompt 的文本（由 `build_prompt` 确定性重算、
与 OFF 逐行 diff 得到；同一规则对**所有命中题**注入同一段文本，仅方向 / N 值等插值不同）：

**代表题 E-0098**：每个商品分类中，销量最高的3款商品分别是哪些？（请给出分类、商品名与销量；仅统计销量超过50的商品）

```diff
+【Top-N 确定性排序契约】（本题是 Top-N / 排名题，请注意并列风险）
+- 识别到的排名表述：「最高的3款」
+- 本题的 Top-N 规模：N = 3
+- 排名 / 截断（ORDER BY … LIMIT n、ROW_NUMBER()/RANK()/DENSE_RANK() … <= n、前 N 名）时，若**排序键可能并列**（尤其按 SUM / COUNT / AVG 等聚合指标排序），必须追加**稳定唯一键**作为最终排序键；
+- 破平键优先使用业务主键：orders.id / order_items.id / products.id / categories.id / users.id；若无可用主键，则使用业务唯一标识（商品名 / 地区名 / 月份）；
+- 破平键**只出现在 ORDER BY（或窗口函数的 ORDER BY）中，不得新增 SELECT 列** —— 多输出一列会破坏结果列契约；
+- 不要给所有 ORDER BY 机械追加主键：仅当本题确实是「排名 / Top-N / LIMIT / 名次过滤」且排序键存在并列可能时才追加。
+- 原因：排序键并列时，不追加破平键会让「谁进入 Top-N」变得不确定，同一 SQL 在不同执行计划下可能选中不同实体。
+
```

下表为逐题对照（SQL **完整保存**，未截断）。

### 七.E-0098　`NO_OBSERVED_EFFECT`

**题面**：每个商品分类中，销量最高的3款商品分别是哪些？（请给出分类、商品名与销量；仅统计销量超过50的商品）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**False**；ON 正确：**True**；OFF 正确：**False**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MATCH | `['category_name', 'product_name', 'total_sold']` | 66 | `1e1333436482` | 3945 ms |
| OFF | EXEC_MISMATCH | `['category_name', 'product_name', 'total_sold']` | 66 | `e1fa20d7365f` | 3844 ms |

- **GOLD**：`WITH cat_prod AS (SELECT c.name AS cat_name, p.name AS prod_name, p.id AS prod_id, SUM(oi.quantity) AS sold FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id, p.name HAVING SUM(oi.quantity) > 50), ranked AS (SELECT cat_name, prod_name, sold, ROW_NUMBER() OVER (PARTITION BY cat_name ORDER BY sold DESC, prod_id) AS rk FROM cat_prod) SELECT cat_name, prod_name, sold AS sold_qty FROM ranked WHERE rk <= 3 ORDER BY cat_name, rk`
- **OFF SQL**：      `WITH RankedProducts AS (SELECT c.name AS category_name, p.name AS product_name, SUM(oi.quantity) AS total_sold, ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY SUM(oi.quantity) DESC) as rn FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id HAVING SUM(oi.quantity) > 50) SELECT category_name, product_name, total_sold FROM RankedProducts WHERE rn <= 3 ORDER BY category_name, rn`
- **ON SQL**：      `WITH cat_product_sales AS (SELECT c.name AS category_name, p.name AS product_name, SUM(oi.quantity) AS total_sold, ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY SUM(oi.quantity) DESC, p.id ASC) AS rn FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id HAVING total_sold > 50) SELECT category_name, product_name, total_sold FROM cat_product_sales WHERE rn <= 3 ORDER BY category_name, rn`

> **补充判定（POST_HOC_NOT_PREREGISTERED）**：`FIXED` —— 结构判据改为 window_has_secondary_key False→True；OFF EX✗ → ON EX✓；离线二分复算（OFF 加/不加 p.id 破平键）证明差异仅由破平键造成

> **归因注记**：⚠️ 预注册 mechanism 判据 keyed on `any_order_has_secondary_key`（两臂皆 True）⇒ **漏检**了真实变化 `window_has_secondary_key` False→True。原始证据支持 FIXED：OFF 无破平键 ⇒ EX✗；ON 加 `p.id ASC` ⇒ EX✓；离线二分复算证明差异**仅**由破平键造成。预注册判定 NO_OBSERVED_EFFECT 属判据漏检，见 supplementary_verdict（事后定义，不替代预注册判定）。

### 七.E-0074　`REGRESSION`

**题面**：2025年第四季度中，销量最高的3个商品分类是哪些？（请给出分类名称与销量）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**False**；ON 正确：**False**；OFF 正确：**True**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MISMATCH | `['category_name', 'total_sold']` | 3 | `b6c9fee0ebbe` | 3055 ms |
| OFF | EXEC_MATCH | `['category_name', 'total_sold']` | 3 | `f8cebf983cc9` | 3536 ms |

- **GOLD**：`SELECT c.name, SUM(oi.quantity) AS sold FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2025-10-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' GROUP BY c.id, c.name ORDER BY sold DESC, c.name LIMIT 3`
- **OFF SQL**：      `SELECT c.name AS category_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND o.order_date >= '2025-10-01' AND o.order_date < '2026-01-01' GROUP BY c.id ORDER BY total_sold DESC LIMIT 3`
- **ON SQL**：      `SELECT c.name AS category_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 7) = '2025-10' GROUP BY c.id ORDER BY total_sold DESC, c.id LIMIT 3`

> **归因注记**：⚠️ ON 的时间过滤被改写为 `substr(o.order_date,1,7)='2025-10'`（仅 10 月，Q4 语义丢失），与 E11 破平键契约无语义关联 ⇒ 最可能为采样波动。破平键本身（`c.id`）加入正确且无害。prompt 确实不同，不能完全排除。

### 七.E-0042　`REGRESSION`

**题面**：非取消订单实付销售额最高的10个收货地区是哪些？（请给出地区名称与销售额）

- 规则注入（确定性）：**True**（harness 自述：True）；OFF 基线可用：**True**；归因质量：`OFF_AVAILABLE`
- 机制改变（预注册判据）：**False**；ON 正确：**False**；OFF 正确：**True**

| | 结果 | 列 | 行数 | 结果 hash | 延迟 |
|---|---|---|---|---|---|
| ON | EXEC_MISMATCH | `['region_name', 'total_sales']` | 10 | `4f303d058313` | 2622 ms |
| OFF | EXEC_MATCH | `['region', 'total_sales']` | 10 | `9f120577d3ed` | 2080 ms |

- **GOLD**：`SELECT region, ROUND(SUM(total_amount), 2) AS revenue FROM orders WHERE status != 'cancelled' GROUP BY region ORDER BY revenue DESC LIMIT 10`
- **OFF SQL**：      `SELECT o.region, ROUND(SUM(o.total_amount), 2) AS total_sales FROM orders o WHERE o.status != 'cancelled' GROUP BY o.region ORDER BY total_sales DESC LIMIT 10`
- **ON SQL**：      `SELECT o.region AS region_name, ROUND(SUM(o.total_amount), 2) AS total_sales FROM orders o WHERE o.status != 'cancelled' GROUP BY o.id, o.region ORDER BY total_sales DESC, o.region ASC LIMIT 10`

> **归因注记**：⚠️ ON 把 `o.id` 加入 **GROUP BY**（`orders.id` 正是 E11 契约首推的破平键）⇒ 聚合粒度被破坏，属**可追溯的规则过度套用**（规则只允许破平键出现在 ORDER BY）。列别名改为 region_name 与规则无关。

## 八、负例专项（E-0083 / E-0076 / E-0081）

| 题号 | 臂 | 规则是否注入 | 结果 | 判定 | 可靠 |
|---|---|---|---|---|---|
| E-0083 | E9_ON | False | EX✗ | `NO_OBSERVED_EFFECT` | True |
| E-0076 | E10_ON | True | EX✓ | `NO_OBSERVED_EFFECT` | False |
| E-0081 | E4_ON | True | EX✓ | `RULE_TRIGGERED` | False |

- **E-0083**（E9 负例）：detector **未命中** ⇒ Prompt 与 OFF 逐字节相同。ON 为 EX✗ 属**采样噪声**，
  与规则无关（若把这条差异记成「规则副作用」，就是把噪声当信号）。
- **E-0076**（E10 负例）：规则**已注入**，但**没有 OFF 基线** ⇒ 只能证明「ON 正确」，
  无法证明「规则导致了正确」。判定 `NO_OBSERVED_EFFECT` 属**弱结论**。
- **E-0081**（E4 负例）：规则已注入、无 OFF 基线，且预注册机制判据 `_cols(on) != _cols(off)`
  在 `off={}` 时**退化为恒 True** ⇒ `RULE_TRIGGERED` 不成立，标为**不可靠**。

> ⚠️ **方法论缺陷（已暴露，未掩饰）**：`judge()` 在 `off is None` 分支下仍会读取 `mechanism_changed`，
> 而机制判据在缺少 OFF 时只能与空 dict 比较。13 组对照中有 **6 组无 OFF 基线**，其中 **3 组**的判定被标为不可靠。

## 九、副作用清单（REGRESSION）

共 **4** 条：OFF 正确、ON 错误。

| 题号 | 臂 | 归因强度 | ON 失败点 |
|---|---|---|---|
| E-0064 | E10_ON | `TEXTUAL_TRACE` | `EXEC_MISMATCH` / 结果集合不一致 |
| E-0075 | E10_ON | `WEAK_PROMPT_CHANGE_ONLY` | `EXEC_MISMATCH` / 结果集合不一致 |
| E-0042 | E11_ON | `TEXTUAL_TRACE` | `EXEC_MISMATCH` / 排名题集合不一致 |
| E-0074 | E11_ON | `WEAK_PROMPT_CHANGE_ONLY` | `EXEC_MISMATCH` / 排名题集合不一致 |

逐条说明见 §四~§七 的「归因注记」。要点：

- `TEXTUAL_TRACE`（E-0064 / E-0042）：ON 的 SQL 里能**逐字找到**规则子句的痕迹
  （E-0064 使用了规则要求的 `NULLIF(x,0)`；E-0042 把 `orders.id` 加进了 GROUP BY，
  而 `orders.id` 正是 E11 契约首推的破平键）⇒ 归因有文本证据。
- `WEAK_PROMPT_CHANGE_ONLY`（E-0075 / E-0074）：prompt 确实不同，但 ON 的失败点与规则语义
  **无关**（E-0075 是退化的 `CASE WHEN ratio THEN 0 ELSE 1`；E-0074 是时间过滤被改写成单月）
  ⇒ 只能归因到「prompt 变化」，**不能**归因到规则的具体子句；n=1 亦不能排除采样噪声。

## 十、API call count

| 项 | 值 |
|---|---|
| 主运行真实调用 | 17 |
| 补充运行真实调用 | 3 |
| **合计真实调用** | **20** |
| 硬门上限 | 20 |
| 是否超限 | False |
| 单题单臂 ≤ 1 次 | **True** |
| provider 失败数 | **0** |
| 记录条数（题 × 臂） | 20 |

计数方式：monkeypatch `BailianProvider._call_model`（**最内层网络方法**），并在 harness 内
把 `_NETWORK_RETRY_DELAYS_SECONDS` 置空（**仅内存**），确保「1 次 generate ⇒ 至多 1 次网络调用」。

## 十一、延迟

| 统计量 | 值（ms） |
|---|---|
| n | 20 |
| mean | 3057.8 |
| p50（`sorted[n//2]`，非插值） | 3102.23 |
| min | 2080.07 |
| max | 4153.96 |

| 臂 | n | EX✓ | 平均延迟（ms） |
|---|---|---|---|
| OFF | 7 | 4 | 3198.97 |
| E4_ON | 2 | 1 | 2302.45 |
| E9_ON | 4 | 3 | 2867.33 |
| E10_ON | 4 | 2 | 3266.51 |
| E11_ON | 3 | 1 | 3207.67 |

> ⚠️ **延迟差异不得归因**：OFF / ON 的 prompt 长度不同、LLM 输出本身会漂，且各臂样本题不同。
> 上表仅作记录，不用于任何结论。

## 十二、五类判定明细

| 判定 | 条数 |
|---|---|
| `FIXED` | 1 |
| `RULE_TRIGGERED` | 1 |
| `NO_OBSERVED_EFFECT` | 7 |
| `REGRESSION` | 4 |
| `EFFECT_UNCONFIRMED` | 0 |
| **合计** | **13** |

| 题号 | 臂 | 预注册判定 | 主运行判定 | 机制改变 | ON✓ | OFF✓ | 可靠 |
|---|---|---|---|---|---|---|---|
| E-0082 | E4_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | False | False | True |
| E-0081 | E4_ON | `RULE_TRIGGERED` | `RULE_TRIGGERED` | True | True | False | False |
| E-0065 | E9_ON | `FIXED` | `FIXED` | True | True | False | True |
| E-0083 | E9_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | False | False | True |
| E-0053 | E9_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | True | False | True |
| E-0073 | E9_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | True | False | True |
| E-0075 | E10_ON | `REGRESSION` | `REGRESSION` | True | False | True | True |
| E-0076 | E10_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | True | False | False |
| E-0064 | E10_ON | `REGRESSION` | `NO_OBSERVED_EFFECT` | False | False | True | True |
| E-0089 | E10_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | True | False | False |
| E-0098 | E11_ON | `NO_OBSERVED_EFFECT` | `NO_OBSERVED_EFFECT` | False | True | False | True |
| E-0074 | E11_ON | `REGRESSION` | `NO_OBSERVED_EFFECT` | False | False | True | True |
| E-0042 | E11_ON | `REGRESSION` | `NO_OBSERVED_EFFECT` | False | False | True | True |

### 12.1 与主运行的判定漂移（3 条，成因已证明）

| 题号 | 臂 | 主运行 | 合并后 | 成因 |
|---|---|---|---|---|
| E-0064 | E10_ON | `NO_OBSERVED_EFFECT` | `REGRESSION` | 主运行缺 OFF 基线（off is None 分支）；合并后按真实 OFF 基线重判 |
| E-0074 | E11_ON | `NO_OBSERVED_EFFECT` | `REGRESSION` | 主运行缺 OFF 基线（off is None 分支）；合并后按真实 OFF 基线重判 |
| E-0042 | E11_ON | `NO_OBSERVED_EFFECT` | `REGRESSION` | 主运行缺 OFF 基线（off is None 分支）；合并后按真实 OFF 基线重判 |

漂移**不是**判定逻辑改变，而是主运行时这 3 题的 OFF 基线**尚未采集**（`off is None` 分支），
补充运行补上真实 OFF 基线后按同一份 `judge()` 重判。已用 `judge(on, OFF_if_main_had_it, ...) == main_verdict` **13/13 逐条断言**证明这一点。

### 12.2 零效应伪影（规则未注入）

| 题号 | 臂 | 说明 |
|---|---|---|
| E-0083 | E9_ON | 规则未注入 Prompt（与 OFF 逐字节相同）⇒ 输出差异不可归因于规则，属采样噪声 |
| E-0053 | E9_ON | 规则未注入 Prompt（与 OFF 逐字节相同）⇒ 输出差异不可归因于规则，属采样噪声 |
| E-0073 | E9_ON | 规则未注入 Prompt（与 OFF 逐字节相同）⇒ 输出差异不可归因于规则，属采样噪声 |

## 十三、隔离检查

| 项 | 结果 |
|---|---|
| tracked 文件变更 | **0**（无） |
| 冻结物变更 | **0**（无） |
| HEAD（主运行后 / 补充运行后） | `6c5f51c1d25c` / `6c5f51c1d25c` |
| index diff stat | `(空)` |
| `.env` | 未改（`LLM_PROVIDER` 仍为 `mimo`） |
| DB / Gold / FEWSHOT | 未改（冻结哈希前后一致） |
| commit | **无** |

冻结哈希（运行前后比对，全部 MATCH）：

```
benchmark  dba277cc0be7cc282df67c86dd7eabfea1337458612a86885f6daef0c6829f1a
fewshot    ee12fcc994c6afec42a94f4e327109961ac2022466673bc4a37485638f7d4cee
db         65e5d8b2727cfa064174f9a08aa7d4b08209e0edd1eba81f3155698f1a4491d9
.env       dce981d984dd759c502e1306784c80c2319a49c79c156e4fdfa96fb89b34a624
```

## 十四、结论与限制

### 14.1 逐规则结论

**E9（全局口径 / 时间过滤）—— 唯一在真实链路上被确证有效的规则**

- `E-0065` **FIXED**：OFF 的内层子查询继承了全局时间过滤 `strftime('%Y',order_date)='2026'`（结构判据 True）⇒ 1246；ON 去掉内层过滤（False）⇒ 1236 = gold。
  这是四条规则中**唯一**同时满足四条件（OFF 有问题 / ON 改变机制 / ON 更接近 Gold / 无新副作用）的条目。
- 3 个负例（E-0083 / E-0053 / E-0073）**均未误触发**（Prompt 与 OFF 逐字节相同）。

**E11（Top-N 破平键）—— 有真实收益，也有真实副作用**

- `E-0098`：**原始证据支持 FIXED**（OFF 无破平键 ⇒ EX✗；ON 加 `p.id ASC` ⇒ EX✓），
  但**预注册机制判据漏检**（判据 keyed on `any_order_has_secondary_key`，两臂皆 True，
  真实变化在 `window_has_secondary_key`）⇒ 按预注册口径只能写 `NO_OBSERVED_EFFECT`，
  另附事后补充判定 `FIXED`（明确标注 `POST_HOC_NOT_PREREGISTERED`）。
- ⭐ **这直接修正了 Task 44 的结论**：Task 44 用离线复算「证伪」了破平键的必要性
  （gold 去掉 `prod_id` 后 66 行且集合相等）。本次离线**二分复算**证明：
  gold 的写法下隐式行序**恰好**与破平键一致，所以看不出差别；而 OFF 的等价 SQL
  在同一并列处（`sold=105`，儿童玩具类目）**选中了不同实体**，补上破平键后与 gold 完全一致。
  ⇒ 破平键的作用是**让结果不依赖执行计划**，Task 44 的「防御性约束、收益未证实」定性应改为
  「真实链路已证实有效，但收益与副作用并存」。
- 副作用 2 条：`E-0042`（把 `orders.id` 加进 **GROUP BY** ⇒ 聚合粒度破坏，可追溯）与
  `E-0074`（时间过滤被改写为单月，与破平键无语义关联，最可能为采样波动）。

**E10（比值方向）—— 在真实链路上出现净负面**

- `E-0075` REGRESSION：方向抽取本身**正确**，但 SQL 被写成退化的 `CASE WHEN ratio THEN 0 ELSE 1`。
- `E-0064` REGRESSION：规则字面句「A 占 B 的比例 ⇒ A / B」与 benchmark 隐含的
  「比例 = 百分比数值（×100）」口径冲突，ON 输出 0.0503（gold 5.03）。
- `E-0076` / `E-0089` 均 EX✓，但**无 OFF 基线** ⇒ 不能归功于规则。
- ⚠️ 另暴露一个**评测口径缺陷**：E-0064 题面只说「比例是多少」而 gold 用 `* 100.0`；
  同族的 E-0076（「百分之几」）/ E-0089（「占比百分比」）题面都显式写了百分比。
  ⇒ 「比例」在 benchmark 中是**未言明约定**，任何按字面理解的模型都会被判错。

**E4（输出列契约增强）—— 未产生可观测变化**

- `E-0082` `NO_OBSERVED_EFFECT`：规则已注入，但 ON/OFF 的 SQL 与结果**完全一致**（同 hash）。
  两臂都 EX✗（gold=2 列 / pred=1 列）⇒ **E4 未能修复它的目标失败模式**。
- `E-0081` 标为不可靠（无 OFF 基线 + 机制判据退化）。

### 14.2 硬限制（不得越过）

1. **管线不等价**：本 harness 用「全量 Schema 注入 + 无 Repair」替代完整生产图（≥2 次 LLM/题）。
   结论**不能**外推到生产链路。
2. **n=1 / 臂**：OFF 与 ON 各 1 次采样，无法把「规则效应」与「采样噪声」完全分离。
   故所有 REGRESSION 都标了归因强度，且 `TEXTUAL_TRACE` 才具备文本证据。
3. **OFF 基线缺失 6 组**：其中 3 组的判定不可靠（E-0081 / E-0076 / E-0089）。
4. **不计算人为总分**：本报告只给逐条判定与计数，不给「E10 提升 X%」这类数字。
5. **未改变生产默认**：E4/E9/E10/E11 仍**默认关闭**；是否转正需人工决策。

### 14.3 转正建议（基于本次实测）

| 规则 | 建议 | 依据 |
|---|---|---|
| **E9** | 可优先考虑转正 | 唯一四条件齐备的 FIXED；3 个负例未误触发 |
| **E11** | 需先收窄措辞再转正 | 有真实收益（E-0098）但把主键写进 GROUP BY 的副作用已实测复现（E-0042） |
| **E10** | **不建议转正**（至少先改口径） | 4 题中 2 题 REGRESSION，且与 benchmark「比例=百分比」隐含约定冲突 |
| **E4** | 无证据支持转正 | 目标失败模式（E-0082）未被修复 |

---

## 十五、固定字段输出

```
TASK45=COMPLETE
MODE=REAL
PROVIDER=bailian / qwen3.7-flash-2026-07-15
DEFAULT_PROVIDER_UNCHANGED=YES (LLM_PROVIDER=mimo in .env)
ENV_UNCHANGED=YES
DB_UNCHANGED=YES
GOLD_UNCHANGED=YES
FEWSHOT_UNCHANGED=YES
COMMIT=NONE
SAMPLE_N=13
ARMS=OFF,E4_ON,E9_ON,E10_ON,E11_ON
REAL_API_CALLS=20
CALL_BUDGET=20
CALL_BUDGET_OK=YES
ONE_CALL_PER_RUN=YES
PROVIDER_FAILURES=0
IDENTITY_REPLAY=13/13 PASS
PROBE_INVALID=0
E4=E-0082:NO_OBSERVED_EFFECT | E-0081:RULE_TRIGGERED(UNRELIABLE)
E9=E-0065:FIXED | E-0083:NO_OBSERVED_EFFECT(not_injected) | E-0053:NO_OBSERVED_EFFECT(not_injected) | E-0073:NO_OBSERVED_EFFECT(not_injected)
E10=E-0075:REGRESSION | E-0076:NO_OBSERVED_EFFECT(WEAK,no_off) | E-0064:REGRESSION | E-0089:NO_OBSERVED_EFFECT(WEAK,no_off)
E11=E-0098:NO_OBSERVED_EFFECT(predicate_miss; supplementary=FIXED) | E-0074:REGRESSION | E-0042:REGRESSION
E11_STATUS=E11_EFFECT_CONFIRMED
FIXED=1
RULE_TRIGGERED=1
NO_OBSERVED_EFFECT=7
REGRESSION=4
EFFECT_UNCONFIRMED=0
UNRELIABLE_VERDICTS=3
OFF_BASELINE_MISSING=6
ZERO_EFFECT_ARTIFACTS=3
PROMPT_HASH_REPRODUCIBLE=20/20
VERDICT_REPRODUCIBLE=13/13
LATENCY_MEAN_MS=3057.8
LATENCY_P50_MS=3102.23
TOTAL_SCORE=NOT_COMPUTED
```

---

**产物**：

- `F:/task45_semantic_contract_validation/task45_report.md`（本文件）
- `F:/task45_semantic_contract_validation/raw_results.json`（20 条记录 + 13 组对照 + 全部 SQL 全文）
- `F:/task45_semantic_contract_validation/run_task45.py`（harness，位于**仓库外**）
- `F:/task45_semantic_contract_validation/merge_and_report.py`（合并 + 一致性断言）
