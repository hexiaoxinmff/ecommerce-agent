# Task 16：Candidate E8 — Output Shape Validation（生成后结构校验）静态可行性研究

> 范围：只做设计与静态可行性分析；**不修改 Agent / Safety / Repair / Benchmark**。
> 研究对象：SQL Generator 之后、Safety/Execution 之间的"轻量生成后校验"可增加什么。

---

## 1. 现状：现有 SQL 校验链路（只读）

```text
SQL Generate ──► sqlgen.safety.check_sql_safety（sqlglot：单条 SELECT/WITH、禁写操作）
             ──► sqlexec.executor.execute（check_sql_safety 再校验 + 只读 DB 执行）
             ──► evaluation.normalization.compare_results（列数 D1 / 行集合 / 值比较）
```

`check_sql_safety`（[safety.py](file:///f:/基于%20Text2SQL%20的电商智能数据分析%20Agent/backend/app/sqlgen/safety.py)）当前只做：SQLite 方言可解析、单条语句、顶层 SELECT/WITH、无写操作节点。
**它不检查**：列限定符别名是否定义/存在、SELECT 输出列的数量与语义形状、WHERE/HAVING 是否包含题面显式条件。

---

## 2. E8 想拦截什么（与 10 个 Bad Case 的对照）

| 候选拦截点 | 拦截目标 | 对应 Bad Case | 纯静态（不调 LLM）可行性 |
|---|---|---|---|
| P1 列限定符（表别名）引用合法性 | `r.region` 这类"别名不存在/未定义"的列引用 | E-0099（`no such column: r.region`） | **高**（sqlglot 解析 + 作用域别名集合比对） |
| P2 输出列形状契约 | 输出列数量/必须列（维度列+指标列）对齐问题 | E-0082/E-0083（缺 label 列）、E-0090（缺 total_cnt） | **中**（需题目侧"期望形状"元数据，见 §4） |
| P3 显式过滤条件保持 | 题面显式条件（2025年/30000/窗口）在 SQL 中的存在性 | E-0090（缺 2025 过滤）、E-0095（缺 30000 前置过滤） | **低**（需要 NL→SQL 条件映射，纯静态不足） |

**E-0099 单独分析**（§D）：
- 生成 SQL 中 SELECT 用 `r.region`，但 CTE `region_sales` 的别名是 `rs`；`r` 未在任何 FROM/JOIN/CTE 中定义。
- 纯静态可检测：解析后收集所有作用域内可用的表别名 + CTE 别名集合，遍历投影列/WHERE/JOIN 条件的 `exp.Column` 限定符，发现 `r` 不在集合内 → 拦截。**不需要执行 DB、不需要 LLM**。
- Repair 为什么没修掉：Repair 生成的 SQL 仍有未定义字段引用（说明 Repair 的生成结果也需要同一道校验拦截，或 Repair 校验滞后）。
- 结论：E-0099 类错误是"生成层引用 bug"，**值得作为 E8 的 P1 子功能**；但当前只有 1 例 → 若独立立项收益低，建议作为 E8 附带能力。

---

## 3. P2（输出形状）的可行性核心判断

### 3.1 关键结论：**纯静态（无题目元数据）无法判"少一列"**

E-0082/E-0083 的失败本质："数值全对、只是少输出 label 列"。模型在 SELECT 阶段就只选了 1 列（`percentage`）。
- 语法层：`SELECT ROUND(...) AS percentage` 是完全合法单列查询 → sqlglot 无法知道"应该还有一列 c.name"。
- 语义层："应该输出哪几列"恰好是**题目->期望结果的约定**，这个约定存在 Benchmark 的 `answer_slots` / Gold 输出形状里。

### 3.2 要让"不调 LLM 也能查列数"成立，必须给校验器一项**题目侧契约**

设计（不修改正式 Benchmark，独立实验内以 sidecar 提供）：

```json
{
  "eval_id": "E-0082",
  "expected_output": {
    "full_schema": ["categories.name", "pct"],
    "min_columns": 2,
    "required_dimension": ["categories.name"],
    "required_metrics": ["pct"]
  }
}
```

校验器拿到契约后，对生成 SQL 做：
1. sqlglot 解析出 `SELECT` 投影列集合（`selects`）+ parent alias；
2. 与 `min_columns` / `required_dimension` / `required_metrics` 比对，缺失 → 拦截并进入 Repair / 要求重建；
3. 列数与形状达标才放行到执行。

**可行性结论**：
- 技术上可行、成本低（纯 sqlglot + 契约文件，不执行 DB、不依赖 LLM）；
- 但**契约必须由人/基准侧给出**——相当于把"Gold 输出形状"翻译成机器可读契约，**这属于 Benchmark 元数据扩展**，本任务禁止修改 Benchmark → 只能作为 sidecar 实验文件；
- 且契约只覆盖"列数量/必需列"这一类（E-0082/0083/0090 的结构层），**覆盖不了 E-0095/E-0090 的过滤条件遗漏（P3）**（除非同时维护"题面显式条件 -> SQL 谓词"映射，那需要 NLP 级别能力，非静态）。

### 3.3 静态可做、且零猜想的子集

即使没有题目契约，P1（列引用/别名/CTE 引用校验）与"输出列数=0 或空投影"等纯结构错误是**零误报可做**的。这可以在 Safety 阶段低成本加一层（不影响任何正式文件，独立实验内接线）。

---

## 4. E8 最小范围建议（供实验矩阵）

**Candidate E8（保持单变量）**：
- 新增一个独立校验函数 `check_output_shape(sql, contract) -> list[Issue]`（sqlglot 实现，纯静态）；
- 接线点：SQL Generate 后 → `check_sql_safety` 通过后 → Shape 校验 → 任一项不通过即进入 Repair（或要求重新生成）；
- 契约来源：独立 sidecar 文件 `reports/eval/task16/contracts_e8.json`（**不修改** `ecommerce_eval_v1.json`）；
- 同时包含 P1 别名/引用校验（零误报子集，对所有题通用）。

**不建议做**：
- P3 过滤条件保持（需要 NL 条件映射，非静态范畴）；
- E8 默认全量启用在生产 Agent（先实验验证）。

---

## 5. 风险

- 契约文件若与 Gold 失真（e.g. 某些题的期望形状与我对 Gold 的解读不一致）→ 误拦正确 SQL、损伤 EX；
- Repair 触发率上升 → 延迟上升（若 E8 拦截过多）；需统计 Repair Trigger 变化；
- sidecar 契约的制作成本 = 100 题 × 形状标注（可只标注目标题 E-0082/E-0083/E-0090）；
- P1 别名校验扩展到 CTE 复杂的正确 SQL 时需小心（作用域解析要处理嵌套 CTE/窗口），存在误报风险 → 用 100 题回归验证零误报。