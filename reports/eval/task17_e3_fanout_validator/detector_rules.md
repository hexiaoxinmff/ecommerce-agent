# Fan-out Detector 规则说明（Task 17 / E3）

模块：`backend/app/sqlcheck/fanout_detector.py`
性质：只读、非干预、静态 AST 分析；不调用 Mimo、不访问数据库、不读 Gold、不修改 SQL、不触发 Repair。

## 1. 目标

识别 SQL 中 "orders × order_items 1:N 直连 + 订单级聚合" 的 fan-out 放大风险。
典型放大：同一订单在多行 order_items 上重复累计，使订单级金额被放大 N 倍。

## 2. 识别模式

| Pattern | 名称 | severity | 触发条件 |
|---|---|---|---|
| A | `order_join_item_order_agg` | high | orders 与 order_items 在同一查询块 FROM/JOIN 直连，且存在对 orders 列的非去重 `SUM/AVG/COUNT`（如 `SUM(o.total_amount)`、`COUNT(o.id)`） |
| B | `count_star_ambiguous` | medium | 上述直连下出现 `COUNT(*)`/`COUNT(1)`，无法从 AST 区分是"订单数"还是"明细数" |
| - | `order_join_item_order_agg(protected)` | low（不报警） | 直连下订单级聚合采用 DISTINCT（如 `COUNT(DISTINCT o.id)`），视为去重保护 |

## 3. 不应误报的情况（不判 fan-out）

- 聚合值列为 order_items 粒度：`SUM(oi.subtotal)`、`SUM(oi.quantity)`、`SUM(oi.unit_price * oi.quantity)`；
- `CASE WHEN ... THEN <item列>` 的值分支聚合明细列（订单列仅出现在条件里——只过滤不放大）；
- `COUNT(DISTINCT orders主键/日期)` 去重保护；
- `MIN/MAX(orders列)`（重复行不改变最值）；
- orders 在独立 CTE/子查询完成订单级聚合后再 JOIN（不同查询块，无双表直连）；
- order_items 仅出现在 EXISTS 子查询中；
- 完全无 orders×order_items 直连（如 users×orders、单表聚合）。

## 4. 关键实现点

- 对每个查询块（`exp.Select`）独立分析，只取该块 FROM/JOIN 直接引用的表（不递归进子查询/CTE）；
- 聚合提取限制在该块的投影/HAVING 内，不跨子查询；
- CASE 处理：只遍历 THEN（`If.args["true"]`）/ELSE（`default`）值分支，条件列不计入聚合维度；
- distinct 判定：`agg.this` 为 `exp.Distinct` 即去重；
- 输出 `FanoutDiagnosis`；`fan_out_suspected` 仅在存在非保护的高/中风险时为 True。

## 5. 使用方式（观察模式，不做 hard gate）

```python
from app.sqlcheck.fanout_detector import analyze_fanout
diag = analyze_fanout(pred_sql)
# diag.fan_out_suspected / diag.severity / diag.patterns / diag.evidence / diag.detection_reason
```

本阶段仅离线观察；后续可接入 Agent（作为轻量提示或校验），但接入属新增系统改动，需总顾问决策。