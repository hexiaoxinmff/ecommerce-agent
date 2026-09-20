# Task 16：候选 Few-shot 设计（Demonstration-based）

> 原则：示范"能力"而非"题目答案"；每专项 ≤2 条；候选不修改正式 Few-shot；
> 复用 `scripts/check_benchmark_leakage.py` 做 Leakage Gate + 人工结构审计。
> 文件位置：`reports/eval/task16/candidate_fewshot/`（3 个 JSON）。

---

## 1. 候选集总览

| 文件 | 专项 | id | 目标能力 | 对应 Bad Case |
|---|---|---|---|---|
| output_shape_candidates.json | A 输出结构 | cand_A1_multi_col_ratio | label+指标多列（分类、销售额、占比） | E-0082/E-0083 |
| output_shape_candidates.json | A 输出结构 | cand_A2_dims_with_total | 分项计数 + 总计数 + 窗口过滤 | E-0090（列契约部分） |
| metric_semantics_candidates.json | B 金额语义 | cand_B1_metric_contrast | subtotal vs total_amount 对比 | （B 类仍不可修复，见 §4） |
| metric_semantics_candidates.json | B 金额语义 | cand_B2_order_paid_metric | 客单价/实付 → total_amount | （同上） |
| aggregation_candidates.json | C 聚合粒度 | cand_C1_order_grain_join | 订单粒度聚合后再与明细粒度 JOIN（防 fan-out） | E-0086 |
| aggregation_candidates.json | C 聚合粒度 | cand_C2_filtered_avg | 第二层 AVG 基准 = 显式阈值过滤后的集合 | E-0095 |

候选 SQL 全部在真实 dev DB（只读连接）上验证可执行且返回行（检查脚本输出见 tmp_task16_candidates_check.py 运行结果，均已 OK）。

---

## 2. Leakage Audit 结果（官方脚本）

```text
output_shape_candidates.json        → Leakage Gate：PASS（无泄漏）
metric_semantics_candidates.json    → Leakage Gate：PASS（无泄漏）
aggregation_candidates.json         → Leakage Gate：PASS（无泄漏）
```

（运行命令：`python scripts/check_benchmark_leakage.py --fewshot <file>`）

---

## 3. 人工结构审计（补充程序化工具之外的判断）

针对每条候选与 Benchmark 100 条 Gold 做了：SQL token Jaccard / 最长公共子串 / 题面相似度 / 专属常量扫描。摘要：

| 候选 | 与最相似 Gold | Jaccard | 常量命中 | 结构关系判断 |
|---|---|---|---|---|
| cand_A1 | E-0082 | 0.37 | 无 | 同"类目占比"主谓，但无专属类目名、无专属日期；CTE 形态与 E-0082 的标量子查询形态不同；问题措辞"各分类…分别"含义不同——能力示范，非答案示范 |
| cand_A2 | E-0090 | 0.20 | 无 | 同"状态/地区+高低计数+总数"轮廓但维度不同（地区 vs 状态）、阈值 8000 vs 5000、年份 2024 vs 2025、无取消订单附加说明——通用结构，非答案 |
| cand_B1 | E-0077 | 0.25 | 无 | 同为地区两 CTE，但一题为"两类金额对比"一题为"高于地区平均"——不含 Gold 的比较/聚合逻辑 |
| cand_B2 | E-0045 | 0.36 | 无 | 客单价/平均订单金额通用示范；问题、阈值均不同 |
| cand_C1 | E-0077 | 0.24 | 无 | 同"订单粒度+明细粒度双 CTE JOIN"骨架，但无任何比较/阈值/排名逻辑——纯结构示范 |
| cand_C2 | E-0061 | 0.26 | 无 | 同"达标过滤后平均"骨架，但阈值为 10000（非专属）、维度为分类（非地区-分类组合）、无 Top-N 输出限制 |

> 人工检查确认：无 SQL exact match、无模板级（子查询/GROUP BY/Top-N/ratio）复用、无 Benchmark 专属日期/金额/地区/类目组合复制。
> 每条候选的关键词/结构都刻意与对应的 Bad Case Gold 保持"结构同型、内容异构"（可教能力，但不可当答案直接套用）。

---

## 4. 候选 Few-shot 逐条说明

### A. 输出结构（output_shape_candidates.json）

**cand_A1_multi_col_ratio**（→ E-0082/E-0083）
- 问题：各商品分类在非取消订单中的销售额及其占全部商品销售总额的比例分别是多少？请给出分类名称、销售额与占比。
- SQL 要点：CTE 计算全平台总额 → 主查询输出 `category_name / category_sales / pct` 三列（维度列 + 2 个指标列）；
- 教的内容：**"占比类问题也要返回维度列 + 数值列"，列数要完整对齐题目所要求的信息**。这正是 E-0082/0083 缺的"把 c.name 也带出来"。
- 与 E-0082/E-0083 Gold 的关系：不同类目（E-0082=休闲零食 / E-0083=家用电器；候选为全部分类），不同窗口（无专属日期），不能直接套用为答案。

**cand_A2_dims_with_total**（→ E-0090 的输出列部分）
- 问题：2024年11月前各收货地区订单中，实付金额高于8000元的高金额订单数与8000元及以下的普通订单数分别是多少？请同时给出各地区的总订单数。
- SQL 要点：按 region 分组输出 `high_cnt / normal_cnt / total_cnt` 三列，且带年份过滤。
- 教的内容：**结构统计要多输出一个 total_cnt（或题面要求的'结构统计'列），且显式时间窗口要留在 WHERE**。

### B. 金额语义（metric_semantics_candidates.json）

> 前置警告：据 task16_bad_case_reanalysis §B，E-0077（缺表）与 E-0096/E-0100（Gold 口径冲突）**都不是 Few-shot 能稳定修复**。B 候选在此仅为"正确口径示范"供后续基准口径仲裁后复用；当前实验设计**不把 B 纳入单变量**（避免引入与 Gold 冲突的信号）。

**cand_B1_metric_contrast**
- 问题：2025年第二季度各收货地区中，商品明细销售额（明细行金额）与订单实付销售额（订单最终支付金额）分别是多少？请分别给出两列。
- SQL 要点：同一问题两 CTE 分别 `SUM(oi.subtotal) AS item_sales` 与 `SUM(o.total_amount) AS paid_sales`，输出两列 → **在同一个查询里把两种口径并列**，让模型看到二者的字段归属与命名差异（item_sales=明细，paid_sales=实付）。

**cand_B2_order_paid_metric**
- 问题：2025年第二季度各收货地区的客单价（平均每笔非取消订单的实付金额）是多少？
- SQL 要点：`AVG(total_amount)` 于订单粒度 → **客单价 / 平均实付 = total_amount**（与现有正式 ex_009 slot 语义一致，无冲突）。

### C. 聚合粒度（aggregation_candidates.json）

**cand_C1_order_grain_join**（→ E-0086）
- 问题：2024年7月至12月各收货地区的订单实付总额与售出商品件数分别是多少？请给出地区、实付总额与件数。
- SQL 要点：两 CTE —— `region_orders`（订单粒度 `SUM(total_amount)` 不 JOIN 明细）+ `region_items`（明细粒度 `SUM(quantity)`）→ 在 region 上 JOIN；
- 教的内容：**订单级金额必须在订单粒度聚合，再与明细粒度指标按维度键 JOIN**（防 fan-out）。这正是 E-0086 的失败模式，但候选用地区维度、无阈值/比较，纯结构示范。

**cand_C2_filtered_avg**（→ E-0095）
- 问题：2024年7月至12月各商品分类中，销售额高于10000元的分类里，有哪些分类的销售额高于所有达标分类的平均销售额？请给出分类名称与销售额。
- SQL 要点：CTE 内 `GROUP BY c.id HAVING SUM(subtotal) > 10000`（显式阈值**前置过滤**）→ 第二层 `AVG` 在**达标集合**上算 → 外查询比较；
- 教的内容：**第二层平均基准 = 显式阈值过滤后的集合**（阈值必须先通过 HAVING 前置，否则基准被低值稀释）。与 E-0095 失败模式同型（E-0095 的 pred 漏了 30000 前置过滤）。

---

## 5. 检索命中性与风险提示

- 当前检索器为规则型（关键词 Jaccard 0.30 + 表 0.25 + 字段 0.25 + scenario 0.20）。新增候选能否被"目标题"检索到，取决于其 question/字段/表与目标题的 scoring。
- 预估：
  - E-0082/E-0083（占比例，关键词"销售额/占比/分类"）→ cand_A1 question 含"销售额/占比/分类"，且 tables/columns 高度重合 → **命中预期高**；
  - E-0086（用户消费，关键词"消费/用户/金额"）→ cand_C1 是地区维度、关键词"实付/销量" → **命中依赖表/字段重合**（users/orders/order_items 字段不完全一致），**存在检索不命中风险**——实验时需用 trace 确认检索到 cand_C1；若未命中需考虑关键词扩展（属实验设计参数，不修改正式文件）。
  - E-0095（地区-分类销售额，关键词"销售额/平均"）→ cand_C2 为分类维度 → 命中依赖字段重合（orders/order_items/products/categories 与 E-0095 完全一致）→ **命中预期中高**。
- **风险登记**（写入实验矩阵）：Few-shot 检索到 ≠ 模型一定模仿正确结构；示范型示例可能带来 "表面相似但结构没学到"或"示例污染"。

---

## 6. 候选文件结构

```text
reports/eval/task16/candidate_fewshot/
├── output_shape_candidates.json      # A1, A2
├── metric_semantics_candidates.json  # B1, B2（本轮不推荐纳入实验）
└── aggregation_candidates.json       # C1, C2
```

候选文件不得替换 `data/fewshot/ecommerce_examples.json`（正式 FEWSHOT_V3 保持不动）。