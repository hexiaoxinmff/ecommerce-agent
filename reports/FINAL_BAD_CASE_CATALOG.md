# FINAL BAD CASE CATALOG（最终 Bad Case 目录）

> Task 23 整理。**不修改任何历史 Bad Case 数据**（来源：reports/eval/bad_case_analysis_v2.md + Task 17~21 E3 标签）。
> 展示建议说明："这些都是**工程诊断记录**，反映当前 Prompt/口径对特定查询结构的失败模式；不代表系统不可用。"

---

## 1. 按根因分类

| 根因 | 代表样例（eval_id） | 根因描述 | 当前系统是否已处理 | 现状 | 是否适合最终展示 |
|---|---|:---:|---|---|---|
| `wrong_cancelled` | E-0014 / E-0022 / E-0047~0053 / E-0057 / E-0072 / E-0075 / E-0076 | 「订单数/结构统计」误加「取消订单过滤」；口径混淆（结构统计 vs 实际销售） | Prompt V1.3 已写「结构统计不排除 cancelled」规则 | 部分缓解、仍存在于个例 | 🟡 可讲（体现口径设计） |
| `enum_hallucination` | E-0002 / E-0034 / E-0038 / E-0081 | 枚举值幻想（'广东省'/'active' 等） | Prompt V1.3 枚举分表 + CHECK 约束说明 | 已显著缓解 | 🟡 可讲（体现 Schema 约束） |
| `wrong_amount_field` | E-0054 / E-0077 / E-0097 | 金额字段选错（subtotal vs total_amount vs price/unit_price） | Prompt V1.3 金额口径唯一权威 | 部分缓解 | 🟡 可讲（体现口径） |
| `wrong_output_shape` | E-0082 / E-0083 / E-0090 | SELECT 输出列不完整（缺 label / 缺 total_cnt 列，D1 判错） | 无静默修复；E3 不覆盖 | **仍存在**（Clean Baseline 中可见） | 🟡 可讲（评测契约 D1） |
| `wrong_avg_granularity` | E-0056 / E-0086 | 两阶段聚合粒度错误 / 订单级金额未防 fan-out | Prompt V1.3 规则 + **E3 Detector/hint（PoC）** | **E-0086 已被 E3 Hint 单例修复（机制验证）**；整体仍存在 | 🟢 可重点讲（E3 创新点） |
| `wrong_date_group` | E-0066 | strftime %Q 非法格式 | Prompt V1.3 日期规则（禁 %Q，用 substr+CASE） | 已修复 | ✅ 可讲（已解决） |
| `wrong_daily_avg` | E-0073 | 日均分母用固定天数 | Prompt V1.3 COUNT(DISTINCT order_date) 规则 | 已修复 | ✅ 可讲（已解决） |
| `wrong_context_filter` | E-0095 | 遗漏题面显式阈值（30000）前置过滤 | 题面 v1.1 已补齐 30000；Prompt 有 HAVING 规则 | 题面对齐，生成仍可能漏 | 🟡 可讲 |
| `ranking_tie_risk` | E-0098 | ROW_NUMBER 并列无稳定 tiebreaker | Gold 已加 tiebreaker（v1.1） | 已修复（Gold 侧） | ✅ 可讲 |
| `fan-out`（E3 新增标签） | E-0086 | orders×order_items 1:N 直连 + 订单级 SUM/AVG/COUNT 放大 | **E3 Detector（Gold-independent）+ 条件 Hint（PoC）** | 机制验证成功（单例 EX✗→✓），未全量修复 | 🟢 可重点讲（创新点） |

## 2. 展示口径建议

- **可讲**：`wrong_date_group`（已修）、`wrong_daily_avg`（已修）、`ranking_tie_risk`（Gold 修复）→ 展示系统迭代闭环；
- **重点讲**：`wrong_avg_granularity / fan-out`（E-0086）→ 与创新点 4（E3 Detector + Hint）联动，明确是 **PoC/机制验证**；
- **审慎讲**：`wrong_cancelled`、`wrong_amount_field`、`enum_hallucination`、`wrong_output_shape`、`wrong_context_filter` → 说明为**当前 Prompt 口径对特定结构仍存在的失败模式**，非致命缺陷。

> 归因数据为历史记录不可修改；本目录仅整理展示建议。最终引用基线：Clean Baseline v1.1 = 90.0% EX。

*生成：Task 23（整理归档，未改动历史数据）。*