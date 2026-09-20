# ECO-SQL-Bench 评测集题型矩阵（Evaluation Matrix）

> 阶段：Phase 5 · Task 11（评测集设计与题型矩阵）
> 日期：2026-09-15
> 作者：TRAE 开发 Agent
> 状态：设计定稿，等待总顾问验收；题目生成属 Task 12，不在本任务范围
> 关联文档：`docs/evaluation-plan.md`（指标与分阶段策略）、`docs/evaluation-dataset-spec.md`（数据规范）、`docs/database-schema.md`（口径权威）、`data/eval/README.md`（数据集元数据）

---

## 1. Benchmark 命名与定位

- **正式名称**：`ECO-SQL-Bench`
- **副标题**：项目自建电商 Text2SQL 评测集
- **定位**：针对本项目业务库（`db/ecommerce.db`，seed=20260914，dev 档规模）的**自建、可扩展、可审核、可自动评测**的 Text2SQL 基准。
- **评测哲学**（沿用 evaluation-plan.md）：主指标为 **Execution Accuracy（EX）**——pred SQL 与 gold SQL 在**同一数据库**上执行结果一致即判对，不要求 SQL 文本相同；辅助指标为 Exec Rate / Pass@1 / Latency / Repair Rate。

### 1.1 目录规划（以现有工程为准，不强行重构）

```text
data/eval/
├── ecommerce_eval_v1.json        # 主 Benchmark（单轮）
├── ecommerce_multiturn_v1.json   # 多轮评测组（单独文件，不混入主集）
├── bad_cases/                    # Bad Case 沉淀（Task 13/14 使用）
│   ├── B-0001.example.json
│   └── README.md
└── README.md                     # 数据集元数据
```

---

## 2. 总体规模规划（约 300 条）

| 阶段 | 内容 | 说明 |
|---|---|---|
| 阶段 1 | **100 条高质量单轮** | Easy 25 / Medium 30 / Hard 30 / Extra Hard 15（总数固定 100，比例允许按实际数据库能力微调） |
| 阶段 2 | **约 200 条单轮 + 约 50~100 条多轮** | 多轮单独存放在 `ecommerce_multiturn_v1.json` |
| 最终 | **约 300 条左右** | 质量 > 数量；不硬凑数量、不加大量同义改写 |

> **原则：题型覆盖率 > 数量。** 任一难度档达不到质量标准时，宁可少放、不放。

### 2.1 生成批次（与任务书的批生成规范一致）

| 批次 | 难度 | 数量 |
|---|---|---|
| Batch 1 | Easy | 25 |
| Batch 2 | Medium | 30 |
| Batch 3 | Hard | 30 |
| Batch 4 | Extra Hard | 15 |

每批生成后必须通过：自动结构检查 → 数据库执行 → 去重 → 语义检查 → 人工审核 → 记 hash → 入集（详见本文件第 10 节与 spec 文档第 C 章）。

---

## 3. 场景标签（scenario）— 可枚举，不允许一题一个随机字符串

### 3.1 核心场景（阶段 1 必覆盖，7 个）

| 标签 | 业务含义 | 典型问题 |
|---|---|---|
| `user_analysis` | 用户结构/行为/注册/地区分布 | "哪个地区的用户最多？" |
| `product_analysis` | 商品维度（价格/销量/在售） | "价格超过500元的商品有哪些？" |
| `category_analysis` | 分类维度（含一级/叶子层级汇总） | "每个类别有多少商品？" |
| `order_analysis` | 订单结构（状态/数量/金额口径） | "各订单状态分别有多少单？" |
| `sales_analysis` | 销售经营（销售额/销量/客单价） | "总销售额是多少？" |
| `time_analysis` | 时间趋势/时间窗口 | "2025 年每月销售额是多少？" |
| `regional_analysis` | 地区维度（收货/用户地区） | "各省份订单量是多少？" |

### 3.2 扩展场景（阶段 1 少量进入矩阵，作为枚举成员）

```text
comparison | ranking | ratio | trend | funnel
```

> **场景=业务主题、operator=SQL 能力，二者并行不冲突**（如"销售额 Top5 商品" → scenario=`ranking` + operators=`top_n,join,group_by`）。
> 阶段 1 中 `ranking / ratio / comparison` 以少量配额进入 100 条矩阵（合计 13 条，见 §7.2）；`trend / funnel` 需要更长时间跨度或多环节业务流支撑，暂不进入阶段 1 矩阵（原因：订单时间跨度 2024-01-01 ~ 2026-09-12，跨期趋势可用但口径易歧义，阶段 2 启用以保证数据可比性）。

---

## 4. SQL 操作标签（operators）— 统一枚举

### 4.1 基础操作（阶段 1 必覆盖，14 个）

```text
select | where | order_by | limit | group_by | having | aggregate |
join | subquery | case_when | date_filter | date_group | ratio | top_n
```

### 4.2 复杂操作（Hard/Extra Hard 覆盖）

```text
nested_subquery | multiple_join | conditional_aggregation |
comparison_to_average | multi_dimension_grouping
```

### 4.3 使用约定与统一统计口径（覆盖统计必须按此口径，避免虚增）

- `select` 为一切题目的隐含基础能力，**不要求显式写入 operators**（文档与校验脚本均按"可选"处理）；
- 单题可携带 1~N 个操作标签；`operators` 数组内不允许重复；
- **一题可贡献多个 operator**（`GROUP BY + ORDER BY + LIMIT` 题可同时贡献 `group_by / order_by / limit / top_n / aggregate`）；
- **贡献规则（防虚增）**：
  1. 每个标签按"一题一次"计入；统计为覆盖计数，不是配额；
  2. 标签必须反映**该操作对解题真正重要**（能向 Reviewer 解释"这一步在解题中的角色"）；禁止把一题堆满标签来"折抵"其它题；
  3. `select` 不计入统计；
  4. `ORDER BY` 无 `LIMIT` 只计 `order_by`；`ORDER BY + LIMIT` 且题面为"前 N/最高/最低/最近"必须额外计 `top_n`；
  5. `group_by` 只对显式 `GROUP BY` 语句计数；`having` 只对 `HAVING` 子句计数；
  6. `join` = 涉及 JOIN 的题数（不限链数）；`multiple_join` = JOIN 链 ≥2 次（即 ≥3 张表）的题数，二者可同题标注（如实反映）；
  7. `date_filter` = 存在日期/时间范围条件的题；`date_group` = 按日期分组聚合（MONTH/STRFTIME 等）的题。

---

## 5. 题型矩阵（A ~ M）

> 每类给出"设计意图 + 示例问题 + 对应难度 + 核心 operators"。示例问题均基于真实库可回答（15 个地区、订单 2024-01-01 ~ 2026-09-12、30 个分类、26.47~9351.34 元价格区间）。

### A. 基础查询（Easy）

验证最基础 Schema Linking + SELECT。

```text
有多少用户？                       → user_analysis     [select, aggregate]
有多少商品？                       → product_analysis  [select, aggregate]
有哪些订单状态？                    → order_analysis    [select]
某个地区有多少用户？（如广东）       → regional_analysis [where, aggregate]
```

### B. 条件过滤（Easy ~ Medium）

主要 SQL：`WHERE / AND / OR / BETWEEN / IN`。

```text
价格超过500元的商品有哪些？          → product_analysis  [where, order_by, limit]
2024 年之后注册的用户有哪些？        → user_analysis    [where, date_filter]
最近30天的订单有多少？              → order_analysis   [date_filter, aggregate]
```

### C. 聚合统计（Easy）

主要 SQL：`COUNT / SUM / AVG / MIN / MAX`。

```text
平均商品价格是多少？                → product_analysis  [aggregate]
订单总数是多少？                    → order_analysis   [aggregate]
总销售额是多少（排除取消）？         → sales_analysis   [aggregate, join, where]
```

> 口径提示：「总销售额」默认排除 `cancelled`（`WHERE o.status != 'cancelled'`，见 database-schema.md §5.1）。

### D. GROUP BY（Medium）

```text
每个地区有多少用户？                → user_analysis     [group_by, aggregate]
每个类别有多少商品？                → category_analysis [group_by, aggregate, join]
每个月销售额是多少？                → sales_analysis    [date_group, group_by, aggregate, join]
```

### E. 排名 / Top-N（Medium ~ Hard）

```text
销量最高的5个商品                   → product_analysis  [top_n, group_by, aggregate, join, multiple_join]
销售额最高的10个类别                → category_analysis [top_n, group_by, aggregate, multiple_join, join]
订单最多的地区（去重用户）           → regional_analysis [top_n, group_by, aggregate, join, distinct]
```

### F. JOIN（Medium ~ Hard）

覆盖 `users/orders/order_items/products/categories` 典型路径。

```text
每个商品类别的销售额                → category_analysis [join, multiple_join, group_by, aggregate]
每个地区的订单金额                  → regional_analysis [join, group_by, aggregate]
每个用户的订单数量                  → user_analysis     [join, group_by, aggregate]
```

### G. 时间分析（Medium ~ Hard）

```text
近7天/近30天                       → time_analysis   [date_filter]
最近一个月                         → time_analysis   [date_filter]
某个月（如2024年6月）               → time_analysis   [date_filter, aggregate]
某季度（如2025年第三季度）           → time_analysis   [date_filter, aggregate]
今年（2026年至今）                  → time_analysis   [date_filter, aggregate]
按月/按季度趋势                     → time_analysis   [date_group, group_by, aggregate]
```

> 数据边界：订单仅覆盖 2024-01-01 ~ 2026-09-12。**不要为覆盖题型硬造库中不存在的粒度**（如周内某天粒度可做但需 6 周以上数据验证；"某年同比"需要跨完整年数据才合理）。

### H. HAVING / 聚合后过滤（Medium ~ Hard）

```text
订单数量超过10的用户                → user_analysis  [having, group_by, join]
销售额超过阈值的类别                → category_analysis [having, group_by, join, aggregate]
```

### I. 子查询（Hard）

```text
价格高于商品平均价格的商品           → product_analysis [subquery, comparison_to_average]
销量高于平均销量的商品               → product_analysis [subquery, comparison_to_average, join, group_by]
销售额高于平均水平的类别             → category_analysis [subquery, comparison_to_average, multiple_join]
```

### J. 比率 / 占比（Hard）

必须定义 `gold result + tolerance`（见 spec 文档 §D6/D7）：

```text
某地区用户占全部用户的比例           → regional_analysis [ratio, aggregate]
某类别销售额占总销售额的比例         → category_analysis [ratio, aggregate, join, multiple_join]
```

```json
{
  "answer_slots": {
    "value_type": "ratio",
    "tolerance": 0.01
  }
}
```

### K. 多维组合（Hard ~ Extra Hard）

```text
近30天各地区各类别销售额              → sales_analysis [date_filter, multi_dimension_grouping, group_by, multiple_join]
近30天华南地区销量最高的商品           → product_analysis [date_filter, where, top_n, multiple_join, group_by]
```

### L. Hard / Extra Hard 复杂组合

```text
多表 JOIN；JOIN + GROUP BY；JOIN + HAVING；子查询；聚合 + 子查询；
多条件组合（时间 + 地区 + 类别）…
```

> **禁止为 Extra Hard 人为制造无业务意义的 SQL**（如跨表 SELECT 一个与问题无关的列再套复杂子查询）。Extra Hard 的本质是"业务条件多、Schema Linking 弱信号条件下仍能写出正确口径"，不是"把简单题改难"。

### M. 歧义 / 澄清（少量）

```text
最近卖得最好的是哪些？      → expected_behavior = "clarify"（"最近"多长？"卖得好"指销量还是销售额？）
表现最好的类别是什么？      → expected_behavior = "clarify"（口径未定义）
哪些商品比较受欢迎？        → expected_behavior = "clarify"
```

- 这些条目 **不一定要求生成 SQL**，用于测试 Agent 是否**澄清而非乱猜**；数量 ≤ 正式评测集总数的 10%；
- `expected_behavior` 枚举：`answer`（直接作答）/ `clarify`（需澄清）/ `refuse`（合理拒答/超出数据域）。

---

## 6. 难度分级规则（不允许凭主观感觉标难度）

> 难度由 **SQL 结构复杂度 × 业务口径复杂度** 共同决定。问法长 ≠ Extra Hard。

| 级别 | SQL 结构特征 | 业务口径特征 |
|---|---|---|
| **Easy** | 单表；简单 `WHERE`；简单 `COUNT/SUM/AVG`；简单 `ORDER BY`；简单 `LIMIT` | 单一口径，无歧义 |
| **Medium** | `GROUP BY`；简单 `HAVING`；简单 JOIN（2 表）；日期过滤；Top-N（简单排序） | 需要明确一种口径 |
| **Hard** | 多表 JOIN（≥3 表）；`GROUP BY`+`HAVING`；单层子查询；复杂过滤；时间+聚合；多维分析 | 口径判断 + 条件组合 |
| **Extra Hard** | 多级 JOIN；嵌套子查询；复杂聚合（如条件聚合/多步）；多个业务条件；复杂时间逻辑；强 Schema Linking 需求 | 口径权衡 + 弱信号列定位 |

**分级对照表（判定速查）**：

| 问法 | 结构决定 | 结果 |
|---|---|---|
| "有多少用户？" | 单表 COUNT | Easy |
| "销售额 Top5 商品" | JOIN+GROUP+ORDER+LIMIT | Medium |
| "2025 年各季度销售额及环比" | 多级聚合+时间+自比 | Extra Hard |
| "复购≥3 的用户占比" | JOIN+HAVING+ratio+子查询 | Hard/Extra Hard |

---

## 7. 第一批 100 条矩阵（设计目标）

### 7.1 难度总分布

| Difficulty | 数量 | 占比 | 核心能力 |
|---|---|---|---|
| Easy | 25 | 25% | SELECT / WHERE / COUNT / ORDER BY / LIMIT |
| Medium | 30 | 30% | GROUP BY / JOIN(2表) / HAVING(简单) / Top-N / 日期过滤 |
| Hard | 30 | 30% | JOIN(≥3表) / GROUP BY+HAVING / Subquery / 时间+聚合 / 占比 |
| Extra Hard | 15 | 15% | Multi-Join / Nested Subquery / Complex Agg / 多条件组合 |
| **合计** | **100** | 100% | — |

### 7.2 难度 × 场景分布

| 场景 | Easy | Medium | Hard | Extra Hard | 小计 |
|---|---:|---:|---:|---:|---:|
| user_analysis | 6 | 3 | 2 | 1 | 12 |
| product_analysis | 5 | 5 | 3 | 2 | 15 |
| category_analysis | 2 | 4 | 3 | 1 | 10 |
| order_analysis | 6 | 3 | 2 | 1 | 12 |
| sales_analysis | 2 | 5 | 5 | 3 | 15 |
| time_analysis | 2 | 4 | 5 | 3 | 14 |
| regional_analysis | 2 | 3 | 3 | 1 | 9 |
| ranking | 0 | 3 | 2 | 1 | 6 |
| ratio | 0 | 0 | 3 | 1 | 4 |
| comparison | 0 | 0 | 2 | 1 | 3 |
| **合计** | **25** | **30** | **30** | **15** | **100** |

> `trend / funnel` 阶段 1 不进入矩阵（原因见 §3.2）。

### 7.3 难度 × SQL Operator 约束矩阵（Coverage > Exact Count）

> 不再使用"固定数字配额"（旧版 `aggregate=20 / order_by=8 / limit=8` 已被证明结构矛盾，见 §7.6）。
> 约束分四类：**最低覆盖**（`≥N`）、**目标范围**（`M~N`，区间内均为健康，超上限需去重审查）、
> **禁止项**（`禁止`，该难度不得出现）、**隐含**（不计入统计）。
> 单元格取值依据：Task 12 Batch 1 实测（Easy 25 条） + 各难度容量分析（§7.6）+ 去重约束。

| operator | Easy | Medium | Hard | Extra Hard | Tier |
|---:|---:|---:|---:|---:|---|
| aggregate | ≥20 | ≥18 | ≥20 | ≥10 | A 核心 |
| where | ≥15 | ≥15 | ≥18 | ≥6 | A 核心 |
| select | 隐含 | 隐含 | 隐含 | 隐含 | A 核心 |
| group_by | 禁止 | ≥15 | ≥15 | ≥8 | A 核心 |
| order_by | 3~6 | ≥12 | ≥12 | ≥4 | A 核心 |
| limit | 3~6 | ≥10 | ≥8 | ≥2 | A 核心 |
| join | 禁止 | 2 表 ≥10 | ≥15 | ≥2 | A 核心 |
| top_n | 2~6 | 6~12 | 4~8 | 2~4 | B 业务 |
| having | 禁止 | 5~10 | ≥8 | ≥4 | B 业务 |
| date_filter | ≥4 | ≥8 | ≥8 | ≥4 | B 业务 |
| date_group | 禁止 | 4~8 | ≥6 | ≥3 | B 业务 |
| ratio | 禁止 | 禁止 | ≥5 | ≥2 | B 业务 |
| case_when | 禁止 | 1~4 | 2~6 | 1~4 | B 业务 |
| subquery | 禁止 | 禁止 | ≥6 | ≥4 | C 复杂 |
| multiple_join | 禁止 | 禁止 | ≥8 | ≥8 | C 复杂 |
| comparison_to_average | 禁止 | 禁止 | 3~6 | ≥2 | C 复杂 |
| multi_dimension_grouping | 禁止 | 禁止 | 3~6 | ≥3 | C 复杂 |
| nested_subquery | 禁止 | 禁止 | 禁止 | ≥4 | C 复杂 |
| conditional_aggregation | 禁止 | 禁止 | 禁止 | ≥3 | C 复杂 |

**Tier 说明**：
- **Tier A（核心）**：Text2SQL 基本能力，多数题目天然携带，按**最低覆盖**约束，防止"某难度全是/全无某种基础操作"；
- **Tier B（重要业务）**：业务分析常用但非题题必需，按**最低覆盖 或 目标范围**约束；
- **Tier C（复杂能力）**：逐难度逐步放开，只在对应难度**出现即可**（不设高数量门槛）；禁止项起到"难度分级生效"的作用。

**禁止项（难度分级的硬边界，Validator 强制执行）**：

```text
Easy       禁止 group_by / join / having / subquery / date_group / ratio / case_when
           / multiple_join / nested_subquery / conditional_aggregation /
           comparison_to_average / multi_dimension_grouping
           （允许 aggregate / where / order_by / limit / top_n / date_filter）

Medium     禁止 subquery / ratio / multiple_join / nested_subquery /
           conditional_aggregation / comparison_to_average / multi_dimension_grouping

Hard       禁止 nested_subquery / conditional_aggregation

Extra Hard 无 operator 禁止项（但禁止"无业务意义的复杂 SQL"，见 §L）
```

> 运行约束的机制：`scripts/validate_eval_dataset.py` 内置上述禁止项，条目递补即拦截；
> 最低覆盖/目标范围为**生成阶段监测值**（validator 输出覆盖矩阵对照本表，不因未达而碎裂既有数据）。

### 7.4 题集级最低覆盖（= §7.3 各档下限之和，供 300 条总体监测）

| operator | 总体最低 | operator | 总体最低 |
|---|---:|---|---:|
| aggregate | 68 | date_filter | 24 |
| where | 54 | limit | 23 |
| group_by | 38 | having | 17 |
| order_by | 31 | multiple_join | 16 |
| join | 27 | top_n | 14 |
| date_group | 13 | subquery | 10 |
| ratio | 7 | multi_dimension_grouping | 6 |
| comparison_to_average | 5 | case_when | 4 |
| nested_subquery | 4 | conditional_aggregation | 3 |

> 说明：总体最低 = 各难度下限直接求和；范围为"健康区间"参考，不参与累加。
> validator 输出实际覆盖矩阵与 §7.4 对照；缺口 === 补题信号，超上限 === 模板去重信号。
> 场景配额仍按 §7.2 不变（Easy 聚合场景多 → aggregate/where 自然偏高，属正常，不反向调整业务题型）。

### 7.6 容量分析与旧矩阵矛盾证明（为什么 order_by/limit=8 不可行）

以 Easy=25 为已知条件，单表、无 GROUP BY、无 JOIN 的约束下：

```text
设  A = 聚合标量题数量（结果单值，贡献 aggregate）
    L = 有序列表题数量（SELECT 输出多行，ORDER BY [+LIMIT]，无 GROUP BY）
可得：A + L = 25（聚合标量与有序多行列表互斥：有 GROUP BY 才是聚合+列表，
     而 GROUP BY 属于 Medium，Easy 禁止）

若 aggregate ≥ 20 ⇒ A ≥ 20 ⇒ L ≤ 5
⇒  order_by ≤ 5（只有列表题有意义地携带 ORDER BY）
⇒  limit  ≤ 5（LIMIT 需排序语义，同样只出现在列表题）

结论：
1. 旧矩阵 Easy 行 order_by=8 / limit=8 与 aggregate=20 数学上不可同时满足；
2. 即使强行让 L=5，5 条单表有序列表也只能靠 价格/日期/状态 几类排序反复做
   “排序方向反例 / 换日期区间”，必然触碰 §10 模板去重红线；
3. Task 12 Batch 1 以质量优先取 L=3（用户注册时间 / 订单日期 / 订单金额+日期），
   实测 aggregate=22、order_by=3、limit=3 —— 与上述边界一致。

修正方案：
   Easy：aggregate 保持 ≥20；order_by / limit 改为目标范围 3~6（区间下界=3 与实测一致，
   上界 6 是容量上限 5 的近似 + 允许 1 条无 LIMIT 排序题，如“全部在售商品按价格降序列出”）；
   top_n 由 0 修正为 2~6（Batch 1 实有 3 条 Top-N 列表题，旧表 top_n=0 与数据矛盾）。
```

**可执行性模拟（Easy 25 / Medium 30 / Hard 30 / Extra Hard 15，新规则下可无模板重复生成）**：

| Difficulty | 核心 operator（最低覆盖） | 可选 operator | 禁止 operator |
|---|---|---|---|
| Easy | aggregate≥20、where≥15、date_filter≥4、order_by 3~6、limit 3~6、top_n 2~6 | （无） | 见 §7.3 禁止项 |
| Medium | aggregate≥18、where≥15、group_by≥15、join(2表)≥10、order_by≥12、limit≥10、date_filter≥8、top_n 6~12 | having 5~10、date_group 4~8、case_when 1~4 | subquery / ratio / multiple_join / 复杂标签 |
| Hard | aggregate≥20、where≥18、group_by≥15、join≥15、multiple_join≥8、having≥8、date_filter≥8、subquery≥6 | ratio≥5、top_n 4~8、case_when 2~6、comparison_to_average 3~6、multi_dimension_grouping 3~6、date_group≥6 | nested_subquery / conditional_aggregation |
| Extra Hard | aggregate≥10、where≥6、group_by≥8、multiple_join≥8、nested_subquery≥4、subquery≥4、conditional_aggregation≥3 | having≥4、date_filter≥4、date_group≥3、ratio≥2、comparison_to_average≥2、multi_dimension_grouping≥3、case_when 1~4、top_n 2~4、order_by≥4、limit≥2 | 无（仅禁止无业务意义组合） |

> 该模拟表明：多标签题（如"各地区销售额 Top5"，一条即可同时贡献
> join + group_by + aggregate + order_by + limit + top_n ≈ 6 个标签）使各难度最低覆盖
> 在对应容量内可自然达到，无需模板重复。

### 7.5 第一批 100 条生成施工图

**Easy 25**（单表、简单聚合/过滤/排序）

```text
Easy 25
├── user_analysis 6     单表 COUNT / WHERE（用户总数、某地区用户数、注册时间过滤）
├── product_analysis 5  价格/状态条件 + ORDER BY + LIMIT（价格>500、在售商品 Top5 价格等）
├── order_analysis 6    状态分布、某状态订单数、日期过滤（近7/30天订单数）
├── category_analysis 2 分类/叶子分类总数等简单计数
├── regional_analysis 2 地区用户计数
├── time_analysis 2     简单 date_filter（最近30天）
└── sales_analysis 2    非取消订单数等单表口径聚合
```

**Medium 30**（GROUP BY / 2 表 JOIN / Top-N / 日期分组）

```text
Medium 30
├── ranking 3           商品/分类/地区 Top-N（2~3 表 JOIN + ORDER + LIMIT）
├── user_analysis 3     按地区分组用户数、订单数>N 的用户（having 简单）
├── product_analysis 5  每商品销量/销售额（join 明细+商品）
├── category_analysis 4 每分类商品数、每分类订单量（join）
├── order_analysis 3    按状态/月份统计、近30天订单分布
├── sales_analysis 5    按月/按状态的销售额（join + date_filter/date_group）
├── time_analysis 4     月份/季度聚合（date_group）
├── regional_analysis 3 按收货地区订单量（group_by）
└── case_when 1         简单状态条件转换
```

**Hard 30**（多表 JOIN / HAVING / 子查询 / 占比 / 时间+聚合）

```text
Hard 30
├── multi join 8        商品-订单-明细-分类（≥3表）销售额汇总
├── join + having 5     销售额超阈值的类别、订单数超阈值的用户
├── subquery 5          高于平均价格/销量的商品（comparison_to_average）
├── ratio 4             地区/类别占比（含 tolerance）
├── time + aggregate 5  月趋势、季度同比（跨期自比）
├── case_when 3         条件聚合（状态/价位分档）
└── comparison 2        两两对比（两类/两地区对比）
```

**Extra Hard 15**（嵌套子查询 / 多级 JOIN / 条件聚合 / 多维 / 复杂时间）

```text
Extra Hard 15
├── nested_subquery 4   Top-N 在子查询基础上二次统计
├── multiple_join 4    多级 JOIN + 多业务条件（时间+地区+类别+状态）
├── conditional_aggregation 3  SUM(CASE WHEN...) 条件口径（取消/退款剔除口径）
├── multi_dimension 2   地区×类别×时间三维
└── complex time 2      跨期环比/占比等复杂时间逻辑
```

> 施工图是**生成配额**（Task 12 的 Batch 1~4 按此配比出题），不是死模板：单题场景与 operator 可合理重合，但落库后必须通过 §7.2 场景配额、§7.3 operator 约束（含禁止项）与去重审核三重复核。

---

## 8. 多轮结构设计（第二阶段的单独文件，不混入主集）

文件：`data/eval/ecommerce_multiturn_v1.json`

```json
{
  "conversations": [
    {
      "conversation_id": "C-001",
      "turns": [
        {
          "turn_id": 1,
          "previous_turn_id": null,
          "question": "最近30天销售额最高的商品有哪些？",
          "gold_sql": "...",
          "gold_result_hash": "...",
          "expected_context": { "dependency": "none" }
        },
        {
          "turn_id": 2,
          "previous_turn_id": 1,
          "question": "再按类别看看。",
          "gold_sql": "...",
          "expected_context": {
            "dependency": "dimension_change",
            "inherited": ["time_window", "sales_metric"],
            "changed": ["group_dim"]
          }
        },
        {
          "turn_id": 3,
          "previous_turn_id": 2,
          "question": "只看华南地区。",
          "gold_sql": "...",
          "expected_context": {
            "dependency": "filter_add",
            "inherited": ["time_window", "sales_metric", "group_dim"],
            "added": ["region"]
          }
        }
      ]
    }
  ]
}
```

**`expected_context.dependency` 枚举**（测试多轮理解的关键维度）：

```text
none            首轮/独立轮
reference       指代（"它"/"那个品类"→ 上轮对象）
condition_inherit  条件继承（沿用上轮时间窗/地区）
filter_add      追加筛选
dimension_change  分组维度切换
modify_range    修改范围（缩/扩时间、换地区）
answer_grounded 基于上轮结果继续（对上轮结果的引用）
```

**多轮评测重点**：指代消解、条件继承、筛选追加、分组变化、上轮结果理解；每轮独立计 EX，另计"上下文依赖轮"独立 EX（evaluation-plan.md §2.2）。

---

## 9. Gold SQL 强制入集流程（禁止 AI 直接入集）

```text
人工设计问题 → 候选 Gold SQL → 真实 SQLite 执行 → 检查 SQL 逻辑 →
人工核对结果 → 确认业务口径 → 生成 gold_result_hash → 正式入集
```

禁止：
```text
LLM 生成 SQL → 未经验证 → 直接成为 Gold
```

---

## 10. 批生成与去重流程

每批（25/30/30/15）执行：

```text
自动结构检查 → 数据库只读执行 → 三类去重 → 语义检查 → 人工审核 → 记 hash → 入集
```

三类去重：
1. **完全重复**：question 完全相同；
2. **语义重复**：不同问法、SQL/逻辑/测试目的基本一致（如同一个"用户最多地区"改为三种问法）；
3. **模板重复**：仅替换地区/分类等常量、逻辑完全一致的题目。

> 去重不以"恰好 N 条"为目标；替换变量产生的题目每难度档最多保留 2~3 条，保证覆盖代表性即可。

---

## 11. 与既有文档的一致性

- 难度比例、EX 主指标、Gold SQL 五步流程：与 `evaluation-plan.md` 完全一致；
- 金额/销售口径：以 `database-schema.md` §4/§5.1 为准，本题型矩阵中的示例 SQL 全部遵守（销售额/销量默认排除 `cancelled`）；
- 分阶段规模（100 → 200+多轮 → ~300）：与 `PRD.md` §18.1、`project-understanding.md` §8 一致；
- 阶段 1 不引入 LLM-as-Judge / 多模型投票 / embedding 向量库 / 多 Agent 共识等（见 `docs/evaluation-dataset-spec.md` §D）。