# E3 Known Limitations（未来 Detector 版本工作）

> 本文件记录当前冻结版 Fan-out Detector（`backend/app/sqlcheck/fanout_detector.py`）的已知局限。
> 依据 WorkBuddy 独立终审（P1-1 / P1-2；P2-3 / P2-4）。
> **这些属于"下一版本 Detector"的工作，不修改当前冻结版**，以免污染已完成实验版本。

## P1-1：子查询剪枝未生效（误报/漏报风险）

- **现象**：`_select_has_metric_aggregations` 与 `_collect_agg_columns` 在遍历聚合表达式时，
  `exp.Subquery` 的剪枝逻辑未覆盖全部路径（例如窗口函数 / EXISTS 子查询内部、深层 `CASE` 分支嵌套），
  特定标量子查询结构下会被当成本查询块内的列引用 → 可能误报。
- **影响**：特定结构下 alarm 判定可能不正确（倾向误报）。
- **修复方向（下一版）**：用 sqlglot scope 分析替换手工 walk，区分"本查询块 FROM/JOIN 表"与"子查询内部表"。

## P1-2：未限定列名的归属盲区（漏报）

- **现象**：聚合参数中的 `Column` 若无表格限定符（如 `SUM(total_amount)` 而非 `SUM(o.total_amount)`），
  `_col_table()` 返回空串，`table_map` 中查不到 → 归类为 `other` → **不报警**（漏报盲区）。
- **影响**：真实 Fan-out 风险可能因列未限定而被漏掉。
- **修复方向（下一版）**：引入 schema/CTE 列名 → 表映射做归属推断；或对"未限定列名 + 直连"保守标记 medium。

## P2-3：`SUM(DISTINCT orders_column)` ≠ Fan-out protection

- **现象**:当前对 `COUNT(DISTINCT orders主键/order_date)` 视为去重保护（不报警）；但 `SUM(DISTINCT orders金额列)`
  同样走 "distinct → protected" 分支，而 `SUM(DISTINCT total_amount)` 并非合法防 fan-out 手段
  （金额列取值本身不重复，DISTINCT 不能消除 join 产生的重复行对 SUM 的影响）。
- **影响**：可能把本应报警的结构误认为安全。
- **修复方向（下一版）**：仅对 COUNT(主键/维度键) 类 DISTINCT 视为保护；SUM/AVG DISTINCT 不豁免。

## P2-4：仅覆盖 orders × order_items

- **现象**：当前 Detector 只识别 `orders` 与 `order_items` 直连下的粒度风险；
  其他 1:N Fan-out（如 orders × 其他明细表、category 层级展开等）未覆盖。
- **影响**：非本 Benchmark 主模式的 fan-out 不在检测范围内。
- **修复方向（下一版）**：将"维表/FK 关系 + 聚合粒度"泛化，支持表元数据驱动的 1:N 检测。

---

*冻结日期：2026-09-16。当前位置：主仓库（非 worktree master-b947f329）。*