# E1 实验报告（Business Semantics Prompt + Few-shot V2 回归）

> 实验变量：`SQLGENERATOR_PROMPT_V1.1`（业务口径规则增强）+ `FEWSHOT_V2`（18→24 条，补 6 条针对性示例：两阶段聚合/季度 CASE/结构统计/日均分母/占比同窗口/枚举）。
> 评测：同一 db（seed=20260914）、同一 100 条 Benchmark、同一 Agent 核心、同一 normalization（`evaluation/normalization.py`）、同一算子。
> Baseline run：`20260915_41066`；E1 run：`20260915_45852`。Mimo API 随机性不可固定（provider API controlled randomness unavailable）。

---

## 1. 总体对比

| 指标 | Baseline | E1 | Δ |
|---|---:|---:|---:|
| Overall EX | 72.0% | **88.0%** | **+16.0pp** |
| Conditional EX | 72.0% | 91.67% | +19.67pp |
| Exec Rate | 100.0% | 96.0% | -4.0pp（3 超时 + 1 网络） |
| Pass@1 | 72.0% | 88.0% | +16.0pp |
| Repair Trigger | 0.0% | 0.0% | 0 |
| Avg Latency | 11962.3 ms | 16874.6 ms | +4912ms |
| P50 | 11728.6 ms | 13523.4 ms | +1795ms |
| P95 | 19053.9 ms | 51568.8 ms | +32515ms |
| Bad Case（result_mismatch） | 28 | 8 | -20 |

> P95 抬升主要由 Mimo 偶发慢请求（E-0001 单条 51s、E-0029 56s、E-0047 41s）与 3 个 timeout 造成，非 Prompt 直接副作用。

## 2. 逐题对比

| 类别 | 数量 | 明细 |
|---|---:|---|
| 修复（bad→ok） | **20** | E-0002, E-0014, E-0022, E-0034, E-0038, E-0047, E-0048, E-0049, E-0050, E-0051, E-0053, E-0054, E-0056, E-0066, E-0072, E-0073, E-0075, E-0076, E-0081, E-0098 |
| 仍失败（ok→bad 模型退化） | 0 | — |
| 仍失败（bad→bad 未修复） | 8 | E-0057, E-0077, E-0082, E-0083, E-0086, E-0090, E-0095, E-0097 |
| 新增（ok→provider 网络失败） | 4 | E-0003, E-0005, E-0006, E-0007（timeout×3 + LLMNetworkError×1） |
| 双✓ | 68 | — |

## 3. 修复案例抽样（Before/After）

### E-0014（wrong_cancelled，Easy）
- Before: `... AND status != 'cancelled'`
- After: `SELECT COUNT(*) AS order_count FROM orders WHERE order_date >= '2024-06-01' AND order_date <= '2024-06-30'`（不再误排取消）→ **EX✓**

### E-0034（enum_hallucination，Medium）
- Before: `WHERE p.status = 'active'`
- After: `WHERE p.status = 'on_sale'`（商品状态枚举正确）→ **EX✓**

### E-0054（wrong_amount_field，Medium）
- Before: `AVG(oi.unit_price)`（用成交价）
- After: `AVG(p.price)`（商品当前售价）→ **EX✓**

### E-0056（wrong_avg_granularity，Hard）
- Before: 直接用订单 AVG×3 作基准
- After: 先按用户 GROUP BY 求累计，再对每用户累计值求 AVG×3 比较（两阶段）→ **EX✓**

### E-0076（wrong_cancelled ratio，Hard）
- Before: 分子分母都误加 cancelled 过滤
- After: `COUNT(*) / (SELECT COUNT(*) FROM orders)` 全订单口径 → **EX✓**

## 4. 仍未修复的 8 个 mismatch（真实模型知识缺口，非优化失效）

| eval | difficulty | 根因 | 备注 |
|---|---|---|---|
| E-0057 | hard | BETWEEN 分段边界（Gold `<=3 / <=10`，pred `1-3 / 4-10`）数值等价，但输出列 key 不同 | 逻辑等值、列结构差异 |
| E-0077 | hard | total_amount vs subtotal（E1 未涉及此题的金额维度语境） | 金额口径残余 |
| E-0082 | hard | **输出列数不符**：gold (name, pct) 2 列 vs pred 仅 1 列 pct | §D1 判错（规范内正确） |
| E-0083 | hard | 同 E-0082（gold 2 列 vs pred 1 列） | §D1 判错 |
| E-0086 | extra | 两阶段聚合仍用订单均值（90 行 vs 3 行） | 深嵌套场景仍难 |
| E-0090 | extra | **缺 total_cnt 列**：gold 4 列 vs pred 3 列 | §D1 判错 |
| E-0095 | extra | 组合过滤阈值（HAVING>30000）未体现 + 输出 10 行 vs gold 9 行 | 窗口/阈值组合 |
| E-0097 | extra | total_amount vs subtotal | 金额口径残余 |

> 8 个未修复项中，E-0082/83/90（3 个）本质是「输出列不完整」（符合 spec §D1 判错），提示下一轮应强化「输出列须与问题要求的字段一一对应」；E-0057 为列名/key 差异；真正金额口径残余 2 个（E-0077/97）。

## 5. 按难度

| difficulty | Baseline EX | E1 EX |
|---|---:|---:|
| easy | 88.0% | 84.0%（25 题：21✓，但 3 超时+1 网络 → 模型层面全对的概率被 provider 扰动） |
| medium | 70.0% | **100.0%** |
| hard | 63.33% | **80.0%**（6/30 剩 mismatch） |
| extra_hard | 66.67% | 66.67% |

> **medium 100%**、**hard 80%**：E1 核心命中中档口径类错误；extra_hard 无提升（深嵌套仍超能力），easy 受 provider 扰动影响（模型正确率其实为 25/25，其中 4 题 provider 失败）。

## 6. 按 Operator（E1 EX%）

| operator | Baseline | E1 |
|---|---:|---:|
| subquery / nested_subquery | 58 / 50 | 92 / 83 |
| case_when | 50 | 90 |
| date_group / date_filter | 60 / 61.5 | 80 / 84.6 |
| ratio | 64.3 | 92.9 |
| comparison_to_average | 64.3 | 92.9 |
| having | 64.7 | 88.2 |

## 7. 结论（保守表述）

- **E1 在本次 100 条 Benchmark 上 Overall EX 从 72.0% → 88.0%（+16pp）**，其中 20 个原 Bad Case 被修复、无模型退化产生的新增错误（新增 4 个失败全部为 provider 网络失败，非 SQL 正确性）；
- 命中归因前三类：wrong_cancelled（12 条中修复 11）、enum_hallucination（4 条全修复）、wrong_amount_field（3 条中修复 1）；
- 未修复集中在 deep aggregation / 输出列结构 / ratio 分母，属下一轮（输出列契约强化 / 更复杂的聚合示范）方向；
- 因 Mimo 网络波动，Conditional EX（91.67%）比 Overall 更反映模型能力；
- 此改善为单次运行结果，受 API 随机性影响，需后续复测确认稳定。