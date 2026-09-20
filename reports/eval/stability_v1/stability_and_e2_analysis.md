# ECO-SQL-Bench · 稳定性复测（V1.1 + FEWSHOT_V2）与 E2 Few-shot 独立归因

> Task 14.1：确认推荐配置稳定性 + 严格拆分 Few-shot 贡献。
> 全部运行：同一 Benchmark（100）、同一 db（seed=20260914）、同一 Agent 核心、同一 Runner/Normalization、同一模型（mimo-v2.5-pro）；Mimo 随机性不可固定。

---

## 一、稳定性复测（V1.1 + FEWSHOT_V2，2 次独立完整 100 条）

| 指标 | run_01 (20260915_48824) | run_02 (20260915_50382) | E1 参考 (20260915_45852) | Mean | Min | Max | Range |
|---|---:|---:|---:|---:|---:|---:|---:|
| Overall EX | 83.0 | 85.0 | 88.0 | **85.3** | 83.0 | 88.0 | 5.0 |
| Conditional EX | 89.25 | 90.43 | 91.67 | **90.45** | 89.25 | 91.67 | 2.42 |
| Exec Rate | 93.0 | 94.0 | 96.0 | 94.3 | 93.0 | 96.0 | 3.0 |
| Provider Failures | 7 | 6 | 4 | 5.7 | 4 | 7 | 3 |
| Timeout | 7 | 6 | 3 | 5.3 | 3 | 7 | 4 |
| Bad Case(result_mismatch) | 10 | 9 | 8 | 9.0 | 8 | 10 | 2 |
| Avg Latency (ms) | 21366 | 15233 | 16875 | 17825 | 15233 | 21366 | 6133 |

**结论（保守表述）**：
- V1.1 + V2 的三次运行 Overall EX 在 **83%~88%** 之间波动（Range 5pp），Conditional EX 在 **89.25%~91.67%**（Range 2.42pp）；
- Overall EX 的波动主要由 **Mimo provider timeout/网络失败（每轮 3~7 题）** 拉低 Exec Rate 造成，**模型本身（Conditional EX）波动更小（<2.5pp）**；
- 仍明显高于 Baseline 72%（提升 +11~+16pp）；波动属 Mimo 随机性正常范围，非配置失效；
- （样本仅 3 轮、N=100，不做统计显著性断言。）

---

## 二、E2 严格拆分（V1.1 + FEWSHOT_V1 18条）

**实验变量：仅 Few-shot 从 V1（18）还原——Prompt 保持 V1.1 不变。**
（FEWSHOT_V1 独立快照：`data/fewshot/ecommerce_examples_fewshot_v1.json`，通过 `FEWSHOT_DATASET_PATH` 加载，未触碰正式 V2 文件。）

| 配置 | Prompt | Few-shot | EX | Cond EX | Provider Fail | Timeout |
|---|---|---|--:|--:|--:|--:|
| Baseline | V1 | V1(18) | 72.0 | 72.0 | 0 | 0 |
| **E2** | **V1.1** | **V1(18)** | **91.0** | **91.92** | 1 | 0 |
| E1 | V1.1 | V2(24) | 88.0 | 91.67 | 4 | 3 |

### 增益分解（本次运行观测值）

```text
Prompt-only 增益（E2 − Baseline）= +19.0pp
Combined 增益（E1 − Baseline）= +16.0pp
Few-shot 新增贡献（E1 − E2）= −3.0pp（单次运行内 E2 反而更高）
```

**结论**：
1. **贡献主体是 Prompt V1.1**（E2 在无新增 few-shot 下即达 91%）；Business Semantics 口径规则是 +16~19pp 的主要来源；
2. **FEWSHOT_V2 的 6 条新增未带来可观测的额外增益**（E1 88% vs E2 91%，差值为 Mimo 随机性范围内的翻转；无新增错误被其稳定修复）；
3. 因此**推荐配置可回退到更简的 `SQLGENERATOR_PROMPT_V1.1 + FEWSHOT_V1(18)`**，或保留 V2 亦无妨（不影响正确性）——前者更简单、少 6 条维护成本。

---

## 三、Bad Case 归属（E2 vs E1 vs Baseline）

- **Baseline 失败（非 provider）**：28 条
- **被 E2（V1.1）修复**：19 条 → 归因 Prompt（含 wrong_cancelled 12 中 11、enum_hallucination 4、amount 部分等）
- **被 E1 修复但 E2 未修复**：1 条（E-0098）→ Few-shot 唯一可能贡献点
- **稳定未修复（E1/E2/run01/run02 均 ✗）**：E-0057, E-0077, E-0082, E-0083, E-0086, E-0090, E-0095, E-0097（8 条）→ 真实模型缺口（输出列结构/深嵌套聚合/金额口径残余），与 few-shot/prompt 均无关

### E2 的 8 个 result_mismatch（与 E1 同类）

| eval | 根因（同 Task14 归因） |
|---|---|
| E-0057 | 分段边界列 key 差异 |
| E-0077 | total_amount vs subtotal |
| E-0082/0083 | 输出列不完整（gold 2 列 vs pred 1 列，§D1） |
| E-0086 | 两阶段聚合仍用订单均值 |
| E-0090 | 缺 total_cnt 列（gold 4 vs pred 3） |
| E-0095 | 组合过滤阈值（HAVING>30000） |
| E-0097 | total_amount vs subtotal |

---

## 四、新增 6 条 Few-shot（ex_019~024）逐条映射

| example_id | 针对 Bad Case 类型 | 原问题 | 目标 operator/能力 |
|---|---|---|---|
| ex_019 | user_avg_granularity（E-0056/86） | 用户平均累计消费 | subquery / 两阶段聚合 |
| ex_020 | date_group %Q 非法（E-0066） | 季度订单数 | case_when / date_group |
| ex_021 | wrong_cancelled（E-0051 等结构统计） | 地区订单量分布 | group_by / 结构统计口径 |
| ex_022 | wrong_daily_avg（E-0073） | 日均销售额 | COUNT(DISTINCT) / 多表 JOIN |
| ex_023 | ratio_denominator（E-0082/83） | 同窗口占比 | ratio / subquery 分母 |
| ex_024 | enum_hallucination（E-0034/38） | 在售 Top-5 | top_n / 枚举 on_sale |

**实测结果**：E-0056/66/73/76 等确实被 V1.1+V1（E2）单独修复（→ Prompt 规则已覆盖）；E-0082/83 仍失败（few-shot 示例存在但模型仍输出单列 → 输出列结构问题需更强约束，非 few-shot 能解决）；ex_021 等结构统计类与 Prompt 规则重叠 → Few-shot 增益被 Prompt 覆盖，难以分离出净增量。

---

## 五、推荐配置判定

**`SQLGENERATOR_PROMPT_V1.1` 是提升的核心来源**（+19pp 观测值，3 轮稳定高于 72%）；
`FEWSHOT_V2` 无显著额外贡献，**为简化可回退 V1，或保留 V2（无副作用）**。

**Recommended Configuration v1 = `SQLGENERATOR_PROMPT_V1.1 + FEWSHOT_V1(18)`**（更简、成本更低；保留 V2 亦等价）。
如实记录波动：Overall EX 83~88%，Conditional EX 89~92%（3 轮）。

*以上为单/多次运行观测，Mimo 随机性 → 不做统计显著性断言。*