# Task 14.2 四组专项实验汇总（E4~E7）

> 基准：Recommended Candidate（V1.1 + FEWSHOT_V1 18 条），run 20260915_51396（EX 91.0 / CondEX 91.92）。
> 方法：每次仅通过 `SQLGEN_EXTRA_RULES` 环境变量启用一个专项规则段（V1.1 基础规则不变），
> FEWSHOT 固定 V1(18)，完整 100 条回归。

## 1. 总体对比

| run | Prompt | EX% | CondEX% | Exec% | Provider | Timeout | 目标题修复 |
|---|---|---|---:|---:|---:|---:|---:|---|
| **Recommended** | V1.1 | **91.0** | 91.92 | 99.0 | 1 | 0 | —（基准） |
| E4 | V1.1+E4(Output Contract) | 85.0 | 90.43 | 94.0 | 6 | 6 | 0/3 |
| E5 | V1.1+E5(Metric Semantics) | 85.0 | 89.47 | 95.0 | 5 | 5 | 0/2 |
| E6 | V1.1+E6(Nested Agg) | 81.0 | 91.01 | 89.0 | 11 | 11 | 0/2 |
| E7 | V1.1+E7(CASE Boundary) | 79.0 | 89.77 | 88.0 | 12 | 11 | 0/1 |

> 说明：E6/E7 的 Overall 明显低于 recommended，主要由当轮 Mimo provider timeout 次数多（11~12）
> 拉低 Exec Rate 所致；CondEX（89.8~91.0）仍在 recommended（91.92）附近波动，无统计显著差异。

## 2. 8 个稳定 Bad Case 各实验表现（✓=修复，✗=失败，PROV=provider）

| eval | Rec | E4 | E5 | E6 | E7 | 专项 |
|---|---|---|---|---|---|---|
| E-0057 | ✗ | ✗ | ✗ | ✗ | ✗ | D |
| E-0077 | ✗ | ✗ | ✗ | ✗ | ✗ | B |
| E-0082 | ✗ | ✗ | ✗ | ✗ | ✗ | A |
| E-0083 | ✗ | ✗ | ✗ | ✗ | ✗ | A |
| E-0086 | ✗ | ✗ | ✗ | ✗ | ✗ | C |
| E-0090 | ✗ | ✗ | ✗ | PROV | ✗ | A |
| E-0095 | ✗ | ✗ | ✗ | ✗ | PROV | C |
| E-0097 | PROV | ✗ | PROV | PROV | PROV | B |

**结论：E4~E7 四组专项在各自目标题上修复率均为 0。**

## 3. 为什么 Prompt 规则没能修复？

对 8 题的 pred SQL 逐字复核发现，模型**在生成时根本没有进入"读规则 → 应用规则"的路径**：
- E-0082/83：仍输出单列 percentage（规则要求两列 name+pct）——模型省略了分类名列；
- E-0090：仍缺 total_cnt 列——模型未补结构总数列；
- E-0077/97：仍用 `SUM(total_amount)`——规则要求 subtotal，模型未切字段；
- E-0086：仍 `COUNT(o.id)`（order_items JOIN 后未 DISTINCT）→ 行数膨胀；
- E-0095：仍无 `HAVING SUM>30000` 前置过滤；
- E-0057：仍 `BETWEEN 1 AND 3`（0 落入 ELSE 档）。

这些属于**模型 SQL 生成时的结构/语义偏差**，追加几行文本规则不足以使模型改正；
依赖 few-shot 提供正确 SQL 形态（示范）或后续在 Schema/生成校验层系统性改进，
而非简单加 Prompt 指令。

## 4. 推荐方案

**保留 Recommended Candidate（SQLGENERATOR_PROMPT_V1.1 + FEWSHOT_V1 18 条）**：
- Overall EX 91.0 / CondEX 91.92 仍是四组中最高；
- E4~E7 全部无目标修复且 Overall 无增益（E6/E7 因 timeout 明显下降）；
- 不再合并任何专项规则到正式 Prompt（避免无收益地增加长度与不确定性）。

**暂不采用**：E4~E7 专项规则段（保留在 prompt.py 中作为可选项，由 SQLGEN_EXTRA_RULES 控制，
默认关闭；不做正式合并）。