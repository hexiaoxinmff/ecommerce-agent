# E3 Claims and Limits

> E3 实验冻结声明（Task 22）。基于 WorkBuddy 独立终审（Verdict: PASS WITH RESERVATIONS，无 P0，4 个 P1 与若干 P2）。
> 本文件定义 E3 可对外声称的内容与不可声称的内容，供最终项目报告 / PPT 使用。

## 1. 已证明

**L1（机制）**：
`E-0086 → detector alarm → FANOUT_RECHECK_HINT → 一次 regeneration → EX✓`

- Task 20 单例 dry-run 与 Task 21 ON 组均复现；
- Task 21 ON 中 E-0086：initial_ex=false → final_ex=true，regeneration_count=1，repair 未触发。

**L2（审计）**：
Benchmark 内 orders×order_items 双表题全部完成人工审计（Task 17/Task 19：20 条候选），
**未发现真实 FN**（audit_subset_fn_rate = 0/20）。

## 2. 单例机制证据

E-0086（Task 20 单例，DB 直连验证）：

```text
369854.65 → 89397.46          （累计消费金额）
4.137× fan-out → 正确结果     （订单级金额被明细行放大倍数 → 消除）
```

最终 SQL：双 CTE（订单粒度 `SUM(o.total_amount)` + 明细粒度 `COUNT(DISTINCT product_id)` 再 JOIN）。

## 3. 整体 EX 的正确解释

```text
OFF = 90%
ON  = 93%
观测差异 = +3pt
```

其中：

- **E-0086 = +1pt，可归因 Hint**（detector_alarm=true，注入了 FANOUT_RECHECK_HINT，init✗→final✓）；
- **E-0099 / E-0100 = 未触发 Hint**（alarm=false，未注入 hint），其改善来自独立样本随机性。

因此：

> "Hint 提升 EX 3pt" —— **禁止使用**。
> 正确表述：观察到 +3pt 整体差异，其中仅 E-0086 的 +1pt 有 Hint 直接归因证据。

且 OFF/ON 非严格单变量（P1-3：timeout 60s vs 90s；LangGraph+repair vs 线性脚本无 repair；延迟口径不同），
整体结果定位为 **机制层面观测（mechanism-level observation）**，非全局 EX 增益的干净因果估计。

## 4. 统计限制

**alarm sample = 1（E-0086）**

因此**不能声称**：

- 高 Recall；
- 显著预测能力；
- Hint 普遍有效；
- 整体 EX 稳定提升；
- 不会引入回归。

## 5. Detector 已知局限

- **P1-1**：子查询剪枝实现实际未生效，特定标量子查询结构存在误报风险；
- **P1-2**：未限定列名存在真实 Fan-out 漏报盲区（列归属无法可靠确定）；
- **P2-3**：`SUM(DISTINCT orders_column)` 不应简单等价于 Fan-out protection；
- **P2-4**：当前仅覆盖 `orders × order_items`，不是所有 1:N Fan-out。

以上为当前冻结版本已知局限，**不在 E3 内修复**（属下一版本 Detector 工作，见 E3_KNOWN_LIMITATIONS.md）。

## 6. 工程成本

- 单次 regeneration：约 **+8.3s/题**（Task 21 E-0086 实测 regeneration 延迟贡献）；
- 本次观测 alarm rate：**1%**；
- 平均摊薄成本：约 **+0.08s/题**（1% × 8.3s）。

> 注意：这不是大规模成本可接受性的证明（alarm 分布/调用频率可能随题库变化）。

## 7. 最终定位

E3 = **"Gold-independent Fan-out 风险检测 + 条件触发 Hint 的机制验证 / proof of concept"**，

而**不是**："已证明对整体 Text2SQL EX 有稳定提升的完整工程方案"。

---

*冻结日期：2026-09-16；依据 WorkBuddy 独立终审（PASS WITH RESERVATIONS）。*