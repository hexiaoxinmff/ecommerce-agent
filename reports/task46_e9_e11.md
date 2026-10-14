# Task 46：E9 扩大验证 + E11 规则收窄

> 目标：① 验证 E9 的触发边界是否足够稳定；② 修复 E11 已发现的 GROUP BY 粒度破坏；
> ③ E10 / E4 保持默认关闭；④ 默认 Provider 不变；⑤ 不改 DB / Gold / FEWSHOT；
> ⑥ 优先离线验证，真实 Bailian 调用严格限量。
>
> 边界（全部遵守）：`LLM_PROVIDER` 仅在**进程内**临时设为 `bailian`（`.env` 仍是 `mimo`）/
> 不 commit / 不跑 100Q / **真实调用 8 次**（E9 6 + E11 2，硬门 8）/ 不输出 API Key。

---

## 一、执行摘要

| 项 | 结果 |
|---|---|
| E9 触发面（100 题冻结 benchmark） | **1 题**（E-0065） |
| E9 误触（false positive） | **0** |
| E9 漏触发（人工核对 4 个候选） | **0** |
| E9 真实调用 | 6 次（2 正例 × OFF/ON + 2 负例 × ON） |
| E9 真实结果 | 正例 **2/2 FIXED**；负例 **2/2 NO_OBSERVED_EFFECT**（规则未注入） |
| E11 离线测试 | **24 条**（A~F + 检查器自检），全 PASS |
| E11 真实调用 | 2 次（E-0098 / E-0042） |
| E11 结果 | 两题 **RULE_TRIGGERED**；GROUP BY 粒度破坏**未复现** |
| Identity Replay | **6/6 PASS**（含 1 道 harness 自撰题） |
| 真实 API 调用总数 | **8**（硬门 8） |
| 生产代码变更 | **1 个文件**（见 §八） |

---

## 二、E11：原始问题 → 收窄

### 2.1 原始问题（Task 45 真实回归）

| 题号 | 现象 | 后果 |
|---|---|---|
| `E-0042` | ON 把 `orders.id` 塞进 **GROUP BY**（`GROUP BY o.id, o.region`） | 聚合粒度从「按地区」变成「按订单行」⇒ EX✓ → EX✗ |
| `E-0074` | ON 把日期过滤从 `order_date >= '2025-10-01' AND < '2026-01-01'` 改写成 `substr(order_date,1,7) = '2025-10'` | Q4 → 单月 ⇒ EX✓ → EX✗ |

Phase 1 审计定位到的**文本级诱因**：

1. 旧文本只写「不得新增 **SELECT** 列」，**完全没提 GROUP BY** ⇒ 模型把主键塞进 GROUP BY 时没有任何约束；
2. 旧文本首句「破平键**优先使用业务主键**：orders.id / …」直接点名了 `orders.id`；
3. 旧文本的 fallback 列表含「**月份**」，是全文唯一与日期表达相关的词。

### 2.2 修改前机制（旧注入文本，逐字）

```
【Top-N 确定性排序契约】（本题是 Top-N / 排名题，请注意并列风险）
- 识别到的排名表述：「最高的3款」
- 本题的 Top-N 规模：N = 3
- 排名 / 截断（ORDER BY … LIMIT n、ROW_NUMBER()/RANK()/DENSE_RANK() … <= n、前 N 名）时，若**排序键可能并列**（尤其按 SUM / COUNT / AVG 等聚合指标排序），必须追加**稳定唯一键**作为最终排序键；
- 破平键优先使用业务主键：orders.id / order_items.id / products.id / categories.id / users.id；若无可用主键，则使用业务唯一标识（商品名 / 地区名 / 月份）；
- 破平键**只出现在 ORDER BY（或窗口函数的 ORDER BY）中，不得新增 SELECT 列** —— 多输出一列会破坏结果列契约；
- 不要给所有 ORDER BY 机械追加主键：仅当本题确实是「排名 / Top-N / LIMIT / 名次过滤」且排序键存在并列可能时才追加。
- 原因：排序键并列时，不追加破平键会让「谁进入 Top-N」变得不确定，同一 SQL 在不同执行计划下可能选中不同实体。
```

（字符数 548）

### 2.3 修改后机制（收窄后的注入文本，逐字）

```
【Top-N 确定性排序契约】（本题是 Top-N / 排名题，请注意并列风险）
- 识别到的排名表述：「最高的3款」
- 本题的 Top-N 规模：N = 3
- 本契约的**唯一**作用是：在 ORDER BY（含窗口函数的 ORDER BY）**末尾追加一个**确定性破平键。除排序外，不得改动 SQL 的任何其他部分。
- 适用条件：排名 / 截断（ORDER BY … LIMIT n、ROW_NUMBER()/RANK()/DENSE_RANK() … <= n、前 N 名）且**排序键可能并列**（尤其按 SUM / COUNT / AVG 等聚合指标排序）时追加；
- 正确写法示例：`ORDER BY 指标 DESC, p.id ASC`；窗口函数同理：`ROW_NUMBER() OVER (PARTITION BY … ORDER BY 指标 DESC, p.id ASC)`；
- 破平键优先使用业务主键：orders.id / order_items.id / products.id / categories.id / users.id；若无可用主键，则使用业务唯一标识（商品名 / 地区名 / 类别名 / 月份）；
- ❌ **禁止把破平键写进 GROUP BY**：不得出现 `GROUP BY …, p.id` 这类写法。破平键不是分组维度；写进 GROUP BY 会把「按实体聚合」拆成「按行聚合」，聚合粒度被改变，结果必然算错。
- ❌ **禁止把破平键写进 SELECT**：不得出现 `SELECT …, p.id`，除非原问题本身明确要求输出该字段（如题目要求「请给出订单 ID」）。多输出一列会破坏结果列契约。
- ❌ **禁止因为本契约改动 WHERE / HAVING 中的任何过滤条件**，尤其是日期 / 时间条件：破平键只影响排序，与过滤无关。不得改写、收窄、放宽或重写已有日期表达式（反例：把 `order_date >= '2025-10-01' AND order_date < '2026-01-01'` 改写成 `substr(order_date, 1, 7) = '2025-10'`）。
- ❌ **禁止因为本契约改变原有聚合粒度**：GROUP BY 的列集合必须与「不加破平键时」完全一致；本契约只允许在 ORDER BY 末尾追加一个键。
- 不要给所有 ORDER BY 机械追加主键：仅当本题确实是「排名 / Top-N / LIMIT / 名次过滤」且排序键存在并列可能时才追加。
- 原因：排序键并列时，不追加破平键会让「谁进入 Top-N」变得不确定，同一 SQL 在不同执行计划下可能选中不同实体。
```

（字符数 1144）

**收窄的核心**：把规则从「必须追加稳定唯一键」改为「**唯一作用是在 ORDER BY 末尾追加一个破平键**」，
并把四类误用写成显式禁止（❌ 标记）：

| # | 禁止项 | 对应 Task 45 的哪个回归 |
|---|---|---|
| 1 | 写进 **GROUP BY** | `E-0042`（本次修复目标） |
| 2 | 写进 **SELECT**（除原问题明确要求该字段） | 潜在风险（T45 未复现） |
| 3 | 改动 WHERE / HAVING 过滤，尤其日期 | `E-0074`（本次防护目标） |
| 4 | 改变原有聚合粒度（GROUP BY 列集合须与不加破平键时一致） | `E-0042` 的语义化表述 |

⚠️ 诚实记录：`E-0074` 的成因在 Task 45 被判为 `WEAK_PROMPT_CHANGE_ONLY`（失败点与破平键语义无关，
最可能是采样波动）。因此第 3 条禁止是**预防性**的，不是对已确证因果的修复。

### 2.4 离线回归测试（A~F）

文件：`backend/tests/test_task46_e11_narrowing.py`（24 条，全 PASS）

| 测试 | 内容 | 结果 |
|---|---|---|
| §0 / **F** | gold identity replay：100 题两次重放一致且等于冻结 `gold_result_hash` | **100/100 PASS** |
| **A** | Top-N 正常：E-0098 的 ON 只多一个 `ORDER BY` 破平键（`order_by_added == ['p.id ASC']`，其余零增量）；且 ON 与 gold 判等一致、OFF 不一致 | PASS |
| **B** | GROUP BY 粒度保护：检查器必须检出 `E-0042` 的真实回归（`group_by_added == ['o.id']`）；且粒度判据对「函数依赖列」不误报 | PASS |
| **C** | SELECT 契约保护：把破平键写进 SELECT ⇒ 输出列数 2→3 ⇒ 必须被检出 | PASS |
| **D** | 时间过滤保护：`E-0074` 的日期谓词改写必须被检出；无日期条件的 SQL 不得误报 | PASS |
| **E** | 标量 Top-1（E-0009/0010/0015/0032/0038）继续保持 E11 不触发 | PASS |
| §8 | 检查器**非空有效性**：5 组正/负样本参数化，证明它不会永远返回空 | PASS |

### 2.5 真实 smoke（2 次调用）

**`E-0098`** — `EXEC_MATCH`（4705 ms，注入=True）

- 题面：每个商品分类中，销量最高的3款商品分别是哪些？（请给出分类、商品名与销量；仅统计销量超过50的商品）
- GOLD：`WITH cat_prod AS (SELECT c.name AS cat_name, p.name AS prod_name, p.id AS prod_id, SUM(oi.quantity) AS sold FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id, p.name HAVING SUM(oi.quantity) > 50), ranked AS (SELECT cat_name, prod_name, sold, ROW_NUMBER() OVER (PARTITION BY cat_name ORDER BY sold DESC, prod_id) AS rk FROM cat_prod) SELECT cat_name, prod_name, sold AS sold_qty FROM ranked WHERE rk <= 3 ORDER BY cat_name, rk`
- PRED：`WITH category_product_sales AS (SELECT c.id AS category_id, p.id AS product_id, p.name AS product_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id HAVING total_sold > 50), ranked_products AS (SELECT category_id, product_name, total_sold, ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY total_sold DESC, product_id ASC) AS rn FROM category_product_sales) SELECT c.name AS category_name, rp.product_name, rp.total_sold FROM ranked_products rp JOIN categories c ON c.id = rp.category_id WHERE rp.rn <= 3`

| guard | 值 | 判定 |
|---|---|---|
| GROUP BY 主键列 | `['id']` vs gold `['id']` | **PASS** |
| GROUP BY 全列（审计用） | `['id']` vs gold `['id', 'name']` | 精确相等 = False |
| SELECT 列数 | 3 vs gold 3 | **PASS** |
| 日期谓词 | `[]` vs gold `[]` | **PASS** |
| ORDER BY 键 | `['total_sold DESC', 'product_id ASC']` | 破平键只出现在 ORDER BY |
| **不变量** | `invariant_holds` | **True** |

> E-0098 仍能触发：窗口 `ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY total_sold DESC, product_id ASC)`
> 中的 `product_id ASC` 就是破平键，且结果与 gold 判等一致。

**`E-0042`** — `EXEC_MISMATCH`（2736 ms，注入=True）

- 题面：非取消订单实付销售额最高的10个收货地区是哪些？（请给出地区名称与销售额）
- GOLD：`SELECT region, ROUND(SUM(total_amount), 2) AS revenue FROM orders WHERE status != 'cancelled' GROUP BY region ORDER BY revenue DESC LIMIT 10`
- PRED：`SELECT o.region AS region_name, ROUND(SUM(oi.subtotal), 2) AS total_sales FROM orders o JOIN order_items oi ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY o.region ORDER BY total_sales DESC, o.region ASC LIMIT 10`

| guard | 值 | 判定 |
|---|---|---|
| GROUP BY 主键列 | `[]` vs gold `[]` | **PASS** |
| GROUP BY 全列（审计用） | `['region']` vs gold `['region']` | 精确相等 = True |
| SELECT 列数 | 2 vs gold 2 | **PASS** |
| 日期谓词 | `[]` vs gold `[]` | **PASS** |
| ORDER BY 键 | `['total_sales DESC', 'o.region ASC']` | 破平键只出现在 ORDER BY |
| **不变量** | `invariant_holds` | **True** |

> ⭐ **本次修复目标的直接验证**：Task 45 的 ON 是 `GROUP BY o.id, o.region`；
> 本次 ON 是 `GROUP BY o.region`（主键列**没有**再进入 GROUP BY），破平键 `o.region` 落在 `ORDER BY` 末尾。
> 该题仍为 EX✗，但原因是**另一个**缺陷：预测用了 `SUM(oi.subtotal)`（明细口径），
> gold 用 `SUM(total_amount)`（订单实付口径）⇒ 指标列选择错误，与 E11 契约无关，**不记为 E11 的 REGRESSION**。

### 2.6 E11 判定

| 题号 | 判定 | 依据 |
|---|---|---|
| `E-0098` | `RULE_TRIGGERED` | 规则已注入 + 机制按预期改变（窗口 ORDER BY 增加 `product_id ASC`）+ 结果正确；**本轮无同轮 OFF 基线** ⇒ 按纪律不写 `FIXED` |
| `E-0042` | `RULE_TRIGGERED` | 规则已注入 + 破平键只出现在 ORDER BY、GROUP BY 粒度未变 ⇒ 契约按预期生效；目标回归**未复现** |

> ⚠️ **本轮无法判定 E11 是否「修复」了 E-0042**：本任务没有为 E-0042 采集 OFF 基线（预算上限 8），
> 且该题本轮 EX✗ 由非 E11 缺陷导致。可以说的是：**已观测到的 GROUP BY 回归没有再次出现**。n=1/题。

---

## 三、E9：触发面扩大验证

### 3.1 100 题 deterministic 扫描（不调用任何 LLM）

- **E9_TRIGGER_COUNT = 1**
- **E9_FALSE_POSITIVE_COUNT = 0**
- E9_NON_TRIGGER_COUNT = 99

触发题（唯一）：

- `E-0065`　2026年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？
  - time_terms = `['2026年']`，global_terms = `['全平台']`
  - gold：`SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`

### 3.2 误触核对：把判据放宽到「全部 / 所有」会误触的 12 题

这些题**同时**含时间过滤与「全部 / 所有 / 各」类词，但**没有**平台级词。窄判据全部放过：

| 题号 | 题面 | 为什么**不该**触发 |
|---|---|---|
| E-0049 | 按季度统计2024年的订单数量，每个季度各有多少笔订单？… | 「每个季度各有多少笔」——各季度是同一时间窗内的对象 |
| E-0064 | 2025年各订单状态的订单数及其占2025年总订单数的比例是多少？… | 分母「2025年总订单数」与本题共享 2025 窗口 |
| E-0066 | 2025年各季度、各订单状态的实付销售额分别是多少？（不含取消订单；请按季度与状态列出）… | 各季度/各状态都是 2025 窗口内的分组 |
| E-0067 | 最近90天（2026年6月14日至9月12日）各地区各类别的销售金额最高的8个组合是哪些… | 各组合都在最近 90 天窗口内 |
| E-0071 | 2025年各月、各订单状态的订单数量分别是多少？（请按月份与状态列出）… | 各月/各状态都在 2025 窗口内 |
| E-0077 | 2025年各收货地区的非取消订单销售额中，高于各地区平均销售额的地区有哪些？（请给出地区… | 「各地区平均销售额」是**同一窗口内**的基准 |
| E-0083 | 2025年第四季度中，家用电器类目销售金额占该季度全部商品销售金额的比例是多少？（百分比… | 「该季度全部商品销售金额」被同一句时间窗限定（**本题被任务书锁定为 NO**） |
| E-0090 | 2025年各订单状态下，实付金额高于5000元的高金额订单数与5000元及以下的普通订单… | 比较对象是固定阈值 5000 元，不是全局基准 |
| E-0091 | 2025年各收货地区、各季度的平均实付金额（客单价）是多少，每个组合的订单量如何？（仅列… | 各地点-季度组合都在 2025 窗口内 |
| E-0093 | 2025年各收货地区中，销售金额最高的3个商品分类分别是哪些？（请给出地区、分类与销售额… | 各地区/各分类都在 2025 窗口内 |
| E-0094 | 2025年各月的非取消订单实付销售额与2024年同月相比的同比增速是多少？（请给出月份、… | 同比的基期是同月，不是全局基准 |
| E-0095 | 最近30天（2026年8月14日至9月12日）中，有哪些地区-分类组合的销售金额高于30… | 「该地区各组合的平均」是**分区内**基准，非全局 |

**E-0083 特别锁定**：`trigger = NO` ✓（题面含「全部」但无平台级词；且其 gold 的分母子查询
**保留**了 `o3.order_date >= '2025-10-01' AND <= '2025-12-31'` ⇒ 正是「必须保留时间窗」的反例）。

### 3.3 漏触发核对（false negative）

对 4 个「时间过滤 ∧ 参照基准语义 ∧ 全局类词」的候选逐一人工核对，全部**应当**不触发：

| 题号 | 命中词 | 结论 |
|---|---|---|
| E-0064 | 「各订」 | 分母与本题共享 2025 窗口 ⇒ 正确放过 |
| E-0077 | 「各地」 | 基准是同一 2025 窗口内的地区均值 ⇒ 正确放过 |
| E-0083 | 「全部」 | 被同一句时间窗限定 ⇒ 正确放过 |
| E-0090 | 「各订」 | 无全局基准（固定阈值比较）⇒ 正确放过 |

**E9_FALSE_NEGATIVE_COUNT = 0**（在上述 4 个可核对候选内）。

### 3.4 离线语义 fixtures

文件：`backend/tests/test_task46_e9_boundary.py`（29 条，全 PASS）

| 组 | 数量 | 内容 | 期望 |
|---|---|---|---|
| Positive | 5 | 「2026年各地区销量与**全平台**平均销量相比」「高于**全站**平均」「**整个平台**平均」「**平台整体**平均」 | 全部触发 ✓ |
| Negative | 7 | 「2026年**全部**商品中销量最高」「该季度**全部**商品销售金额」「2025年**所有**订单总金额」「占2025年总订单数比例」「**全部**收货地区」等 | 全部不触发 ✓ |
| Boundary | 4 | 有平台级词但**无时间过滤**（「全平台商品平均售价是多少？」等） | 全部不触发 ✓ |
| 真实题锁定 | 6 | E-0065 YES；E-0083 / E-0077 / E-0064 / E-0090 / E-0058 NO | ✓ |

fixture 的核心区分：**「全局参照基准」≠「同一时间窗口内的全部对象」**。
另外两条测试直接用 gold 证明这两种情形：

- `E-0065` 的 gold：参照基准子查询内**没有** `order_date` ⇒ 基准不受外层时间窗限制；
- `E-0083` 的 gold：分母子查询内**保留**了季度过滤 ⇒ 与 E-0065 正好相反。

### 3.5 真实 smoke（6 次调用）

| 题号 | 臂 | 注入 | 检测命中 | 结果 | 行数 | 延迟 |
|---|---|---|---|---|---|---|
| E-0065 | OFF | False | True | EXEC_MISMATCH | 1 | 2935 ms |
| E-0065 | E9_ON | True | True | EXEC_MATCH | 1 | 2870 ms |
| E9POS2-HARNESS | OFF | False | True | EXEC_MISMATCH | 1 | 4584 ms |
| E9POS2-HARNESS | E9_ON | True | True | EXEC_MATCH | 1 | 2641 ms |
| E-0083 | E9_ON | False | False | EXEC_MISMATCH | 1 | 4473 ms |
| E-0077 | E9_ON | False | False | EXEC_MATCH | 7 | 3023 ms |

**`E-0065`**

- 题面：2026年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？
- GOLD：`SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`
- OFF SQL：`SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled')`
- ON  SQL：`SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2026' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`

**`E9POS2-HARNESS`**

- 题面：2025年实付金额高于全平台非取消订单平均实付金额的订单有多少笔？
- GOLD：`SELECT COUNT(*) FROM orders WHERE order_date >= '2025-01-01' AND order_date <= '2025-12-31' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`
- OFF SQL：`SELECT COUNT(*) AS order_count FROM orders WHERE status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`
- ON  SQL：`SELECT COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2025' AND status != 'cancelled' AND total_amount > (SELECT AVG(total_amount) FROM orders WHERE status != 'cancelled')`

**机制对照（内层参照基准是否继承了外层时间过滤）**

| 题号 | OFF | ON | 判定 |
|---|---|---|---|
| `E-0065` | 内层 `SELECT AVG(total_amount) … WHERE strftime('%Y',order_date) = '2026'` ⇒ **继承**了 2026 过滤 | 内层只剩 `status != 'cancelled'` ⇒ **未继承** | **FIXED**（EX✗ → EX✓） |
| `E9POS2-HARNESS` | 外层**整个丢了** 2025 过滤（无任何 `order_date` 条件） | 外层恢复 `strftime('%Y',order_date) = '2025'`，内层保持干净 | **FIXED**（EX✗ → EX✓，但见下方 caveat） |

> ⚠️ **E9POS2 的归因弱于 E-0065**：本题 OFF 的缺陷是「外层时间过滤被丢失」，
> 而 E9 契约的字面靶点是「参照基准不得**继承**外层时间过滤」。规则文本确实强调
> 「参照基准要写成独立标量子查询」「只有本题被识别为全局口径时才适用本段；其他题目不要无理由去掉时间过滤」，
> 但它**没有**直接规定「主查询必须保留时间过滤」⇒ 该题的修复**可能**来自 prompt 变化带来的整体谨慎度提升，
> 而非某条具体子句。n=1，不能排除采样噪声。

**负例（规则未注入）**

| 题号 | 注入 | 结果 | 说明 |
|---|---|---|---|
| `E-0083` | **False**（prompt 与 OFF 逐字节相同） | EX✗ | 失败原因是**列契约**：预测只输出 1 列（`percentage`），gold 要 2 列（`c.name` + `pct`）——与 E9 无关。**关键正面证据**：预测对分子分母**都保留了** Q4 过滤（`substr(order_date,1,7) BETWEEN '2025-10' AND '2025-12'`），即 E9 开启**没有**诱导模型丢掉合法时间过滤。 |
| `E-0077` | **False** | EX✓ | 预测把地区聚合与均值都限定在同一 2025 窗口内（`avg_sales` 取自同一个 `region_sales` CTE）⇒ 「同一时间窗内的全部对象」语义被正确保留。 |

### 3.6 E9 判定

| 题号 | 判定 | 依据 |
|---|---|---|
| `E-0065` | **`FIXED`** | OFF 有明确缺陷（内层继承 2026 过滤）→ ON 改变机制（内层过滤消失）→ 结果由 EX✗ 变 EX✓ → 无新副作用。四条件齐备（n=1，机制有结构证据） |
| `E9POS2-HARNESS` | **`FIXED`** | 同上四条件齐备；但修复的缺陷（外层过滤丢失）与契约字面靶点不完全一致 ⇒ 归因强度弱于 E-0065 |
| `E-0083` | **`NO_OBSERVED_EFFECT`** | 规则未注入（prompt 与 OFF 逐字节相同）⇒ 因果上等价于 OFF；其 EX✗ 属列契约缺陷 |
| `E-0077` | **`NO_OBSERVED_EFFECT`** | 规则未注入 ⇒ 因果上等价于 OFF；结果正确 |

---

## 四、真实调用与延迟

| 项 | 值 |
|---|---|
| Provider | `bailian` / `qwen3.7-flash-2026-07-15`（类 `BailianProvider`） |
| 真实调用总数 | **8** |
| 硬门 | 8 |
| 是否超限 | False |
| 单次（题 × 臂）≤ 1 次 | **True** |
| provider 失败 | 0 |

| 统计量 | 值（ms） |
|---|---|
| n | 8 |
| mean | 3495.84 |
| p50（`sorted[n//2]`，非插值） | 3022.74 |
| min / max | 2640.97 / 4705.3 |

> 计数方式：monkeypatch `BailianProvider._call_model`（**最内层网络方法**），
> 并在 harness 内把 `_NETWORK_RETRY_DELAYS_SECONDS` 置空（**仅内存**）。

> ⚠️ 延迟不用于任何结论（各臂 prompt 长度不同、LLM 输出本身会漂）。

---

## 五、检查器与判据（可复核）

### 5.1 E11 不变量检查器

文件：`F:/task46_e9_e11/e11_guard.py`（纯函数，无 LLM / 无 DB）。真实运行与离线复算**共用同一份**。

```
不变量：E11 只允许在 ORDER BY（含窗口 ORDER BY）追加一个键；
        相对 gold，SELECT 输出列数、GROUP BY 聚合粒度、日期谓词必须保持不变。

粒度判据 = GROUP BY 中的主键列集合（本项目约定列名 `id`）必须相等。
  理由：GROUP BY c.id, p.id 与 GROUP BY c.id, p.id, p.name 是同一粒度
        （p.name 函数依赖于 p.id），精确列集合比较会误报。
```

**判据自身的有效性**（§8 参数化测试 + 真实数据）：

| 样本 | 期望 | 实际 |
|---|---|---|
| T45 的 `E-0042` ON（`GROUP BY o.id, o.region`） | 检出粒度违例 | ✓ 检出 |
| T45 的 `E-0098` ON（`GROUP BY c.id, p.id` vs gold 多一列 `p.name`） | **不得**误报 | ✓ 未误报 |
| T45 的 `E-0074` ON（日期谓词被改写） | 检出时间过滤违例 | ✓ 检出 |
| T45 的 `E-0098` ON（只加 ORDER BY 键） | 零违例 | ✓ 零违例 |

⚠️ 已知限制：`groupby_cols_exact_match` 会对**函数依赖列**给出 false negative（E-0098 实测），
故它只作审计字段，**判定只用 `groupby_grain_ok`**。

---

## 六、隔离检查

| 项 | 结果 |
|---|---|
| HEAD unchanged | **True**（`6c5f51c1d25c`） |
| index clean | **True**（staged 文件数 0） |
| tracked 文件 sha256（开工前 vs 现在） | **0 个变化**（共 824 个 tracked 文件） |
| 冻结物（benchmark / fewshot / db / .env） | **0 个变化** |
| `.env` 的 `LLM_PROVIDER` | 仍为 `mimo`（Bailian 仅进程内覆盖） |
| commit | **无** |

### 6.1 本任务实际改动的文件（mtime 取证）

```
2026-09-21 13:25  backend/app/sqlgen/semantic_contracts.py        ← 生产代码（E11 收窄）
2026-09-21 13:28  backend/tests/test_task44_semantic_rules.py     ← 既有测试（断言/文档同步）
2026-09-21 13:29  backend/tests/test_task46_e9_boundary.py        ← 新增（E9 fixtures）
2026-09-21 13:33  backend/tests/test_task46_e11_narrowing.py      ← 新增（E11 A~F）
```

`backend/` 下**再无其他文件**被改动（`find backend -newermt` 全量核对，已排除 `__pycache__`）。

### 6.2 生产代码变更清单（按要求明确列出）

| 文件 | 变更 | 是否 tracked |
|---|---|---|
| `backend/app/sqlgen/semantic_contracts.py` | `RankingTiebreakContract.to_prompt_block()` 注入文本收窄（549 → 1145 字符）+ 模块 docstring 的 E11 条目 | **否**（T44 新增，从未 `git add`） |
| `backend/tests/test_task44_semantic_rules.py` | `test_D_e11_injects_for_ranking_questions_only` 的断言由旧措辞改为新的两条禁止锚点；`test_D_honest_record_…` 的 docstring 记录 T45 更正 | **否**（T44 新增） |

**未改动**：`sqlgen/prompt.py`、`sqlgen/semantic_contracts.py` 的 detector 逻辑、任何 T37/T38/T39-L 文件。

> 由于 `semantic_contracts.py` 未被 git 跟踪，git 快照对它**完全隐形** —— 因此上表是**人工声明的变更清单**，
> 其内容可由 `phase1_audit.txt`（编辑前逐字捕获的旧文本）与新文本逐字对照复核。
> detector 行为未变的证据：触发面仍是 **25 题**（离线测试锁定），100 题扫描仍是 **1 题**。

---

## 七、测试

| 范围 | 结果 |
|---|---|
| Task 46 E11（`test_task46_e11_narrowing.py`） | **24 passed** |
| Task 46 E9（`test_task46_e9_boundary.py`） | **29 passed** |
| Task 44 + prompt_rules（回归） | 53 passed |
| **全量 `backend/tests`** | **749 passed / 0 failed** |

（Task 44 完成时为 694 ⇒ 本任务净增 **55** = 24 + 29 + 2 条粒度判据测试。）

---

## 八、证据等级与下一阶段

### 8.1 E9 当前证据等级

| 维度 | 状态 |
|---|---|
| 触发边界稳定性 | **高**：100 题扫描误触 0、漏触发 0（4 个候选逐一核对）；29 条 fixtures 锁定「全局参照基准 ≠ 同一时间窗内的全部对象」 |
| 真实机制确证 | **中**：`E-0065` 四条件齐备（T45 + T46 两次独立采样均 FIXED） |
| 真实证据基数 | **低**：冻结 benchmark 中 E9 的靶题**只有 1 题**；本任务用 1 道 harness 自撰题把真实正例扩到 2 题 |
| 负例保护 | **高**：4 个真实负例（E-0083/E-0077 + fixtures）全部未被误触发，且 E-0083 的预测**保留了**合法时间过滤 |

**结论：E9 具备「定向开启」的资格，但不具备「全局开启」的证据。**
本任务**未**改变任何默认开关（E9 仍为 OFF）。

### 8.2 E11 当前证据等级

| 维度 | 状态 |
|---|---|
| 规则文本收窄 | **完成**：四类误用显式禁止 + 「唯一作用」声明 |
| 离线回归保护 | **高**：A~F 全通过；检查器经 5 组正/负样本证明非空有效 |
| 真实收益 | **中**：`E-0098` 本轮仍触发且结果正确（T45 + T46 两次） |
| 目标回归修复 | **低–中**：`E-0042` 的 GROUP BY 粒度破坏**未再出现**，但 n=1/题，且本轮无同轮 OFF 基线 ⇒ 不能宣称已修复 |
| 剩余风险 | **未测**：SELECT 契约风险与时间过滤风险在真实链路上均**未被复现**（T45 只复现了 GROUP BY 与时间过滤两条；本轮只 smoke 了 2 题） |

**结论：E11 的已知回归已由措辞收窄覆盖，但真实证据不足以转正。**

### 8.3 下一阶段是否可以考虑 100Q

**不建议现在直接跑 100Q**，理由分规则说明：

1. **对 E9 而言，100Q 的信息增量很低**：E9 在冻结 benchmark 上**只有 1 道靶题**（E-0065）。
   跑 100Q 只会再采样 1 道正例，无法提升证据基数。要扩 E9 的证据，需要的是**扩充题库**
   （补更多「全局参照基准 + 时间过滤」的题），而不是跑 100Q。
2. **对 E11 而言，100Q 有价值但时机未到**：E11 触发面 25 题，100Q 能给出真实副作用面。
   但本轮只 smoke 了 2 题，SELECT 契约与时间过滤两条风险在真实链路上**尚未被验证过**。
   建议先做 **25 题触发面的小样本定向验证**（约 25–50 次调用），确认收窄后的措辞在
   全部 Top-N 题上都不产生 GROUP BY / SELECT / 时间过滤违例，再考虑 100Q。
3. **100Q 还牵涉预算与 Provider 决策**：默认 Provider 仍是 `mimo`（本任务未改）；
   100Q × ≥2 次 LLM/题 = 200+ 次调用，需要单独的任务书与预算批准。

---

## 九、固定字段输出

```
TASK46=COMPLETE
E9_TRIGGER_COUNT=1
E9_FALSE_POSITIVES=0
E9_REAL_CALLS=6
E9_RESULT=FIXED(2/2 positive) | NO_OBSERVED_EFFECT(2/2 negative, not injected)
E11_OFFLINE_TESTS=24 passed (A~F + checker self-test)
E11_GROUPBY_GUARD=PASS (E-0042: GROUP BY o.region, no PK column added)
E11_SELECT_GUARD=PASS (E-0098: 3 cols == gold 3 cols; E-0042: 2 == 2)
E11_TIMEFILTER_GUARD=PASS (no date predicates added/removed in both smokes)
E11_REAL_CALLS=2
E11_RESULT=RULE_TRIGGERED(E-0098) | RULE_TRIGGERED(E-0042, target regression NOT reproduced)
E4_DEFAULT=OFF
E9_DEFAULT=OFF
E10_DEFAULT=OFF
E11_DEFAULT=OFF
PROD_CODE_CHANGED=1 file: backend/app/sqlgen/semantic_contracts.py (untracked; E11 prompt block narrowed 549->1145 chars)
ENV_CHANGED=NO
DB_CHANGED=NO
GOLD_CHANGED=NO
FEWSHOT_CHANGED=NO
HEAD_UNCHANGED=YES
INDEX_CLEAN=YES
TRACKED_FILES_CHANGED=0 (of 824)
REAL_API_CALLS_TOTAL=8 (budget 8)
IDENTITY_REPLAY=6/6 PASS
PROBE_INVALID=0
COMMIT=NONE
```

---

## 十、产物

- `F:/task46_e9_e11/task46_report.md`（本文件）
- `F:/task46_e9_e11/raw_results_task46.json`（8 条真实记录，含 gold/pred SQL 全文 + guard）
- `F:/task46_e9_e11/run_task46.py`（真实调用 harness，位于**仓库外**）
- `F:/task46_e9_e11/e11_guard.py`（E11 不变量检查器，纯函数）
- `F:/task46_e9_e11/phase1_audit.txt` / `phase4_e9_scan.txt` / `phase4_e9_scan.json`
- `F:/task46_e9_e11/pre_snapshot.json`（824 tracked 文件开工前 sha256）
- `backend/tests/test_task46_e11_narrowing.py` / `backend/tests/test_task46_e9_boundary.py`（离线回归测试）
