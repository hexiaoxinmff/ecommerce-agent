# Task 47：E11 25 题触发面真实验证

> 在 Task 46 已收窄的 E11 文本基础上，对 ECO-SQL-Bench v1.1 中 **E11 deterministic trigger=YES 的全部 25 题**
> 执行一次真实 Bailian 单臂验证，只验证 E11 的触发边界 / 结构约束 / 副作用 / SQL 执行 / 与 Gold 的结果关系。
>
> 边界（全部遵守）：单臂 `SQLGEN_EXTRA_RULES=E11`（进程内）/ `LLM_PROVIDER=bailian`（进程内，`.env` 仍是 `mimo`）/
> 不碰 E4/E9/E10 / 不改 DB / Gold / FEWSHOT / **每题严格 1 次、总数 == 25** / 不 commit / 不跑 100Q。

---

## 一、执行摘要

| 项 | 结果 |
|---|---|
| E11_TRIGGER_COUNT | **25** |
| REAL_API_CALLS | **25**（硬门 25） |
| PROVIDER_FAILURES | **0** |
| IDENTITY_REPLAY | **25/25 PASS**（PROBE_INVALID = 无） |
| FIXED | **1** |
| REGRESSION | **1** |
| PASS_NO_EFFECT | **18** |
| OTHER | **5** |
| GROUPBY_REGRESSION | **0** |
| SELECT_REGRESSION | **0** |
| TIMEFILTER_REGRESSION | **0** |
| OTHER_STRUCTURE_REGRESSION | **1** |
| E11_STRUCTURE_OK | **25/25** |
| E-0098 正向控制 | **PASS** |
| **E11_CONCLUSION** | **`NEEDS_NARROWING`** |

---

## 二、25 题 trigger 清单（Phase 1，完全离线）

deterministic trigger=YES：**25 题**；与 Task 46 审计输出题号集合一致 = **True**；
`TRIGGER_DEFINITION_ISSUE` = **0**（未自行修改 trigger 定义）。

| # | question_id | 排名表述 | N | gold ORDER BY | LIMIT | 窗口 | 输出列 | 判定 |
|---|---|---|---|---|---|---|---|---|
| 1 | `E-0017` | 最高的5笔 | 5 | `total_amount DESC` | 5 | False | 2 | OK_RANKING |
| 2 | `E-0031` | 最多的5个 | 5 | `cnt DESC / c.name` | 5 | False | 2 | OK_RANKING |
| 3 | `E-0034` | 最高的5款 | 5 | `p.price DESC / p.id` | 5 | False | 3 | OK_RANKING |
| 4 | `E-0037` | 最多的5个 | 5 | `product_count DESC / c.name` | 5 | False | 2 | OK_RANKING |
| 5 | `E-0042` | 最高的10个 | 10 | `revenue DESC` | 10 | False | 2 | OK_RANKING |
| 6 | `E-0045` | 最高的5个 | 5 | `avg_amount DESC / region` | 5 | False | 2 | OK_RANKING |
| 7 | `E-0048` | 最多的5个 | 5 | `order_count DESC / month` | 5 | False | 2 | OK_RANKING |
| 8 | `E-0053` | 最高的5个 | 5 | `order_count DESC / region` | 5 | False | 2 | OK_RANKING |
| 9 | `E-0054` | 最高的5个 | 5 | `avg_price DESC / c.name` | 5 | False | 2 | OK_RANKING |
| 10 | `E-0055` | 最高的5位 | 5 | `total_spent DESC / u.id` | 5 | False | 2 | OK_RANKING |
| 11 | `E-0058` | 前5 | 5 | `avg_price DESC / c.name` | 5 | False | 2 | OK_RANKING |
| 12 | `E-0059` | 最高的5款 | 5 | `sold DESC / p.id` | 5 | False | 2 | OK_RANKING |
| 13 | `E-0062` | 最高的5个 | 5 | `revenue DESC / c.name` | 5 | False | 2 | OK_RANKING |
| 14 | `E-0067` | 最高的8个 | 8 | `revenue DESC / o.region / c.name` | 8 | False | 3 | OK_RANKING |
| 15 | `E-0073` | 最高的5个 | 5 | `daily_avg_revenue DESC / c.name` | 5 | False | 2 | OK_RANKING |
| 16 | `E-0074` | 最高的3个 | 3 | `sold DESC / c.name` | 3 | False | 2 | OK_RANKING |
| 17 | `E-0076` | 最多的5个 | 5 | `order_count DESC / region` | 5 | False | 3 | OK_RANKING |
| 18 | `E-0080` | 最高的5款 | 5 | `revenue DESC / p.id` | 5 | False | 2 | OK_RANKING |
| 19 | `E-0087` | 最高的10款 | 10 | `ps.sold DESC / ps.id` | 10 | False | 3 | OK_RANKING |
| 20 | `E-0088` | 最高的5款 | 5 | `total DESC / name` | 5 | False | 4 | OK_RANKING |
| 21 | `E-0092` | 最大的是哪些 | — | `growth_pct DESC / region` | - | False | 4 | OK_RANKING |
| 22 | `E-0093` | 最高的3个 | 3 | `region / rk` | - | True | 3 | OK_RANKING |
| 23 | `E-0095` | 前10 | 10 | `ps.revenue DESC / ps.region / ps.cat_name` | 10 | False | 3 | OK_RANKING |
| 24 | `E-0096` | 最快的3个 | 3 | `mom_pct DESC / month` | 3 | True | 3 | OK_RANKING |
| 25 | `E-0098` | 最高的3款 | 3 | `cat_name / rk` | - | True | 3 | OK_RANKING |

**分类结论**：25 题 gold **全部**含 `ORDER BY` 或窗口排名；gold 最终 SELECT **全部 ≥2 列**（返回实体集合）；
标量 Top-1（gold 只 1 列）与 trigger 集合**无交集**。

> ⚠️ **审计工具自身的坑（已记录）**：`_RANK_SCALAR_ONLY_PATTERN` 会把「最多的5个…是**哪几**个」
> 误匹配成标量题（实测命中 9 题，其中 4 题是集合型 Top-N）。它在 detector 里只服务于第三个分支，
> Top-N 分支**根本不看它**，因此当前无害；但这是一个**潜在脆弱点**：一旦分支顺序调整就会误杀。
> 本任务改用**客观结构判据**（gold 输出列数）做分类，不使用该正则。

## 三、Identity Replay（25 题，先于任何真实调用）

判定口径：gold 两次 replay 的 `normalize_result` 经 `compare_results` 判等 **且** hash 与冻结 `gold_result_hash` 一致。

| question_id | replay hash | frozen hash | hash 自洽 | compare 一致 | pass |
|---|---|---|---|---|---|
| `E-0017` | `fd40b30e5271` | `fd40b30e5271` | True | True | **True** |
| `E-0031` | `92f1d4dd9496` | `92f1d4dd9496` | True | True | **True** |
| `E-0034` | `3f07dbe7e28e` | `3f07dbe7e28e` | True | True | **True** |
| `E-0037` | `64accf2a87c3` | `64accf2a87c3` | True | True | **True** |
| `E-0042` | `3455fe8cd7b0` | `3455fe8cd7b0` | True | True | **True** |
| `E-0045` | `d4cf0982a0b4` | `d4cf0982a0b4` | True | True | **True** |
| `E-0048` | `eab6d15b769b` | `eab6d15b769b` | True | True | **True** |
| `E-0053` | `62135bdb083a` | `62135bdb083a` | True | True | **True** |
| `E-0054` | `cf6d84c8ecb8` | `cf6d84c8ecb8` | True | True | **True** |
| `E-0055` | `0fe157dc71b9` | `0fe157dc71b9` | True | True | **True** |
| `E-0058` | `1653ebb10032` | `1653ebb10032` | True | True | **True** |
| `E-0059` | `c16a40884bc7` | `c16a40884bc7` | True | True | **True** |
| `E-0062` | `03c576689cf6` | `03c576689cf6` | True | True | **True** |
| `E-0067` | `eaf133a7132c` | `eaf133a7132c` | True | True | **True** |
| `E-0073` | `bc51ab9ba856` | `bc51ab9ba856` | True | True | **True** |
| `E-0074` | `45ca285fa3a2` | `45ca285fa3a2` | True | True | **True** |
| `E-0076` | `afee0c55d9c5` | `afee0c55d9c5` | True | True | **True** |
| `E-0080` | `9ea9497a7df6` | `9ea9497a7df6` | True | True | **True** |
| `E-0087` | `5e1f3fcbe23c` | `5e1f3fcbe23c` | True | True | **True** |
| `E-0088` | `1c3eaa6778ef` | `1c3eaa6778ef` | True | True | **True** |
| `E-0092` | `8eb1dc14489a` | `8eb1dc14489a` | True | True | **True** |
| `E-0093` | `893b1e99c1b1` | `893b1e99c1b1` | True | True | **True** |
| `E-0095` | `70cf5b38211e` | `70cf5b38211e` | True | True | **True** |
| `E-0096` | `95de24040f0e` | `95de24040f0e` | True | True | **True** |
| `E-0098` | `4c991746647d` | `4c991746647d` | True | True | **True** |

**25/25 PASS**，`PROBE_INVALID` = 空 ⇒ 探针可用，继续真实调用。

## 四、逐题真实结果

| # | question_id | 注入 | 结构OK | 破平键 | 结果 | 判定 | 归因 | 延迟 | calls |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `E-0017` | True | True | `id asc` | MATCH | **FIXED** | NONE | 3071 ms | 1 |
| 2 | `E-0031` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2669 ms | 1 |
| 3 | `E-0034` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2547 ms | 1 |
| 4 | `E-0037` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2582 ms | 1 |
| 5 | `E-0042` | True | True | `region asc` | MISMATCH | **OTHER** | BUSINESS_SEMANTIC | 2768 ms | 1 |
| 6 | `E-0045` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2324 ms | 1 |
| 7 | `E-0048` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2260 ms | 1 |
| 8 | `E-0053` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2463 ms | 1 |
| 9 | `E-0054` | True | True | — | MISMATCH | **OTHER** | BUSINESS_SEMANTIC | 2426 ms | 1 |
| 10 | `E-0055` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2367 ms | 1 |
| 11 | `E-0058` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 3532 ms | 1 |
| 12 | `E-0059` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2963 ms | 1 |
| 13 | `E-0062` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 3131 ms | 1 |
| 14 | `E-0067` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 4111 ms | 1 |
| 15 | `E-0073` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 4451 ms | 1 |
| 16 | `E-0074` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 3558 ms | 1 |
| 17 | `E-0076` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 2625 ms | 1 |
| 18 | `E-0080` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 3269 ms | 1 |
| 19 | `E-0087` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 4312 ms | 1 |
| 20 | `E-0088` | True | True | — | MISMATCH | **OTHER** | BUSINESS_SEMANTIC | 5451 ms | 1 |
| 21 | `E-0092` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 5176 ms | 1 |
| 22 | `E-0093` | True | True | `id asc` | EXEC_ERROR | **REGRESSION** | E11_STRUCTURE | 5401 ms | 1 |
| 23 | `E-0095` | True | True | — | MISMATCH | **OTHER** | BUSINESS_SEMANTIC | 5264 ms | 1 |
| 24 | `E-0096` | True | True | — | MISMATCH | **OTHER** | BUSINESS_SEMANTIC | 4641 ms | 1 |
| 25 | `E-0098` | True | True | — | MATCH | **PASS_NO_EFFECT** | NONE | 4614 ms | 1 |

### 4.1 完整 SQL（gold / pred 全文，不截断）

> **字段名说明（§五 合规）**：`raw_results.json` 中 SQL 全文的规范字段名按任务书 §五 为
> `full_gold_sql` / `full_pred_sql`；本 harness 原始写出的键名为 `gold_sql_full` / `pred_sql_full`。
> 收尾时已**追加等价别名**（内容逐字节相同，未删除原键），并写入顶层 `spec_field_names` 供复核。
> 25/25 题的两个规范字段均存在且非空；全文无任何 `[:400]` 截断（`grep '\[:400\]'` = 0 命中）。

**`E-0017`**　2024年实付金额最高的5笔非取消订单是哪几笔？（请给出订单ID和金额）

- GOLD：`SELECT id, total_amount FROM orders WHERE order_date >= '2024-01-01' AND order_date <= '2024-12-31' AND status != 'cancelled' ORDER BY total_amount DESC LIMIT 5`
- PRED：`SELECT o.id AS order_id, o.total_amount AS amount FROM orders o WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 4) = '2024' ORDER BY o.total_amount DESC, o.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['order_id', 'amount']`　行数：5　结果 hash：`22c33bebd95b`

**`E-0031`**　售价低于100元的商品中，款数最多的5个分类是哪些？（请给出分类名称与款数）

- GOLD：`SELECT c.name, COUNT(*) AS cnt FROM products p JOIN categories c ON c.id = p.category_id WHERE p.price < 100 GROUP BY c.id, c.name ORDER BY cnt DESC, c.name LIMIT 5`
- PRED：`SELECT c.name AS category_name, COUNT(p.id) AS product_count FROM products p JOIN categories c ON c.id = p.category_id WHERE p.price < 100 GROUP BY c.id ORDER BY product_count DESC, c.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['category_name', 'product_count']`　行数：5　结果 hash：`a6e50e9d5eab`

**`E-0034`**　在售商品中价格最高的5款商品是哪些？（请给出商品名称、价格与所属分类）

- GOLD：`SELECT p.name, p.price, c.name AS category_name FROM products p JOIN categories c ON c.id = p.category_id WHERE p.status = 'on_sale' ORDER BY p.price DESC, p.id LIMIT 5`
- PRED：`SELECT p.name AS product_name, p.price, c.name AS category_name FROM products p JOIN categories c ON c.id = p.category_id WHERE p.status = 'on_sale' ORDER BY p.price DESC, p.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['product_name', 'price', 'category_name']`　行数：5　结果 hash：`6bb544a0dd56`

**`E-0037`**　挂载商品数量最多的5个分类是哪些？（请给出分类名称与商品数量）

- GOLD：`SELECT c.name, COUNT(*) AS product_count FROM products p JOIN categories c ON c.id = p.category_id GROUP BY c.id, c.name ORDER BY product_count DESC, c.name LIMIT 5`
- PRED：`SELECT c.name AS category_name, COUNT(p.id) AS product_count FROM categories c LEFT JOIN products p ON p.category_id = c.id GROUP BY c.id ORDER BY product_count DESC, c.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['category_name', 'product_count']`　行数：5　结果 hash：`4f23cce71a6d`

**`E-0042`**　非取消订单实付销售额最高的10个收货地区是哪些？（请给出地区名称与销售额）

- GOLD：`SELECT region, ROUND(SUM(total_amount), 2) AS revenue FROM orders WHERE status != 'cancelled' GROUP BY region ORDER BY revenue DESC LIMIT 10`
- PRED：`SELECT o.region AS region_name, ROUND(SUM(oi.subtotal), 2) AS total_sales FROM orders o JOIN order_items oi ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY o.region ORDER BY total_sales DESC, o.region ASC LIMIT 10`
- 结果：`排名题集合不一致`　列：`['region_name', 'total_sales']`　行数：10　结果 hash：`76c6b1eaab03`

**`E-0045`**　非取消订单平均实付金额（客单价）最高的5个收货地区是哪些？（请给出地区名称与平均金额）

- GOLD：`SELECT region, ROUND(AVG(total_amount), 2) AS avg_amount FROM orders WHERE status != 'cancelled' GROUP BY region ORDER BY avg_amount DESC, region LIMIT 5`
- PRED：`SELECT o.region, ROUND(AVG(o.total_amount), 2) AS avg_paid_amount FROM orders o WHERE o.status != 'cancelled' GROUP BY o.region ORDER BY avg_paid_amount DESC, o.region ASC LIMIT 5`
- 结果：`MATCH`　列：`['region', 'avg_paid_amount']`　行数：5　结果 hash：`ce4cf30fd8b8`

**`E-0048`**　2026年订单数量最多的5个月份是哪几个？（请给出月份与订单数）

- GOLD：`SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS order_count FROM orders WHERE order_date >= '2026-01-01' GROUP BY month ORDER BY order_count DESC, month LIMIT 5`
- PRED：`SELECT substr(o.order_date, 1, 7) AS month, COUNT(*) AS order_count FROM orders o WHERE substr(o.order_date, 1, 4) = '2026' GROUP BY month ORDER BY order_count DESC, month ASC LIMIT 5`
- 结果：`MATCH`　列：`['month', 'order_count']`　行数：5　结果 hash：`eab6d15b769b`

**`E-0053`**　2026年7月至8月，订单数量最高的5个收货地区是哪些？（请给出地区名称与订单数量）

- GOLD：`SELECT region, COUNT(*) AS order_count FROM orders WHERE order_date >= '2026-07-01' AND order_date <= '2026-08-31' GROUP BY region ORDER BY order_count DESC, region LIMIT 5`
- PRED：`SELECT o.region, COUNT(o.id) AS order_count FROM orders o WHERE o.order_date >= '2026-07-01' AND o.order_date < '2026-09-01' GROUP BY o.region ORDER BY order_count DESC, o.region ASC LIMIT 5`
- 结果：`MATCH`　列：`['region', 'order_count']`　行数：5　结果 hash：`62135bdb083a`

**`E-0054`**　平均售价最高的5个商品分类是哪些？（请给出分类名称与平均售价）

- GOLD：`SELECT c.name, ROUND(AVG(p.price), 2) AS avg_price FROM products p JOIN categories c ON c.id = p.category_id GROUP BY c.id, c.name ORDER BY avg_price DESC, c.name LIMIT 5`
- PRED：`SELECT c.name AS category_name, ROUND(AVG(p.price), 2) AS avg_price FROM products p JOIN categories c ON c.id = p.category_id WHERE p.status = 'on_sale' GROUP BY c.id ORDER BY avg_price DESC, c.id ASC LIMIT 5`
- 结果：`排名题集合不一致`　列：`['category_name', 'avg_price']`　行数：5　结果 hash：`88113ffd78a9`

**`E-0055`**　累计消费金额最高的5位用户是哪些？（请给出用户名与累计非取消实付金额）

- GOLD：`SELECT u.username, ROUND(SUM(o.total_amount), 2) AS total_spent FROM users u JOIN orders o ON o.user_id = u.id WHERE o.status != 'cancelled' GROUP BY u.id, u.username ORDER BY total_spent DESC, u.id LIMIT 5`
- PRED：`SELECT u.username, ROUND(SUM(o.total_amount), 2) AS total_spent FROM orders o JOIN users u ON u.id = o.user_id WHERE o.status != 'cancelled' GROUP BY u.id ORDER BY total_spent DESC, u.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['username', 'total_spent']`　行数：5　结果 hash：`0fe157dc71b9`

**`E-0058`**　在售商品平均售价高于全平台商品平均售价的商品分类有哪些？（请给出分类名称与平均售价，取前5名）

- GOLD：`SELECT c.name, ROUND(AVG(p.price), 2) AS avg_price FROM products p JOIN categories c ON c.id = p.category_id WHERE p.status = 'on_sale' GROUP BY c.id, c.name HAVING AVG(p.price) > (SELECT AVG(price) FROM products) ORDER BY avg_price DESC, c.name LIMIT 5`
- PRED：`WITH cat_avg AS (SELECT c.id AS cid, c.name AS category_name, AVG(p.price) AS avg_price FROM products p JOIN categories c ON c.id = p.category_id WHERE p.status = 'on_sale' GROUP BY c.id), platform_avg AS (SELECT AVG(avg_price) AS global_avg FROM cat_avg) SELECT ca.category_name, ROUND(ca.avg_price, 2) AS avg_price FROM cat_avg ca CROSS JOIN platform_avg pa WHERE ca.avg_price > pa.global_avg ORDER BY ca.avg_price DESC, ca.cid ASC LIMIT 5`
- 结果：`MATCH`　列：`['category_name', 'avg_price']`　行数：5　结果 hash：`88113ffd78a9`

**`E-0059`**　非取消订单中销量最高的5款商品是哪些？（请给出商品名称与累计销量）

- GOLD：`SELECT p.name, SUM(oi.quantity) AS sold FROM products p JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY p.id, p.name ORDER BY sold DESC, p.id LIMIT 5`
- PRED：`SELECT p.name AS product_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id WHERE o.status != 'cancelled' GROUP BY p.id ORDER BY total_sold DESC, p.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['product_name', 'total_sold']`　行数：5　结果 hash：`1b64f52967ef`

**`E-0062`**　2025年销售金额最高的5个商品分类是哪些？（请给出分类名称与销售额）

- GOLD：`SELECT c.name, ROUND(SUM(oi.subtotal), 2) AS revenue FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' AND o.order_date >= '2025-01-01' AND o.order_date <= '2025-12-31' GROUP BY c.id, c.name ORDER BY revenue DESC, c.name LIMIT 5`
- PRED：`SELECT c.name AS category_name, ROUND(SUM(oi.subtotal), 2) AS total_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND strftime('%Y', o.order_date) = '2025' GROUP BY c.id ORDER BY total_sales DESC, c.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['category_name', 'total_sales']`　行数：5　结果 hash：`e2cda6fe433b`

**`E-0067`**　最近90天（2026年6月14日至9月12日）各地区各类别的销售金额最高的8个组合是哪些？（请给出地区、分类与金额）

- GOLD：`SELECT o.region, c.name, ROUND(SUM(oi.subtotal), 2) AS revenue FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-06-14' AND o.status != 'cancelled' GROUP BY o.region, c.name ORDER BY revenue DESC, o.region, c.name LIMIT 8`
- PRED：`SELECT o.region AS region, c.name AS category_name, ROUND(SUM(oi.subtotal), 2) AS total_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-06-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY o.region, c.id ORDER BY total_sales DESC, o.region ASC, c.id ASC LIMIT 8`
- 结果：`MATCH`　列：`['region', 'category_name', 'total_sales']`　行数：8　结果 hash：`793293216400`

**`E-0073`**　最近90天（2026年6月14日至9月12日）内，日均销售额最高的5个商品分类是哪些？（请给出分类名称与日均销售额）

- GOLD：`SELECT c.name, ROUND(SUM(oi.subtotal) * 1.0 / COUNT(DISTINCT o.order_date), 2) AS daily_avg_revenue FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-06-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY c.id, c.name ORDER BY daily_avg_revenue DESC, c.name LIMIT 5`
- PRED：`SELECT c.name AS category_name, ROUND(SUM(oi.subtotal) * 1.0 / COUNT(DISTINCT o.order_date), 2) AS daily_avg_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-06-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY c.id ORDER BY daily_avg_sales DESC, c.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['category_name', 'daily_avg_sales']`　行数：5　结果 hash：`45ef6cf335e0`

**`E-0074`**　2025年第四季度中，销量最高的3个商品分类是哪些？（请给出分类名称与销量）

- GOLD：`SELECT c.name, SUM(oi.quantity) AS sold FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2025-10-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' GROUP BY c.id, c.name ORDER BY sold DESC, c.name LIMIT 3`
- PRED：`SELECT c.name AS category_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND o.order_date >= '2025-10-01' AND o.order_date < '2026-01-01' GROUP BY c.id ORDER BY total_sold DESC, c.id ASC LIMIT 3`
- 结果：`MATCH`　列：`['category_name', 'total_sold']`　行数：3　结果 hash：`f8cebf983cc9`

**`E-0076`**　订单数量最多的5个收货地区是哪几个？它们各占订单总量的百分之几？（请给出地区、订单数与占比）

- GOLD：`SELECT region, COUNT(*) AS order_count, ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM orders), 2) AS pct FROM orders GROUP BY region ORDER BY order_count DESC, region LIMIT 5`
- PRED：`SELECT region, cnt, ROUND(cnt * 100.0 / (SELECT COUNT(*) FROM orders), 2) AS pct FROM (SELECT region, COUNT(*) AS cnt FROM orders GROUP BY region ORDER BY cnt DESC, region ASC LIMIT 5)`
- 结果：`MATCH`　列：`['region', 'cnt', 'pct']`　行数：5　结果 hash：`267f8021bd0f`

**`E-0080`**　最近90天内（2026年6月14日至9月12日），销售金额最高的5款商品是哪些？（请给出商品名称与销售额）

- GOLD：`SELECT p.name, ROUND(SUM(oi.subtotal), 2) AS revenue FROM products p JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.order_date >= '2026-06-14' AND o.status != 'cancelled' GROUP BY p.id, p.name ORDER BY revenue DESC, p.id LIMIT 5`
- PRED：`SELECT p.name AS product_name, ROUND(SUM(oi.subtotal), 2) AS total_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id WHERE o.order_date >= '2026-06-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY p.id ORDER BY total_sales DESC, p.id ASC LIMIT 5`
- 结果：`MATCH`　列：`['product_name', 'total_sales']`　行数：5　结果 hash：`cf17d4a71d4e`

**`E-0087`**　销量高于其所属叶子分类平均销量的商品中，销量最高的10款商品是哪些？（请给出商品名、分类名与销量）

- GOLD：`WITH prod_sales AS (SELECT p.id, p.name, p.category_id, c.name AS cat_name, SUM(oi.quantity) AS sold FROM products p JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY p.id) SELECT ps.name, ps.cat_name, ps.sold FROM prod_sales ps WHERE ps.sold > (SELECT AVG(d.sold) FROM (SELECT p2.id, SUM(oi2.quantity) AS sold FROM products p2 JOIN order_items oi2 ON oi2.product_id = p2.id JOIN orders o2 ON o2.id = oi2.order_id WHERE o2.status != 'cancelled' AND p2.category_id = ps.category_id GROUP BY p2.id) d) ORDER BY ps.sold DESC, ps.id LIMIT 10`
- PRED：`WITH product_sales AS (SELECT oi.product_id, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY oi.product_id), category_avg_sales AS (SELECT p.category_id, AVG(ps.total_sold) AS avg_sold FROM product_sales ps JOIN products p ON p.id = ps.product_id GROUP BY p.category_id) SELECT p.name AS product_name, c.name AS category_name, ps.total_sold FROM product_sales ps JOIN products p ON p.id = ps.product_id JOIN categories c ON c.id = p.category_id JOIN category_avg_sales cas ON p.category_id = cas.category_id AND ps.total_sold > cas.avg_sold ORDER BY ps.total_sold DESC, p.id ASC LIMIT 10`
- 结果：`MATCH`　列：`['product_name', 'category_name', 'total_sold']`　行数：10　结果 hash：`edd2dbf52ca0`

**`E-0088`**　2025年销售金额最高的5款商品中，它们上半年与下半年的销售额分别是多少？（请给出商品名、上半年额、下半年额与全年额）

- GOLD：`WITH sales AS (SELECT p.name, SUM(CASE WHEN substr(o.order_date, 6, 2) <= '06' THEN oi.subtotal ELSE 0 END) AS h1, SUM(CASE WHEN substr(o.order_date, 6, 2) >= '07' THEN oi.subtotal ELSE 0 END) AS h2, SUM(oi.subtotal) AS total FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id WHERE o.order_date >= '2025-01-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' GROUP BY p.id, p.name) SELECT name, ROUND(h1, 2) AS first_half, ROUND(h2, 2) AS second_half, ROUND(total, 2) AS total FROM sales ORDER BY total DESC, name LIMIT 5`
- PRED：`WITH top5 AS ( SELECT p.id, p.name, SUM(oi.subtotal) AS total_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 4) = '2025' GROUP BY p.id ORDER BY total_sales DESC, p.id ASC LIMIT 5 ) SELECT t.name AS product_name, ROUND(SUM(CASE WHEN substr(o.order_date, 5, 2) <= '06' THEN oi.subtotal ELSE 0 END), 2) AS h1_sales, ROUND(SUM(CASE WHEN substr(o.order_date, 5, 2) > '06' THEN oi.subtotal ELSE 0 END), 2) AS h2_sales, ROUND(SUM(oi.subtotal), 2) AS full_year_sales FROM top5 t JOIN order_items oi ON oi.product_id = t.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' AND substr(o.order_date, 1, 4) = '2025' GROUP BY t.id`
- 结果：`排名题集合不一致`　列：`['product_name', 'h1_sales', 'h2_sales', 'full_year_sales']`　行数：5　结果 hash：`1acac8dd1373`

**`E-0092`**　2025年下半年实付销售额高于上半年、且增长幅度最大的是哪些收货地区？（请给出地区、上半年额、下半年额与增长百分比）

- GOLD：`WITH region_sales AS (SELECT o.region, SUM(CASE WHEN substr(o.order_date, 6, 2) <= '06' THEN o.total_amount ELSE 0 END) AS h1, SUM(CASE WHEN substr(o.order_date, 6, 2) >= '07' THEN o.total_amount ELSE 0 END) AS h2 FROM orders o WHERE o.order_date >= '2025-01-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' GROUP BY o.region) SELECT region, ROUND(h1, 2) AS first_half, ROUND(h2, 2) AS second_half, ROUND((h2 - h1) * 100.0 / h1, 2) AS growth_pct FROM region_sales WHERE h2 > h1 ORDER BY growth_pct DESC, region`
- PRED：`WITH h1 AS (SELECT region, ROUND(SUM(total_amount), 2) AS sales FROM orders WHERE status != 'cancelled' AND order_date >= '2025-01-01' AND order_date < '2025-07-01' GROUP BY region), h2 AS (SELECT region, ROUND(SUM(total_amount), 2) AS sales FROM orders WHERE status != 'cancelled' AND order_date >= '2025-07-01' AND order_date < '2026-01-01' GROUP BY region) SELECT h2.region, h1.sales AS first_half_sales, h2.sales AS second_half_sales, ROUND((h2.sales - h1.sales) * 100.0 / NULLIF(h1.sales, 0), 2) AS growth_percentage FROM h1 JOIN h2 ON h1.region = h2.region WHERE h2.sales > h1.sales ORDER BY growth_percentage DESC, h2.region ASC`
- 结果：`MATCH`　列：`['region', 'first_half_sales', 'second_half_sales', 'growth_percentage']`　行数：15　结果 hash：`2899fc717a08`

**`E-0093`**　2025年各收货地区中，销售金额最高的3个商品分类分别是哪些？（请给出地区、分类与销售额，按地区与名次排列）

- GOLD：`WITH region_cat AS (SELECT o.region, c.name AS cat_name, SUM(oi.subtotal) AS revenue FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2025-01-01' AND o.order_date <= '2025-12-31' AND o.status != 'cancelled' GROUP BY o.region, c.id, c.name), ranked AS (SELECT region, cat_name, revenue, ROW_NUMBER() OVER (PARTITION BY region ORDER BY revenue DESC) AS rk FROM region_cat) SELECT region, cat_name, ROUND(revenue, 2) AS revenue FROM ranked WHERE rk <= 3 ORDER BY region, rk`
- PRED：`WITH region_category_sales AS (SELECT o.region, c.name AS category_name, SUM(oi.subtotal) AS total_sales FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND o.order_date LIKE '2025%' GROUP BY o.region, c.id), ranked AS (SELECT region, category_name, total_sales, ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC) AS rn FROM region_category_sales c JOIN categories cat ON c.category_name = cat.name) SELECT region, category_name, ROUND(total_sales, 2) AS total_sales FROM ranked WHERE rn <= 3 ORDER BY region, rn`
- 结果：`SQLExecutionDatabaseError: SQL 执行失败: no such column: c.id`　列：`None`　行数：None　结果 hash：`None`

**`E-0095`**　最近30天（2026年8月14日至9月12日）中，有哪些地区-分类组合的销售金额高于30000元、且高于该地区各组合的平均销售金额？（请给出地区、分类与销售额，取前10）

- GOLD：`WITH pair_sales AS (SELECT o.region, c.name AS cat_name, SUM(oi.subtotal) AS revenue FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-08-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY o.region, c.id, c.name HAVING SUM(oi.subtotal) > 30000) SELECT ps.region, ps.cat_name, ROUND(ps.revenue, 2) AS revenue FROM pair_sales ps WHERE ps.revenue > (SELECT AVG(t.avg_rev) FROM (SELECT region, AVG(revenue) AS avg_rev FROM pair_sales GROUP BY region) t WHERE t.region = ps.region) ORDER BY ps.revenue DESC, ps.region, ps.cat_name LIMIT 10`
- PRED：`WITH region_cat_sales AS (SELECT o.region, c.name AS category_name, SUM(oi.subtotal) AS total_sales FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.order_date >= '2026-08-14' AND o.order_date <= '2026-09-12' AND o.status != 'cancelled' GROUP BY o.region, c.id), avg_sales AS (SELECT region, AVG(total_sales) AS avg_sales FROM region_cat_sales GROUP BY region) SELECT rcs.region, rcs.category_name, ROUND(rcs.total_sales, 2) AS total_sales FROM region_cat_sales rcs JOIN avg_sales avs ON rcs.region = avs.region WHERE rcs.total_sales > 30000 AND rcs.total_sales > avs.avg_sales ORDER BY rcs.total_sales DESC, rcs.region ASC, rcs.category_name ASC LIMIT 10`
- 结果：`结果集合不一致`　列：`['region', 'category_name', 'total_sales']`　行数：10　结果 hash：`5dc773916f0b`

**`E-0096`**　2025年环比增速最快的3个月份是哪几个？（请给出月份、当月销售额与环比增速百分比）

- GOLD：`WITH monthly AS (SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS revenue FROM orders WHERE order_date >= '2025-01-01' AND order_date <= '2025-12-31' AND status != 'cancelled' GROUP BY month), with_prev AS (SELECT month, revenue, LAG(revenue) OVER (ORDER BY month) AS prev_rev FROM monthly) SELECT month, ROUND(revenue, 2) AS revenue, ROUND((revenue - prev_rev) * 100.0 / prev_rev, 2) AS mom_pct FROM with_prev WHERE prev_rev IS NOT NULL ORDER BY mom_pct DESC, month LIMIT 3`
- PRED：`WITH monthly_sales AS (SELECT substr(o.order_date, 1, 7) AS sale_month, ROUND(SUM(oi.subtotal), 2) AS total_sales FROM orders o JOIN order_items oi ON o.id = oi.order_id WHERE o.status != 'cancelled' AND o.order_date LIKE '2025-%' GROUP BY substr(o.order_date, 1, 7)) SELECT m.sale_month, m.total_sales, CASE WHEN LAG(m.total_sales) OVER (ORDER BY m.sale_month) IS NULL OR LAG(m.total_sales) OVER (ORDER BY m.sale_month) = 0 THEN NULL ELSE ROUND((m.total_sales - LAG(m.total_sales) OVER (ORDER BY m.sale_month)) * 100.0 / LAG(m.total_sales) OVER (ORDER BY m.sale_month), 2) END AS mom_growth_pct FROM monthly_sales m ORDER BY mom_growth_pct DESC NULLS LAST LIMIT 3`
- 结果：`排名题集合不一致`　列：`['sale_month', 'total_sales', 'mom_growth_pct']`　行数：3　结果 hash：`a7df3e8fc0b1`

**`E-0098`**　每个商品分类中，销量最高的3款商品分别是哪些？（请给出分类、商品名与销量；仅统计销量超过50的商品）

- GOLD：`WITH cat_prod AS (SELECT c.name AS cat_name, p.name AS prod_name, p.id AS prod_id, SUM(oi.quantity) AS sold FROM categories c JOIN products p ON p.category_id = c.id JOIN order_items oi ON oi.product_id = p.id JOIN orders o ON o.id = oi.order_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id, p.name HAVING SUM(oi.quantity) > 50), ranked AS (SELECT cat_name, prod_name, sold, ROW_NUMBER() OVER (PARTITION BY cat_name ORDER BY sold DESC, prod_id) AS rk FROM cat_prod) SELECT cat_name, prod_name, sold AS sold_qty FROM ranked WHERE rk <= 3 ORDER BY cat_name, rk`
- PRED：`WITH category_product_sales AS (SELECT c.id AS category_id, p.id AS product_id, p.name AS product_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id HAVING total_sold > 50), ranked_products AS (SELECT category_id, product_name, total_sold, ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY total_sold DESC, product_id ASC) AS rn FROM category_product_sales) SELECT c.name AS category_name, rp.product_name, rp.total_sold FROM ranked_products rp JOIN categories c ON c.id = rp.category_id WHERE rp.rn <= 3`
- 结果：`MATCH`　列：`['category_name', 'product_name', 'total_sold']`　行数：66　结果 hash：`1e1333436482`

## 五、E11 AST / 结构检查（A~K）

检查器：`F:/task47_e11_trigger_validation/e11_structure.py`（纯函数，真实运行与离线复算**共用同一份**）。
离线自检 14/14 通过（`phase3_checker_selftest.txt`），含 4 类**真实假阳性形态**的回归守卫。

### 5.1 判据设计（含本次实测修正）

| 检查 | 判据 | 为什么这样设计 |
|---|---|---|
| **G** 只在 ORDER BY 增破平键 | 破平键 = **排名子句的尾部键数增量**（按子句逐一比键数） | 用键字符串比对会因**表限定符**（`o.total_amount` vs `total_amount`）与**别名差异**（`category_name` vs `cat_name`）误报 |
| **G** 排名子句定义 | 最外层 ORDER BY + **排名函数**（ROW_NUMBER/RANK/DENSE_RANK）的窗口 ORDER BY | `LAG(...) OVER (ORDER BY month)` 的窗口排序不是排名排序（E-0096 实测误报） |
| **H** 破平键在末尾 | 尾部切片按构造即在末尾，仍显式复核 | — |
| **I** 用业务主键/唯一标识 | 解析后仍是**裸列**（非聚合/表达式） | — |
| **J** 破平键进 SELECT | 最外层 SELECT 的**裸列输出**中 ID 列**数量**增加 | 只数裸列：`COUNT(p.id)` 是计数不是输出 ID（E-0031/E-0037/E-0053 实测误报）；按数量：避免 `id` vs `order_id` 命名差异 |
| **K** 破平键进 GROUP BY | GROUP BY **键数增加** **且**新增了主键列 | 只看「主键列集合变化」会把函数依赖替换误报（E-0067：`GROUP BY o.region, c.id` vs gold `c.name` 同粒度） |
| **C** 时间过滤 | 两侧**都有**日期谓词且**语义不等价**（用 DB 探针比较命中的 `order_date` 集合） | 语法比较会把 `substr(order_date,1,4)='2026'` 与年区间误判成改写 |

### 5.2 逐题结果（A~K）

| question_id | A列数 | B粒度 | C改写 | D JOIN | E聚合 | F LIMIT | G破平键 | H末尾 | J SELECT | K GROUPBY | **结构OK** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `E-0017` | 2/2 | ✓ | ✗ | ✗ | ✗ | ✗ | `id asc` | ✓ | — | — | **True** |
| `E-0031` | 2/2 | ✓ | ✗ | ✗ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0034` | 3/3 | ✓ | ✗ | ✗ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0037` | 2/2 | ✓ | ✗ | ✓ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0042` | 2/2 | ✓ | ✗ | ✓ | ✓ | ✗ | `region asc` | ✓ | — | — | **True** |
| `E-0045` | 2/2 | ✓ | ✗ | ✗ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0048` | 2/2 | ✓ | ✗ | ✗ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0053` | 2/2 | ✓ | ✗ | ✗ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0054` | 2/2 | ✓ | ✗ | ✗ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0055` | 2/2 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0058` | 2/2 | ✓ | ✗ | ✗ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0059` | 2/2 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0062` | 2/2 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0067` | 3/3 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0073` | 2/2 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0074` | 2/2 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0076` | 3/3 | ✓ | ✗ | ✗ | ✓ | ✓ | — | ✓ | — | — | **True** |
| `E-0080` | 2/2 | ✓ | ✗ | ✓ | ✗ | ✗ | — | ✓ | — | — | **True** |
| `E-0087` | 3/3 | ✓ | ✗ | ✓ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0088` | 4/4 | ✓ | ✗ | ✓ | ✓ | ✓ | — | ✓ | — | — | **True** |
| `E-0092` | 4/4 | ✓ | ✗ | ✓ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0093` | 3/3 | ✓ | ✗ | ✓ | ✗ | ✗ | `id asc` | ✓ | — | — | **True** |
| `E-0095` | 3/3 | ✓ | ✗ | ✓ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0096` | 3/3 | ✓ | ✗ | ✓ | ✓ | ✗ | — | ✓ | — | — | **True** |
| `E-0098` | 3/3 | ✓ | ✗ | ✓ | ✓ | ✗ | — | ✓ | — | — | **True** |

（D/E/F 列标 ✓ 表示「**相对 gold 有差异**」——这些属 `NON_E11_STRUCTURAL_DIFFS`，用于归因，
**不计入** `E11_STRUCTURE_OK`；C 列标 ✓ 表示「未改写」，是**好事**。）

**E11_STRUCTURE_OK = 25/25**（`E-0017,E-0031,E-0034,E-0037,E-0042,E-0045,E-0048,E-0053,E-0054,E-0055,E-0058,E-0059,E-0062,E-0067,E-0073,E-0074,E-0076,E-0080,E-0087,E-0088,E-0092,E-0093,E-0095,E-0096,E-0098` 全部通过四项不变量）。

### 5.3 破平键采纳率（规则是否被模型执行）

- pred 的排名子句末尾**是标识列**（即写出了破平键）的题：**21/25**
- 未写出的：**4 题**（`E-0048`, `E-0076`, `E-0088`, `E-0096`）

| 未写出的题 | 结果 | 说明 |
|---|---|---|
| `E-0048` | MATCH | pred 的排名子句末尾是 `SUBSTRING(order_date,1,7)`——**是标识列但为日期表达式**，检查器要求「解析后仍是裸列」故判为未写出；实际已具备确定性排序键 |
| `E-0076` | MATCH | pred **完全没有排名 ORDER BY**（gold 有 `ORDER BY order_count DESC, region`） |
| `E-0088` | MISMATCH | pred 的 CTE 内有破平键，但**最外层丢了 ORDER BY**（gold 有） |
| `E-0096` | MISMATCH | pred 的排名子句只有 `mom_growth_pct` 一个键，未追加破平键 |

> 注：`E-0048` 属**判据的保守性**（日期表达式不算裸列），不是模型漏写；其余 3 题确为未写破平键，
> 其中 `E-0076` / `E-0096` 的结果仍与 gold 一致（gold 的键数也少），`E-0088` 的失败另有原因（半年切分 off-by-one）。

## 六、GROUP BY 副作用（`E11_GROUPBY_REGRESSION`）

**0 条**。判据：GROUP BY 键数增加 **且** 新增主键列。

无。

**对照 Task 45 的真实回归**（同一判据必须能检出）：

| 样本 | pred GROUP BY | 键数 pred/gold | 新增主键 | 检出 |
|---|---|---|---|---|
| Task45 `E-0042` ON | `GROUP BY o.id, o.region` | 2 / 1 | `['id']` | **✓ 检出** |
| Task46 `E-0042` ON | `GROUP BY o.region` | 1 / 1 | `[]` | ✓ 未误报 |
| 本轮 `E-0067` | `GROUP BY o.region, c.id` | 2 / 2 | `[]`（函数依赖替换） | ✓ 未误报 |

## 七、SELECT 副作用（`E11_SELECT_REGRESSION`）

**0 条**。判据：最外层 SELECT 的**裸列** ID 列数量增加。

无。25 题的输出列数均与 gold 一致，且**没有**任何题目因为破平键而多输出实体 ID。

**对照合成负例**：`SELECT …, o.id`（破平键进 SELECT）在自检中被正确检出（`J=['id']`，结构 OK=False）。

## 八、时间过滤副作用（`E11_TIMEFILTER_REGRESSION`）

**0 条**。判据：两侧都有日期谓词且**语义不等价**（DB 探针比较命中的 `order_date` 集合）。

| 分类 | 数量 | 题号 | 是否计入 E11 | 理由 |
|---|---|---|---|---|
| **改写**（两侧都有、语义不同） | **0** | — | ✅ 计入 | 与 E-0074 回归形态一致 |
| 缺失（gold 有、pred 完全没有） | 2 | `E-0093`, `E-0096` | ❌ 不计入 | 属**生成缺失**；E11 契约只谈排序 |
| 新增（pred 有、gold 没有） | 0 | — | ❌ 不计入 | pred 自行加过滤 |

**对照 Task 45 的真实回归**：`E-0074` 的 `substr(order_date,1,7)='2025-10'` vs gold 的 Q4 区间
在自检中被正确检出（`C_date_rewritten=True`，结构 OK=False）⇒ 判据非空有效。

## 九、E-0098 正向控制

| 检查项 | 期望 | 实际 | 结果 |
|---|---|---|---|
| E11 injected | TRUE | True | PASS |
| ORDER BY 含稳定 tie-breaker | TRUE | True | PASS |
| 不得新增 SELECT 列 | 无新增 ID | `[]` | PASS |
| 不得新增 GROUP BY 列 | 无新增主键 | `[]` | PASS |
| 最终 result == Gold | TRUE | True | PASS |

- PRED：`WITH category_product_sales AS (SELECT c.id AS category_id, p.id AS product_id, p.name AS product_name, SUM(oi.quantity) AS total_sold FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' GROUP BY c.id, p.id HAVING total_sold > 50), ranked_products AS (SELECT category_id, product_name, total_sold, ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY total_sold DESC, product_id ASC) AS rn FROM category_product_sales) SELECT c.name AS category_name, rp.product_name, rp.total_sold FROM ranked_products rp JOIN categories c ON c.id = rp.category_id WHERE rp.rn <= 3`
- 排名子句（pred）：`[['SUM(oi.quantity) desc', 'p.id asc']]` ⇒ 末尾键 `p.id asc` 即破平键，位置正确。
- 排名子句（gold）：`[['c.name asc', 'ROW_NUMBER() OVER (PARTITION BY cat_name ORDER BY sold DESC, prod_id) asc'], ['SUM(oi.quantity) desc', 'p.id asc']]` ⇒ gold 本身也有 `p.id`，故 `G_tiebreak_keys`（**相对 gold 的新增**）为空 —— 这是正确的：
  E11 在此题的作用是「让模型**保留/写出** gold 已有的破平键」，不是「多出一个 gold 没有的键」。

**正向控制结论：5/5 项全部 PASS。**

## 十、失败归因（不错误归因）

| FAILURE_CAUSE | 数量 | 题号 |
|---|---|---|
| `NONE` | 19 | `E-0017`, `E-0031`, `E-0034`, `E-0037`, `E-0045`, `E-0048`, `E-0053`, `E-0055`, `E-0058`, `E-0059`, `E-0062`, `E-0067`, `E-0073`, `E-0074`, `E-0076`, `E-0080`, `E-0087`, `E-0092`, `E-0098` |
| `E11_STRUCTURE` | 1 | `E-0093` |
| `BUSINESS_SEMANTIC` | 5 | `E-0042`, `E-0054`, `E-0088`, `E-0095`, `E-0096` |

### 10.1 唯一的 E11 归因失败：`E-0093`

- 现象：`SQLExecutionDatabaseError: SQL 执行失败: no such column: c.id`
- PRED：`WITH region_category_sales AS (SELECT o.region, c.name AS category_name, SUM(oi.subtotal) AS total_sales FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id JOIN categories c ON c.id = p.category_id WHERE o.status != 'cancelled' AND o.order_date LIKE '2025%' GROUP BY o.region, c.id), ranked AS (SELECT region, category_name, total_sales, ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC) AS rn FROM region_category_sales c JOIN categories cat ON c.category_name = cat.name) SELECT region, category_name, ROUND(total_sales, 2) AS total_sales FROM ranked WHERE rn <= 3 ORDER BY region, rn`
- 关键事实：`c.id` **只出现在破平键位置**（`ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC, c.id ASC)`），
  而该 CTE 里的别名 `c` 指向 `region_category_sales`（**没有 `id` 列**）⇒ 破平键引用了不存在的列。
- **机制级证据（剥离探针）**：把新增的尾部破平键删掉后，同一条 SQL **可以正常执行**：
  - `strip_changed_sql = True`
  - `stripped_executes = True`（返回 45 行）
  - stripped SQL：`WITH region_category_sales AS (SELECT o.region, c.name AS category_name, SUM(oi.subtotal) AS total_sales FROM orders AS o JOIN order_items AS oi ON o.id = oi.order_id JOIN products AS p ON p.id = oi.product_id JOIN categories AS c ON c.id = p.category_id WHERE o.status <> 'cancelled' AND o.order_date LIKE '2025%' GROUP BY o.region, c.id), ranked AS (SELECT region, category_name, total_sales, ROW_NUMBER() OVER (PARTITION BY region ORDER BY total_sales DESC) AS rn FROM region_category_sales AS c JOIN categories AS cat ON c.category_name = cat.name) SELECT region, category_name, ROUND(total_sales, 2) AS total_sales FROM ranked WHERE rn <= 3 ORDER BY region, rn`
- ⇒ 判定 `REGRESSION`，`FAILURE_CAUSE = E11_STRUCTURE`。这是**文本级因果链**，不是猜测。

### 10.2 明确**不**归因给 E11 的失败

| 题号 | 现象 | E11 是否改变相关结构 | 归因 |
|---|---|---|---|
| `E-0042` | 排名题集合不一致 | 否（`E11_STRUCTURE_OK=True`，破平键 `['region asc']`） | `BUSINESS_SEMANTIC` |
| `E-0054` | 排名题集合不一致 | 否（`E11_STRUCTURE_OK=True`，破平键 `无`） | `BUSINESS_SEMANTIC` |
| `E-0088` | 排名题集合不一致 | 否（`E11_STRUCTURE_OK=True`，破平键 `无`） | `BUSINESS_SEMANTIC` |
| `E-0095` | 结果集合不一致 | 否（`E11_STRUCTURE_OK=True`，破平键 `无`） | `BUSINESS_SEMANTIC` |
| `E-0096` | 排名题集合不一致 | 否（`E11_STRUCTURE_OK=True`，破平键 `无`） | `BUSINESS_SEMANTIC` |

特别是 `E-0042`：pred 用 `SUM(oi.subtotal)` 而 gold 用 `SUM(total_amount)` ⇒ **`E11_EFFECT = NONE`（就该项而言）**，
`FAILURE_CAUSE = BUSINESS_SEMANTIC`。破平键 `region asc` 只出现在 ORDER BY，GROUP BY 干净。
**不得写成 E11_REGRESSION。**

## 十一、API call count 与延迟

| 项 | 值 |
|---|---|
| Provider | `bailian` / `qwen3.7-flash-2026-07-15`（类 `BailianProvider`） |
| REAL_API_CALLS | **25** |
| 硬门 | 25 |
| 是否超限 | False |
| 每题 ≤ 1 次 | **True**（最大 `api_call_count` = 1） |
| PROVIDER_FAILURES | **0** |

**禁止项核查（AST，非字符串包含）**：

- `extra_body={'enable_thinking': False}` 值节点类型 = `Constant`，是字面量 False = **True**
- 被禁关键字参数 `max_tokens` / `thinking_budget` / `reasoning` = `[]`（空 = 无）
- 被禁 dict 键 `reasoning` = `[]`（空 = 无）
- 网络重试：`_NETWORK_RETRY_DELAYS_SECONDS` 在 harness 内置空（**仅内存**）

> ⚠️ 这里刻意**不用** `"max_tokens" in source` 这类字符串判据：`bailian.py` 的注释里就写着
> 「也不传 max_tokens / thinking_budget / 任何额外 reasoning 参数」⇒ 字符串判据必然误命中。

| 统计量 | 值（ms） |
|---|---|
| n | 25 |
| mean | 3519.01 |
| p50（`sorted[n//2]`，非插值） | 3131.41 |
| min / max | 2259.87 / 5451.03 |

> 延迟不用于任何结论。

## 十二、隔离检查

| 项 | 结果 |
|---|---|
| HEAD 不变 | **True**（`6c5f51c1d25c`） |
| index 不变 | **True**（staged = 0 个） |
| tracked 文件 sha256（开工前 vs 结束） | **0 个变化**（共 824 个） |
| 冻结物（benchmark / fewshot / db / .env） | **0 个变化** |
| `.env` 的 `LLM_PROVIDER` | 仍为 `mimo` |
| E4 / E9 / E10 | 未打开（`SQLGEN_EXTRA_RULES` 仅进程内设为 `E11`） |
| Task37 / Task38 / Task39-L 原有改动 | 保持不变（未触碰） |
| Task46 的 `semantic_contracts.py` / `test_task44_semantic_rules.py` | **未删除、未修改** |
| commit | **无** |

**本轮新增文件（全部在仓库外）**：

```
F:/task47_e11_trigger_validation/
  snapshot.py                    tracked 文件 sha256 快照（git ls-files -z）
  pre_snapshot.json              开工前 824 个 tracked 文件的 sha256
  phase1_trigger_list.py/.txt/.json    25 题固定 + 分类 + 与 Task46 交叉核对
  phase2_identity_replay.py/.txt/.json 25 题 Gold replay 探针
  e11_structure.py               E11 结构检查器（纯函数）
  phase3_checker_selftest.py/.txt      检查器离线自检（14 例，含 4 类假阳性回归守卫）
  task47_judge.py                归因与判定（真实运行与离线复算共用）
  run_task47.py                  真实调用 harness
  recompute_structure.py         判据修正后对已保存 SQL 的离线复算（0 次 API）
  raw_results.json               25 条真实记录（含 gold/pred SQL 全文 + 结构检查）
  run_stdout.txt                 真实运行日志
  task47_report.md               本报告
```

**仓库内新增**：**无**（本任务不修改任何仓库内文件）。

## 十三、限制

1. **单臂无 OFF 基线**：25 次全部是 `E11_ON`。因此「E11 前后」的结构增量只能用 **gold 作为参照**，
   不能直接观测「不开 E11 会写成什么」。凡相对 gold 的差异都可能是模型自身波动 ⇒ 因此把
   `NON_E11_STRUCTURAL_DIFFS` 与 E11 违规**严格分离**。
2. **n=1/题**：每题只采样一次，不能排除采样噪声；本报告不宣称任何跨题普遍结论。
3. **结构检查器看不见语义有效性**：`E-0093` 的破平键 `c.id` 在 AST 上是**合法裸列**，
   四项结构不变量**全部通过**（`E11_STRUCTURE_OK=True`），但执行时 `no such column: c.id`。
   该类失败只能靠**执行/剥离探针**发现 ⇒ 报告里单列 `OTHER_STRUCTURE_REGRESSION`。
4. **日期语义探针只覆盖 `order_date`**：探针用 `SELECT DISTINCT order_date FROM orders WHERE …` 比较，
   因此只能判定**涉及 `order_date` 的谓词**是否等价；对其它时间字段（如 `sale_month`）退化为语法比较。
5. **`GROUP BY` 键数判据是必要条件而非充分条件**：键数不变但语义粒度变化的构造（如把分组键换成
   无关列）不会被检出。本轮 25 题未出现该形态。
6. **不计算综合分**：本报告只给逐条判定与计数，不给人均准确率、不给人为加权。

## 十四、下一步建议

### 14.1 E11 结论等级：`NEEDS_NARROWING`

判定依据（任务书 §十二 B/C）：出现了可复现的 E11 归因结构回归。

### 14.2 关于 `READY_FOR_100Q` 的一个必要说明

任务书 §十二 A 的条件是「无 E11 structural regression」。本轮 `GROUPBY / SELECT / TIMEFILTER` 三类
**均为 0**，但出现了**第 4 类**：`E-0093` 的破平键引用了不存在的列导致 SQL 无法执行。
该条满足「E11 结构确实发生变化 + 产生结果退化」，因此按 §八 记为 `REGRESSION`。

**因此严格按字面条件，E11 尚未达到 `READY_FOR_100Q`。** 但需要区分两类回归的严重性：

| 回归类型 | 本轮数量 | 性质 | 修复路径 |
|---|---|---|---|
| GROUP BY 粒度破坏 | 0 | Task 45 已观测，Task 46 收窄后消失 | 已被措辞覆盖 |
| SELECT 契约破坏 | 0 | 未观测到 | — |
| 时间过滤改写 | 0 | 未观测到 | — |
| **破平键引用无效列** | **1** | **新增形态**：破平键语义正确但**作用域错误**（用了 CTE 别名去引基表主键） | 措辞需补一条：破平键必须引用**当前查询块可见**的列 |

### 14.3 建议的下一步（按优先级）

1. **先补一条 E11 措辞**（最小改动）：在禁止项里增加
   「破平键必须是**当前 SELECT / FROM 中可见**的列；不得引用未出现在本查询块 `FROM`/`JOIN` 里的表或 CTE 不存在的列」。
   然后用**同样的 25 题**再跑一次单臂验证（25 次调用），确认该类回归消失。
2. **再考虑 100Q**：只有在 25 题复验中 `OTHER_STRUCTURE_REGRESSION = 0` 之后，
   才具备 §十二 A 的字面条件。100Q 规模约 200+ 次调用，需单独批预算。
3. **保留正向控制**：任何后续 E11 实验都必须继续包含 `E-0098`，它是唯一能证明
   「规则既被触发又没破坏结构」的锚点。
4. **不建议**把 E11 转为生产默认：本任务未改变任何默认开关，E4/E9/E10/E11 仍全部 OFF。

---

## 十五、固定字段输出

```
TASK47=COMPLETE
E11_TRIGGER_COUNT=25
REAL_API_CALLS=25
IDENTITY_REPLAY=25/25 PASS
FIXED=1
REGRESSION=1
PASS_NO_EFFECT=18
PROVIDER_FAILURES=0
GROUPBY_REGRESSION=0
SELECT_REGRESSION=0
TIMEFILTER_REGRESSION=0
OTHER_STRUCTURE_REGRESSION=1
E11_STRUCTURE_OK=25/25
E0098=PASS
E11_CONCLUSION=NEEDS_NARROWING
PROD_FILES_CHANGED=NONE
NEW_UNTRACKED_FILES=1 (in-repo): reports/task47_e11_trigger_validation.md (report copy); harness files under F:/task47_e11_trigger_validation/
OTHER_COUNT=5
TRIGGER_DEFINITION_ISSUE=0
E4_DEFAULT=OFF
E9_DEFAULT=OFF
E10_DEFAULT=OFF
E11_DEFAULT=OFF
HEAD_UNCHANGED=YES
INDEX_CLEAN=YES
ENV_CHANGED=NO
DB_CHANGED=NO
GOLD_CHANGED=NO
FEWSHOT_CHANGED=NO
COMMIT=NONE
```
