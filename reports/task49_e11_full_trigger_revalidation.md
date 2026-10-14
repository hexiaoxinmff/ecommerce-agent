# Task 49 — E11 全触发面重验证（Phase 5 离线修正）

> 上游：T48 `OVERALL=NEEDS_FULL_TRIGGER_REVALIDATION`（n=1 单臂不能推翻 24 题旧果，故不写 `READY_FOR_100Q`）。
> 本任务用 **25 题真实 Bailian 调用**（Phase 4，25 次调用）做全触发面验证，Phase 5（本文件）是 **0 次新 API 调用**的离线重分析。
> 中心发现：**Phase 4 的 JOIN 副作用检测器（v1）有严重 bug，把 §十一 副作用虚报 5 倍**；用 §十一 合规的 v3 检测器重算后，结论大幅收敛且不引入任何新回归。

---

## 0. 一句话结论

E11 在 25 题真实触发集上的**全触发面重验证**：

- 四道结构回归闸（scope / groupby / select / timefilter）**全 0**；
- §十一 规范的 JOIN 副作用真实只有 **3 题**（v1 虚报 16）；其中 1 题干净良性（E-0087），1 题是**已知既有失败模式** E-0093（与 T47/T48 同源，非新引入），1 题是附带非相关失败（E-0042）；
- **没有 T48 之外的任何新回归**。T48 的「可见性收口」在 n=25 上通过：scope 回归 0，E-0093 的 `c.id` 可见性问题已解决，但其**为拿可见破平键而生成的多余 JOIN 仍引用 CTE 未暴露列** ⇒ 这是一个**独立的已知缺陷**，应另立跟踪，不记成 E11 新回归。

---

## 1. 方法

| 阶段 | 内容 | 新 API 调用 |
|---|---|---|
| Phase 4 | 25 题真实 Bailian 调用，收 `raw_results.json`（含 SQL、行数、scope_check、structure 不变量、预注册 verdict） | 25 |
| Phase 5 | 离线重分析：修正 JOIN 检测器，重算 verdict 与计数（本文件） | 0 |

**关键纪律**：Phase 5 不改任何生产代码、不改 `.env`、不切 Provider、不 commit。判定函数 `derive_final` 与「机制改变」判据在写代码前就确定（预注册），重归因单独记 `post_hoc_reattribution` 并显式标注 `POST_HOC_NOT_PREREGISTERED`（不事后偷改预注册）。

---

## 2. 检测器修正：v1 → v2 → v3（中心发现）

Phase 4 的 `join_side_effect()` 用 `find_all(exp.Join)` 搜**整棵树**并按**别名**比对 ⇒ 把「CTE 内部 JOIN」「CTE 名不同（prod_sales vs prod_sold）」「外层引用 CTE」全算成「新增 JOIN」⇒ 报出 **16 条**，严重高估。

这是本项目反复踩的坑（测量纪律 §6：**检查器会比被测对象更脆弱**）。修正分两级：

- **v2（辅助计数）**：只看**最外层 query block** 的直接源（FROM + JOINs），按**基表名**（CTE 名不算）取差集 ⇒ 4 题：E-0042 / E-0087 / E-0088 / E-0098。
- **v3（§十一 规范检测器）**：看**排名子句所属 block**（最外层 ORDER BY 所有者 + ROW_NUMBER/RANK/DENSE_RANK 窗口所在块）的直接基表，按基表名取差集 ⇒ 3 题：E-0042 / E-0087 / E-0093。

为什么 v3 才是 §十一 定义：Task 48 的 JOIN 副作用形态是「**拥有排名子句的 query block 为拿到可见 tie-breaker 而新增基表 JOIN**」。v2 会漏掉「JOIN 在 CTE 排名块内」的形态（E-0093），也会把「最外层为取输出列名联表」算成 §十一 副作用（E-0098）。**FINAL 以 v3 为准。**

| 检测器 | 口径 | 命中数 | 命中题 |
|---|---|---|---|
| v1（Phase 4，有 bug） | 全树别名比对 | **16**（虚高） | — |
| v2（最外层块基表） | 最外层 FROM/JOIN 基表差集 | 4 | E-0042, E-0087, E-0088, E-0098 |
| v3（排名块基表，§十一） | 排名子句所属块基表差集 | **3** | E-0042, E-0087, E-0093 |

> 由此判定：v1 虚报的 16 条里，**13 条是别名/CTE 名/块内 JOIN 的假阳性**。其中 10 题（E-0037/55/58/59/62/67/73/74/80/92）经 v2 **和** v3 双重确认**无任何基表新增**——证实它们被 v1 的别名匹配误判；另 E-0098 仅最外层有 JOIN（取输出列名），不在排名块 ⇒ 非 §十一 副作用。

---

## 3. 四道回归闸（25 题，全 0）

| 闸 | 定义 | 触发数 |
|---|---|---|
| SCOPE_REGRESSION | `scope_ok=False` 或 SCOPE 类 violation | **0** |
| GROUPBY_REGRESSION | E11 把主键加进 GROUP BY | **0** |
| SELECT_REGRESSION | E11 往 SELECT 加 ID 列 | **0** |
| TIMEFILTER_REGRESSION | 日期谓词被改写 | **0** |

⇒ E11 收口后**没有引入 scope / GROUP BY / SELECT / 时间过滤** 四类结构回归。

---

## 4. 最终 verdict（v3 修正；预注册 vs DERIVE vs FINAL 全量对照见 `phase5_reanalysis.json`）

`counts_final`（v3 修正后）：

| verdict | 数 | 题 |
|---|---|---|
| FIXED | 1 | E-0017 |
| PASS_NO_EFFECT | 17 | E-0031/34/37/45/48/53/55/58/59/62/67/73/74/76/80/92/98（见下注） |
| REGRESSION | 1 | **E-0093** |
| SCOPE_RESOLUTION_SIDE_EFFECT | 1 | **E-0087** |
| OTHER | 5 | E-0042, E-0054, E-0088, E-0095, E-0096 |

> PASS_NO_EFFECT 17 = 原预注册 PASS_NO_EFFECT 6 + 从 SCOPE_RESOLUTION_SIDE_EFFECT 降级的 11（E-0037/55/58/59/62/67/73/74/80/92/98）。
> attribution_final：E11_SCOPE 0 / E11_STRUCTURE 1 / BUSINESS_SEMANTIC 4 / SQL_GENERATION 1 / NONE 19。

**FINAL 与预注册不同的题 = 13 / 25**：11 个是 v1 假阳性（SCOPE_RESOLUTION_SIDE_EFFECT → PASS_NO_EFFECT），加 E-0093（OTHER→REGRESSION）、E-0096（REGRESSION→OTHER，判据退化）。每个差异在 `preregistered_vs_derive_vs_final` 字段逐题显式可见。

---

## 5. 三个 §十一 副作用题的定性

### E-0087 — 干净良性副作用（`SCOPE_RESOLUTION_SIDE_EFFECT`）
- v3 在排名块新增 `products p, categories c`，`whether_semantically_required=True`（服务于破平键可见性）；
- `result_match=True`、`pred_row_count == gold_row_count`（行数不变）、`scope_ok=True`、四不变量全过；
- 结论：E11 收口如预期生效，带来一个**不影响结果正确性的 JOIN 副作用**。✅

### E-0093 — 已知失败模式复发（`REGRESSION` / `E11_STRUCTURE`）
- `tiebreak_keys=['id asc']`、`scope_ok=True`（破平键 `c.id` 本身可见——**T48 的可见性收口生效**）；
- 但为拿 `c.id` 而生成的多余 `JOIN categories c ON c.id = rcs.category_id` 的 ON 引用了 CTE `region_cat_sales` **未暴露的 `category_id`** ⇒ 执行失败 `no such column: rcs.category_id`；
- **根因与 T47/T48 同源**：在「拥有排名子句的 CTE 块」内为可见破平键而生成的 JOIN，其 ON 条件引用了 CTE 内部列，CTE 不向外暴露 ⇒ 结构性非法。**这不是 T48 新引入的回归，是既有已知缺陷的同一表现**；建议另立跟踪项（「CTE 排名块内可见破平键的 JOIN 合法性」），不要记成 E11 收口失败。

### E-0042 — 附带的非相关失败（`OTHER` / `BUSINESS_SEMANTIC`）
- v3 在排名块有 `order_items oi` JOIN（incidental），但该题真实失败是 `SUM(oi.subtotal)` vs gold `SUM(total_amount)` 的**业务语义聚合口径差**，与 E11 无关（与 T46 结论一致：不得记成 E11 的 REGRESSION）；
- verdict 保持 `OTHER/BUSINESS_SEMANTIC`，其排名块 JOIN 只在 §十一 目录里作信息登记。

---

## 6. 两个判据退化 / 重归因案例

- **E-0096**（`REGRESSION` → `OTHER` / `SQL_GENERATION`）：执行失败 `misuse of window function LAG()`——pred 把 `LAG()` 嵌套进 `ROW_NUMBER()` 的窗口 ORDER BY。E11 四条不变量**全过**；`E11_STRUCTURE_OK=False` 来自 `G_tiebreak_keys=['<clause-structure-differs>']`，即排名子句**数量**不同（pred 多了个 ROW_NUMBER 窗口，Top-N 策略差异 rn<=3 vs LIMIT 3）——属判据退化，**不得归因 E11**。
- **E-0088**（保持 `OTHER` / `BUSINESS_SEMANTIC`）：v2 在最外层有 `order_items oi, orders o` JOIN，但 v3（排名块）无 ⇒ 非 §十一 副作用；真实失败是业务语义，不归因 E11。

---

## 7. 对 T48「`NEEDS_FULL_TRIGGER_REVALIDATION`」的回答

| T48 留下的问号 | 本任务（n=25 真实调用）的回答 |
|---|---|
| scope 收口是否在更大触发面成立？ | ✅ scope 回归 **0**；E-0093 的 `c.id` 可见性已解决 |
| 是否引入新结构回归？ | ✅ 四类结构闸全 0；无新 REGRESSION（除已知 E-0093 类） |
| §十一 JOIN 副作用面到底多大？ | 真实 **3 题**（v1 虚报 16）；1 良性 + 1 已知失败 + 1 附带非相关 |
| 能否写 `READY_FOR_100Q`？ | ⚠️ **仍不建议**。理由：① E-0093 的 CTE 排名块 JOIN 合法性缺陷未修，仍是 open known-defect；② 25 题真实集 ≠ 100 题冻结 Benchmark；③ 真实 EX 字段=`execution_accuracy`，本次未跑冻结集 EX 对比 |

**总体**：E11 全触发面重验证**未暴露 T48 之外的任何新回归**；T48 的可见性收口在 n=25 上站稳。剩余唯一真问题（E-0093 的 CTE 内 JOIN 合法性）是独立的既有缺陷，应单独立项修复与跟踪。

---

## 8. 产物

- `F:/task49_e11_full_trigger_revalidation/phase5_analysis.py` — 离线重分析（v2/v3 检测器 + `derive_final` + 重归因 + 全量对照）
- `F:/task49_e11_full_trigger_revalidation/phase5_reanalysis.json` — v3 JOIN 判定 + A~N 结构/作用域检查 + 预注册 vs DERIVE vs FINAL 对照 + 重归因
- `F:/task49_e11_full_trigger_revalidation/phase5_reanalysis.txt` — 可读报告（JOIN 表 / A~N 表 / 对照表 / 专项）
- `F:/task49_e11_full_trigger_revalidation/raw_results.json` — Phase 4 的 25 次真实调用原始结果（未改）

> 纪律声明：本任务**未修改生产代码、未改 `.env`、未切换 Provider、未 commit**。所有判定可追溯至 `raw_results.json`，重分析 0 次新 API 调用。
