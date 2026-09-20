# Task 21：FANOUT_RECHECK_HINT OFF vs ON 100 条对照结果

> OFF/ON 为独立随机样本（Mimo）；ON 仅在 detector alarm 时注入 FANOUT_RECHECK_HINT 并额外 regeneration 一次（≤1）。
> **实验边界声明（P1-3）**：OFF 与 ON 不是严格单变量——
> ① 单题超时 OFF=60s / ON=90s；② OFF 走正式 LangGraph（含 SQL safety + ≤1 次 repair 分支），
> ON 为独立线性实验脚本（无 repair）；③ 延迟统计口径不同。
> 审计确认这些差异未实际污染本次 EX 结论（ON 组 repair_trigger=false、无 timeout/provider 归因差异），
> 但本结果只能解释为 **机制层面的观测**（mechanism-level observation），而非全局 EX 增益的干净因果估计。

## 1. 全局指标

| 指标 | OFF | ON | Δ |
|---|---:|---:|---:|
| Overall EX | 90.0% | 93.0% | **+3.0pt**（观测差异） |
| Conditional EX | 90.0% | 93.0% | +3.00 |
| Exec Rate | 99.0% | 100.0% | +1.00 |
| Pass@1 | 90.0% | 93.0% | +3.00 |
| Provider failure | 0 | 0 | - |
| Timeout | 0 | 0 | - |
| Bad case 数 | 10 | 7 | -3 |

> **整体差异的正确解释（P1-4）**：`OFF 90% → ON 93% (+3pt)` 中，3 个新增正确题的
> **只有 E-0086 的 +1pt 有 Hint 直接归因证据**（detector_alarm=true 且注入了 FANOUT_RECHECK_HINT）；
> **E-0099 / E-0100 未被暴露于干预（alarm=False，未注入 hint）**，其改善来自独立样本随机性，
> 不接受 Hint 归因。**禁止表述为「Hint 提升 EX 3pt」**。

## 2. Detector / Hint 命中

- ON alarm 数：**1**（['E-0086']）
- Hint 注入数：**1** → alarm==hint 一致性：**PASS**
- 总 regeneration 次数：1（平均 0.01/题；仅 alarm 题各 1 次，符合 ≤1 约束）

## 3. Fan-out 干预效果（ON alarm 样本）

- **修复成功（init✗→final✓）= 1**：['E-0086']
- 误修（init✓→final✗）= 0：无
- 仍错（init✗→final✗）= 0：无

## 4. E-0086 单独追踪

| 项 | OFF | ON |
|---|---|---|
| Detector alarm | -（未启用） | true |
| Hint 注入 | - | true |
| Initial EX | ✗（OFF 中 bad，fan-out） | false |
| Final EX | ✗ | **true（修复）** |
| regeneration | - | 1 |
> ON regenerated_sql：改为双 CTE（订单粒度 SUM(total_amount) + 明细粒度 COUNT(DISTINCT product_id) 再 JOIN），经典 fan-out 消除。

## 5. 组间变化（非 alarm 题）—— 不能归因 Hint

| 题 | OFF | ON | ON alarm | 归因 |
|---|---|---|---|---|
| E-0086 | ✗ | ✓ | True | Hint 干预 |
| E-0099 | ✗ | ✓ | False | 独立样本随机性（本轮 alarm=False，未注入 hint） |
| E-0100 | ✗ | ✓ | False | 独立样本随机性（本轮 alarm=False，未注入 hint） |

## 6. 延迟（工程代价）

| 指标 | OFF | ON |
|---|---:|---:|
| Avg | 11144.08 ms | 10529.26 ms |
| P50 | 10717.79 ms | 9616.94 ms |
| P95 | 17544.76 ms | 15561.7 ms |
| 平均 regeneration | 0 | 0.01 |

## 7. Provider / Timeout

- OFF：provider=0，timeout=0；ON：provider=0，timeout=0。无额外 provider 失败（额外 LLM 调用未引入异常）。

## 8. 结论

Overall EX observed change: **90% → 93% (+3pt)**。
Among the 3 additional correct cases, **only E-0086 had detector_alarm=true and received FANOUT_RECHECK_HINT;
therefore only +1pt is directly attributable to the Hint in this run**. E-0099 and E-0100 were not exposed to the intervention.

OFF and ON used independently generated samples and were **not strictly single-variable equivalent**
(timeout 60s vs 90s; pipeline LangGraph+repair vs linear no-repair; latency accounting differs);
therefore this result is a **mechanism-level observation, not a clean causal estimate of global EX gain**.

无误修、无新增回归、无 provider/timeout 恶化、延迟未明显上升。
> 局限：本轮 alarm 样本仅 1 条，修复证据为单案例；完整结论需更多 alarm 样本（见 comparison.json）。