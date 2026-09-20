# Task 17 / E3 离线静态扫描报告（Fan-out Detector）

> 扫描对象：Clean Baseline（v1.1 / V1.3 / FEWSHOT_V3）100 条 Pred SQL（final_sql，缺失时回退 initial_sql）
> 检测器：`backend/app/sqlcheck/fanout_detector.py`（只读、非干预、不读 Gold）
> 运行命令：`python scripts/scan_fanout_report.py`

## 1. 扫描结果总览

| 统计 | 值 |
|---|---|
| 扫描条数 | 100 |
| fan_out_suspected = True | **1（E-0086）** |
| severity=high | 1（E-0086） |
| severity=medium | 0 |
| severity=low（protected，不判风险） | 3（E-0073/E-0097/E-0100） |
| severity=none | 96 |
| EX✓ 中报警 | 0 |

## 2. 关键正例：E-0086（必须回答的 4 问）

1. **是否被识别**：是。`fan_out_suspected=True, severity=high`。
2. **命中的 pattern**：`order_join_item_order_agg`。
   - evidence：`orders 表与 order_items 表在同一查询块直连（JOIN/FROM），1:N 连接存在`；`订单级聚合 SUM(o.total_amount)`。
3. **为什么属于风险**：`WITH user_stats AS (SELECT ... SUM(o.total_amount) AS total_spent ...
   FROM users u JOIN orders o ... JOIN order_items pi ON o.id = pi.order_id GROUP BY u.id, u.username)`。
   orders→order_items 为 1:N，同一订单 N 行明细使 `SUM(o.total_amount)` 重复累计（实测黄冬梅 369854.65 vs Gold 89397.46，约 4.1×）。订单数与 SKU 数用 COUNT(DISTINCT) 已保护、未报警，**只有金额被放大** → 正是经典 fan-out。
4. **是否 Gold-independent**：是。`analyze_fanout(sql)` 签名只有 `sql` 一个参数；检测依据完全来自 Pred SQL 自身的表连接与聚合结构，未读取任何 Gold/期望列/标签。

## 3. 已知负例（不应误报）—— 来自 Task 16 人工归因的 9 个非 fan-out Bad Case

| 题 | 实际根因（Task16） | 检测器结果 | 判定 |
|---|---|---|---|
| E-0057 | CASE 边界/实体选择 | none | ✓ 无误报 |
| E-0077 | Schema Linking 缺表 | none | ✓ 无误报 |
| E-0082 | 输出列契约（值对、少列） | none | ✓ 无误报 |
| E-0083 | 输出列契约（值对、少列） | none | ✓ 无误报 |
| E-0090 | 过滤/结构/口径复合 | none | ✓ 无误报 |
| E-0095 | 第二层平均基准（过滤未前置） | none | ✓ 无误报 |
| E-0096 | Gold 金额口径冲突 | none | ✓ 无误报 |
| E-0099 | 别名引用 bug（sql_repair） | none | ✓ 无误报 |
| E-0100 | Gold 金额口径冲突 | low（protected，不判风险） | ✓ 无高/中报警 |

> E-0100 的 pred 含 `COUNT(DISTINCT CASE ... THEN o.id END)` 与 `SUM(oi.subtotal)`：
> 订单级计数已 DISTINCT 去重（low/protected），金额聚合为明细粒度 → 正确不判为 fan-out。

## 4. 已知正例

| 题 | 标签来源 | 检测器 | 判定 |
|---|---|---|---|
| E-0086 | Task14.3 人工确认的经典 fan-out | high → 报警 | ✓ TP |
| E-0073 / E-0097 | 结构含订单级 DISTINCT 计数（EX✓） | low(protected) | ✓ 正确保护 |

## 5. Precision / Recall 可计算性

**结论：不能可靠计算完整的 Precision/Recall。**

原因：Clean Baseline 100 条中**只有 E-0086 被明确标注为 fan-out 正例**（Task 14.3 人工论证）；
其余 99 条没有逐条人工"fan-out 标签"，无法构造可靠的"真负例"集合。
用 Gold 做标签**不可行**且本轮禁止（Gold-independent 是硬约束）。因此：

- **可报告的确定性结论**（标签可从已审计材料获得的部分）：
  - TP（已知正例命中）：1/1 → 已知正例 Recall = 100%（样本 n=1）
  - FP（已知负例误报）：0/9
  - EX✓ 的 90 条中 0 条被报警（无新增噪声信号）
- **不可构造**：完整 confusion matrix、Formal Precision/Recall（正负例标签不足，伪造会误导）。

## 6. 误报 / 漏报观察（无法定论的部分）

- **潜在误报兜底**：severity=medium（COUNT(*) 意图不明）在 100 条中为 0 次 → 该模糊分支当前无实际影响；
- **潜在漏报（未审计）**：E-0059/E-0061/E-0062/E-0067/E-0074/E-0080/E-0085/E-0087/E-0088/E-0089/E-0093/E-0095/E-0096/E-0098/E-0099
  等 15 条虽含 orders×order_items 直连但未被报警（多为 item 粒度聚合或 DISTINCT 保护），
  其中 90% 属于 EX✓（人工抽查均为安全模式），无法排除个别边界；如需完整 Recall 需逐一人工审计这 15 条。
- 说明：本检测器**只覆盖经典 fan-out（1:N 直连+订单级非去重聚合）**，不覆盖
  过滤遗漏/口径冲突/两阶段基准等其它失败类型（这些由 E9/E10/E11 候选负责）。

## 7. 单元测试

`backend/tests/test_e3_fanout_detector.py`：**12 条全部通过**（覆盖任务书 §八 五个用例 +
E-0086 正例 + COUNT(DISTINCT) 保护 + CASE 值/条件分支正反例 + 解析失败容错 + Gold-independent 签名校验）。
全量 pytest：**352 passed**（新增 12）。