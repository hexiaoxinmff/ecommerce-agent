# ECO-SQL-Bench · 8 个稳定 Bad Case 深度归因（Task 14.2）

> 对象：跨 E1 / stability_run01 / stability_run02 / E2 四轮均失败的 8 条：
> E-0057, E-0077, E-0082, E-0083, E-0086, E-0090, E-0095, E-0097
> 基准：推荐配置（SQLGENERATOR_PROMPT_V1.1 + FEWSHOT_V1 18 条），E2 run 20260915_51396。
> 数据：Gold SQL / Pred SQL 逐字对比 + answer_slots + 真实执行列数/行数。

---

## 专项 A：输出列契约（Output Contract）—— E-0082 / E-0083 / E-0090

**共性根因**：模型 SQL 的**语义/计算基本正确**，但 **SELECT 输出列与问题要求不一致**——列数不足或遗漏字段，按 spec §D1「列数量必须可比」判错。

### E-0082（hard，ratio）
- Q：休闲零食类别占全平台销售总额的比例（百分比）
- Gold SELECT：`c.name, ROUND(SUM(oi.subtotal)*100/(...),2) AS pct` → **2 列**（name + pct）
- Pred SELECT：`ROUND(... AS percentage)` → **1 列**（遗漏 c.name）
- 执行：gold rows=1×2 列；pred rows=1×1 列 → 列数不符判错。
- 根因：问题说「请给出**分类与占比**」，但模型只输出占比列。

### E-0083（hard，ratio）
- Q：2025 Q4 家用电器占当季全部销售额比例
- Gold：`c.name, ROUND(...) AS pct`（2 列）；Pred：`ROUND(...) AS percentage`（1 列）
- 根因：同 E-0082——遗漏分类名称列。

### E-0090（extra_hard，order_analysis）
- Q：各状态高/低金额订单数（含总数结构统计）
- Gold：`status, COUNT(CASE>5000), COUNT(CASE<=5000), COUNT(*)` → **4 列**（含 total_cnt）
- Pred：`status, SUM(CASE>5000), SUM(CASE<=5000)` → **3 列**（遗漏 total_cnt 结构总计列）；且未对金额档排 cancelled（次要问题）
- 根因：问题括号注明「含取消订单的结构统计」→ 模型漏掉「总订单数」字段。

**修复方向（E4）**：Prompt 增加「Output Contract / SELECT 投影规则」：生成前先枚举问题要求返回的字段，SELECT 必须逐项覆盖；占比题通常需「分类名 + 比例」两列；结构统计题需保留总计数列。

---

## 专项 B：金额/销售口径（Metric Semantics）—— E-0077 / E-0097

**共性根因**：**商品销售金额**应使用 `order_items.subtotal`（明细口径），模型误用 `orders.total_amount`（订单实付，含折扣/运费）。

### E-0077（hard，regional_analysis）
- Q：2025 各地区**非取消订单销售额**高于平均销售额的地区
- Gold：`SUM(oi.subtotal)`（明细销售）+ `orders JOIN order_items`
- Pred：`SUM(total_amount)`（订单实付，FROM orders 未 JOIN order_items）
- 根因：金额字段选错（subtotal vs total_amount）；HH 地区销售口径 = 明细金额。

### E-0097（extra_hard，regional_analysis）
- Q：2025 各区域**商品销售金额**高于地区平均、订单笔数高于地区平均的区域
- Gold：`SUM(oi.subtotal) AS revenue` + `COUNT(DISTINCT o.id) AS orders`（JOIN order_items）
- Pred：`SUM(total_amount)` + `COUNT(*)`（未 JOIN order_items、未去重订单数）
- 根因①：金额字段选错；根因②：订单数应用 `COUNT(DISTINCT o.id)`（防止 JOIN 放大），pred 用 `COUNT(*)`。

**修复方向（E5）**：Prompt 强化金额字段选择决策表：
- 商品/类目「销售额 / 销售金额」→ `order_items.subtotal`
- 「销量 / 件数」→ `order_items.quantity`
- 「订单实付 / 客单价 / 订单金额」→ `orders.total_amount`
- 「商品标价 / 平均售价」→ `products.price`
- JOIN order_items 后计数订单必须 `COUNT(DISTINCT o.id)`。

---

## 专项 C：深嵌套/分层聚合（Nested Aggregation）—— E-0086 / E-0095

**共性根因**：多阶段聚合中**实体粒度混淆 / JOIN 放大 / 前置过滤缺失**。

### E-0086（extra_hard，user_analysis）
- Q：累计消费 > 用户平均累计消费 2 倍 且 下单 > 8 笔的用户
- Gold：`user_stats`（orders JOIN order_items，COUNT(DISTINCT o.id)=orders、COUNT(DISTINCT oi.product_id)=sku_cnt）→ 外层与 `(SELECT AVG(spent) FROM (每用户SUM) t)` 比较
- Pred：`user_stats`（users JOIN orders JOIN order_items）`COUNT(o.id)` **未去重** → 因 order_items 一对多导致 `order_count` 行数膨胀（orders 被放大），`order_count>8` 筛选失真；avg_spent 取 `AVG(total_spent)` over 全用户（粒度对，但 orders 膨胀影响 total_spent？——total_spent=SUM(total_amount) 也因多行重复求和而膨胀）
- 根因：**users→orders→order_items 多级 JOIN 后未在正确粒度去重/聚合**（COUNT/SUM 膨胀）。

### E-0095（extra_hard，time_analysis）
- Q：近30天 地区×分类组合 中销售金额高于该地区各组合平均销售金额的组合（前10），且要求「组合金额 > 30000」
- Gold：`pair_sales ... HAVING SUM(oi.subtotal) > 30000`（先过滤组合）→ 再按地区求平均组合金额 → 比较
- Pred：`region_category_sales` 无 `HAVING > 30000` 前置过滤 → 平均基准包含低额组合，选出集合不同（且结果 10 行 vs gold 9 行）
- 根因：遗漏题面条目的显式过滤阈值（HAVING>30000），导致「平均基准」口径错误。

**修复方向（E6）**：Prompt 增加「分层聚合思维约束」：复杂题先确认最终实体 → 第一层聚合并去重（DISTINCT 防放大）→ 第二层聚合（AVG over 聚合结果）→ 显式 WHERE/HAVING 前置过滤必须保留。

---

## 专项 D：分段边界（CASE Boundary）—— E-0057

### E-0057（hard，user_analysis）
- Q：按累计下单次数分三档（1-3 / 4-10 / 11+）各档用户数
- Gold：`CASE WHEN cnt <= 3 THEN '1-3单' WHEN cnt <= 10 THEN '4-10单' ELSE '11单及以上' END`（`<=` 闭区间，边界不重叠，覆盖 0…∞；cnt=0 落入 1-3单）
- Pred：`CASE WHEN order_count BETWEEN 1 AND 3 ... BETWEEN 4 AND 10 ... ELSE ...`（数值等价，但 `order_count=0` 不落入任何档——若 LEFT JOIN 保留无订单用户则 0 落 ELSE「11单及以上」→ 与 gold 的 0→'1-3单' 不一致）
- 执行：rows 数相同但分组归属不同（0 单用户档位错位）
- 根因：分区边界「下界」处理：左闭区间应从 0/正整数起点开始，`BETWEEN 1 AND 3` 使 0 落入 ELSE（错误档）。同时输出列别名与 gold 不同（order_count_group vs tier，属列 key 差异次要因素）。

**修复方向（E7）**：Prompt 增加 CASE WHEN 边界规则：区间必须覆盖全部取值域（含边界起点 0）；相邻区间不重叠（用 `<=` / `>` 或 BETWEEN 但保证起始下界 = 0）；避免未分类值落入错误的 ELSE。

---

## 汇总

| 专项 | eval | 核心根因 | 主要修复面 |
|---|---|---|---|
| A 输出列契约 | E-0082/0083/0090 | SELECT 缺列/列数不足 | Prompt Output Contract |
| B 金额口径 | E-0077/0097 | subtotal vs total_amount；COUNT 去重 | Prompt Metric Semantics |
| C 分层聚合 | E-0086/0095 | JOIN 放大 / 前置 HAVING 缺失 | Prompt 分层聚合 |
| D 分段边界 | E-0057 | CASE 边界下界未覆盖 0 | Prompt CASE Boundary |

*本归因基于 Pred SQL 与 Gold SQL 的事后对比；未修改任何测试题 / Gold / 评测规则。*