# ECO-SQL-Bench 评测集数据规范（Evaluation Dataset Specification)

> 阶段：Phase 5 · Task 11
> 日期：2026-09-15
> 作者：TRAE 开发 Agent
> 状态：设计定稿，等待总顾问验收
> 关联文档：`docs/evaluation-plan.md`、`docs/evaluation-matrix.md`、`docs/database-schema.md`、`data/eval/README.md`
> 权威文件：`data/eval/ecommerce_eval_v1.json`、`data/eval/ecommerce_multiturn_v1.json`、`data/eval/bad_cases/`

---

## A. 总体原则

1. **Execution Accuracy（EX）为主指标**：pred SQL 与 gold SQL 在**同一数据库（db/ecommerce.db）**上执行，结果一致即判对；SQL 文本、列顺序、alias、格式的合理差异不构成失败（对齐 Spider 思想）。
2. **Gold 质量 > 数量**：Gold SQL 必须经过人工审核 + 真实执行 + hash 固化，未验证的 LLM 输出禁止入集。
3. **可复现**：数据库固定 seed=20260914，评测环境锁依赖、记模型快照，脚本一键重跑。
4. **可归因**：每题可定位错误环节（Schema Linking / Few-shot / 生成 / 校验 / 执行），Bad Case 自动沉淀反哺。

---

## B. 数据 Schema

### B1. 单轮条目（主 Benchmark）

```json
{
  "id": "E-0001",
  "split": "eval",
  "difficulty": "easy",
  "scenario": "user_analysis",
  "operators": ["group_by", "count"],
  "question": "哪个地区的用户最多？",
  "gold_sql": "SELECT region, COUNT(*) AS user_count FROM users GROUP BY region ORDER BY user_count DESC",
  "gold_result_hash": "sha256-hex",
  "expected_behavior": "answer",
  "answer_slots": {
    "value_type": "category",
    "tolerance": null
  },
  "multi_turn": null,
  "notes": ""
}
```

**字段定义总表（类型 / 是否必填 / 合法取值 / 作用）**：

| 字段 | 类型 | 必填 | 合法取值 | 作用 |
|---|---|---|---|---|
| `id` | string | 是 | `E-\d{4}`（如 E-0001），全局唯一 | 条目唯一标识，跨版本不重用 |
| `split` | string | 否 | `eval / dev / train`，默认 `eval` | 数据集分区 |
| `difficulty` | string | 是 | `easy / medium / hard / extra_hard` | 难度分级（规则见 §G） |
| `scenario` | string | 是 | 枚举见矩阵文档 §3（12 个） | 业务场景标签 |
| `operators` | string[] | 是 | 非空、无重复；成员 ∈ operators 枚举（矩阵文档 §4） | SQL 能力标签，供覆盖统计与误差归因 |
| `question` | string | 是 | 非空；不能与既有 question 重复 | 自然语言问题 |
| `gold_sql` | string | 是 | 非空；只读 SELECT/WITH；表/列真实存在；真实库可执行 | 基准答案 SQL |
| `gold_result_hash` | string | 是 | 64 位 sha256 hex（§C 算法生成） | 防数据/基准漂移 |
| `expected_behavior` | string | 是 | `answer / clarify / refuse` | 期望行为（见下） |
| `answer_slots.value_type` | string | 否 | `scalar_number / integer / ratio / currency / category / ranking / date / text / boolean / empty` | 结果值语义，决定核验方式 |
| `answer_slots.tolerance` | number | 否 | ≥ 0（比率类建议 0.01） | 数值/浮点比较容差（规则见 §D） |
| `answer_slots.expected_empty` | boolean | 否 | `true / false`，默认 `false` | 显式声明"合法空结果"，见 §D 空结果 |
| `answer_slots.order_sensitive` | boolean | 否 | `true / false`，默认随 value_type | 行顺序是否属于答案一部分（Top-N/排名默认 true） |
| `multi_turn` | null | 否 | 恒为 null（单轮主集） | 多轮题进入多轮文件 |
| `notes` | string | 否 | 自由文本 | 审核备注/口径说明 |

**`expected_behavior` 语义**：
- `answer`：必须有 gold_sql 且可判定 EX；
- `clarify`：题目存在歧义，期望 Agent 反问澄清——**不要求 gold_sql 可判定**（仍建议给参考 SQL 供人工比较），不计入 EX 分母而计入"澄清正确率"；
- `refuse`：超出数据域，期望合理拒答，不计入 EX。

> **歧义保护**：`clarify` 条目不参与 EX 判定，**不得强迫模型对歧义问题胡乱生成 SQL**；评测时出现的澄清动作计为正确行为。

**`answer_slots.value_type` × 核验方式（不要求所有题用同一校验方法）**：

| value_type | 推荐核验字段 | 核验方式 |
|---|---|---|
| `scalar_number` | `tolerance` | 数值归一化后带容差比较 |
| `integer` | — | 整数精确比较（索引类不做浮点转换） |
| `ratio` | `tolerance`（建议 0.01） | 归一化为小数后带容差比较 |
| `currency` | `tolerance`（建议 0.01） | 金额 round(2) 后带容差比较 |
| `category` | — | 分类集合等价比较（顺序不敏感） |
| `ranking` | `order_sensitive=true` | 集合 + 顺序逐位比较（见 §D Top-N） |
| `date` | — | ISO 字符串精确比较 |
| `text` | — | 字符串精确比较 |
| `boolean` | — | 布尔精确比较 |
| `empty` | `expected_empty=true` | 显式声明空结果为合法答案（见 §D 空结果） |

### B2. 多轮条目

```json
{
  "conversation_id": "C-001",
  "turns": [
    {
      "turn_id": 1,
      "previous_turn_id": null,
      "question": "...",
      "gold_sql": "...",
      "gold_result_hash": "...",
      "expected_context": {
        "dependency": "none"
      }
    }
  ]
}
```

- `turn_id` 从 1 递增；`previous_turn_id` 指向上一轮（首轮为 null）；
- `expected_context.dependency` 枚举见矩阵文档 §8；
- `expected_context.context_operations`：**可选**（首轮可省略或为 `[]`），列表形式显式声明本轮对上文所做的语义操作，供评测判断"上下文依赖轮"是否真正继承/变更条件：

  ```text
  inherit_condition   继承上轮条件（时间窗/地区/状态等）
  add_filter          追加筛选条件（如"只看华南"）
  change_group        改变分组维度（如"按类别"→"按地区"）
  remove_condition    删除某条件
  modify_time_range   修改时间范围
  reference_previous  指代上轮对象/结果（"那个品类"）
  ```

- 每轮均有独立 `gold_sql` / `gold_result_hash`（多轮按"上一轮语义继承"构造，审核时校验 `context_operations` 与 gold_sql 之间的继承一致性）。

### B3. Bad Case 条目

```json
{
  "case_id": "B-0001",
  "eval_id": "E-0023",
  "question": "...",
  "gold_sql": "...",
  "pred_sql": "...",
  "failure_stage": "sql_generation",
  "error_type": "missing_join",
  "trace": "...",
  "repair_count": 0,
  "notes": ""
}
```

- `case_id` 唯一（B-0001 起）；`eval_id` 关联主集条目；
- `failure_stage` 枚举：`schema_linking / fewshot_retrieval / sql_generation / sql_validation / sql_execution / result_analysis`；
- `error_type` 允许扩展，但每新增一类必须先登记到本文件附录；
- `repair_count`：进入修复循环的次数（Repair 能力落地前为 0）。

---

## C. Gold Result Hash 规范

**目的**：防止 Gold SQL 或数据库变动导致测试基准漂移。

**算法**（稳定序列化 + SHA-256）：

```text
1. 在 db/ecommerce.db 上只读执行 gold_sql；
2. 取结果 columns（有序列表）与 rows；
3. 归一化：
   - None → "<null>"
   - float → round(v, 6)（统一数值精度，消除浮点噪声）
   - 其余原样
4. 将每行归一化后转为元组，对所有行按「json 序列化字符串」排序（hash 仅用于防漂移，
   行顺序不纳入 hash；顺序语义由 EX 比较阶段单独处理）；
5. 稳定序列化：json.dumps({"columns": [...], "rows": [...]}, ensure_ascii=False,
   sort_keys=False, separators=(",", ":"))；
6. 计算 SHA-256 得到 64 位 hex。
```

- 规范化函数 `normalize_result_hash(columns, rows)` 在 `scripts/validate_eval_dataset.py` 中实现并单测覆盖；
- 校验脚本支持 `--verify-hashes`：重跑 gold_sql 重新计算 hash 并与记录比对，不匹配报错（防漂移闸门）。

**序列化规则要点**：数字统一 `round(x, 6)`；字符串不做 strip；列顺序即查询返回顺序。

---

## D. 结果归一化与验证规范（EX 判定）

> EX 判定 = gold 结果 ⇋ pred 结果 在**同一数据库**上执行后的语义等价比较。以下规则是 Runner（Task 12+）必须实现的归一化口径，本规范为权威定义。

### D1. 列名 / alias

- 比较时**不区分列名与 alias**（`COUNT(*) AS c` 与 `COUNT(*) AS user_count` 等价）；
- 但列**数量与语义位置**必须可比（gold 有 2 列、pred 只有 1 列 → 不等价）。

### D2. 列顺序

- **不敏感**：结果按"列名 → 值"映射后再比较，允许 pred 交换 SELECT 列顺序；
- `gold_result_hash` 记录列顺序仅用于审计，不参与 EX 判定。

### D3. 行顺序

- 题面含 `ORDER BY`（或语义要求排序，如 Top-N/排名）→ **顺序属于答案的一部分**，按 gold 顺序逐行比较；
- 题面无排序要求 → **集合等价**：执行"排序后比较"，行顺序任意；
- 判定开关：`answer_slots.order_sensitive`（`ranking` 默认 `true`，其余默认 `false`）。

### D4. NULL

- `NULL = NULL`（行内对齐比较）；
- `NULL ≠ 0`、`NULL ≠ ""`、`NULL ≠ 'None'`；
- gold/pred 同一单元格一个为 NULL 一个非 NULL → 不等价。

### D5. 数值（integer / float / decimal）

- `integer`：先转 int 再精确比较；
- `float / REAL`：比较前 `round(v, 6)`，**禁止把浮点转字符串比较**；
- 金额（`currency` / 销售额）：`round(v, 2)` 后比较；
- SQLite 中 `REAL` 一律按浮点规则处理，不依赖存储精度。

### D6. 浮点误差 / tolerance

```text
ratio 类 ：|pred - gold| ≤ gold * tolerance          （相对容差）
currency ：|pred - gold| ≤ max(0.01, gold*tolerance) （绝对/相对取较大）
scalar   ：round(pred, 6) == round(gold, 6) 或按 tolerance
```

- `tolerance` 缺省时为 **0**（精确比较）；
- tolerance 属于**条目级**配置，写在各题 `answer_slots`，不是全局常量。

### D7. Top-N / 排名（集合 + 排序双验证）

```text
① 集合验证：pred 的 Top-K 集合 == gold 的 Top-K 集合；
② 顺序验证：逐位比较排序键（值或名次），允许并列时顺序不确定性
            → 并列键内部顺序忽略，仅要求 排序键(名次) 序列一致；
③ 不得只验证第一名。
```

- 题面未指明 N（如"销量最高的商品"）→ N=1，仍走 D3 排序比较。

### D8. 空结果（expected_empty 机制）

- **合法空结果**：SQL 正确、题目语义允许空（如"2023 年 1 月（无订单）有多少订单？"）→ 条目必须显式声明 `answer_slots.expected_empty = true`，此时 gold 空结果按正确通过；
- **错误空结果**：问题明显应有数据（如"总销售额是多少"）却返回空 → 判定 gold/pred 逻辑错误，先人工复核，不直接判对；
- **pred 空 vs gold 非空**：一律判错；
- 判定默认值：未声明 `expected_empty` 时按 `false` 处理（gold 空结果即视为基准异常）。

### D9. 汇总表

| 结果类型 | 验证方式 |
|---|---|
| 单值（总销售额/平均价格/用户数） | 归一化 + 数值 tolerance（§D5/D6） |
| 数字 / 浮点 | `round(v, 6)` 后比较；**禁止字符串直接比较**浮点 |
| 比率 / 占比 | 必须定义 `tolerance`（建议 0.01） |
| 排名 / Top-N | 集合 + 排序双验证（§D7） |
| 多行非排名 | 行规范化后升序排列比较（集合等价） |
| 空结果 | `expected_empty=true` 才判对；否则人工复核（§D8） |
| 分类 / 日期 / 文本 | 归一化后精确比较 |

> 具体如何实现以上规则属评测 Runner（Task 12+）职责；本规范只定义口径，不允许各实现意见不一致。

---

## E. SQL 入集硬性校验（每个 gold_sql 必须满足）

1. 只读：顶层 `SELECT / WITH`（sqlglot SQLite 方言解析，单语句）；
2. 表/列存在：引用的表、列 ∈ 真实 Schema（`SchemaCatalog`）；
3. 可执行：在 `db/ecommerce.db` 只读连接（`mode=ro` + `PRAGMA query_only=ON`）上执行成功；
4. 业务口径：涉及"实际销售"类指标时正确排除 `cancelled`；金额字段语义符合 database-schema.md §4；
5. 结果合理性：问题明显应有结果时，gold 结果不允许为空；确无合理数据时人工复核并标注。

---

## F. 去重规范（三类同时检查）

| 类型 | 定义 | 处理 |
|---|---|---|
| 完全重复 | question 完全相同 | 直接删除 |
| 语义重复 | 问法不同但 SQL/逻辑/测试目的基本一致 | 每难度档保留 1~2 条代表，其余删除 |
| 模板重复 | 仅替换常量（地区/分类/日期）而逻辑完全一致 | 每模板最多 2~3 条，其余删除 |

---

## G. 难度分级（与矩阵文档 §6 一致，禁止主观标注）

> 除 SQL 结构/业务口径外，各难度还有 **operator 禁止项**（矩阵文档 §7.3，validator 强制执行）：
> Easy 禁止 subquery/join/group_by 等；Complex 标签逐难度放开。难度分级由"允许集 + 禁止集"共同定义。

| 级别 | SQL 结构 | 业务口径 |
|---|---|---|
| easy | 单表 / 简单 WHERE / 简单聚合 / 简单 ORDER/LIMIT | 单一口径 |
| medium | GROUP BY / 简单 HAVING / 2 表 JOIN / 日期过滤 / Top-N | 明确一种口径 |
| hard | ≥3 表 JOIN / GROUP BY+HAVING / 单层子查询 / 时间+聚合 / 多维 | 口径判断 + 条件组合 |
| extra_hard | 多级 JOIN / 嵌套子查询 / 复杂聚合 / 多业务条件 / 复杂时间 | 口径权衡 + 强 Schema Linking |

---

## H. 生成与审核流程（Gold SQL 禁止 AI 直接入集）

```text
① 人工设计问题（含场景/难度/operator 标签）
        ↓
② 候选 Gold SQL
        ↓
③ 真实项目 SQLite 执行
        ↓
④ 检查 SQL 逻辑（表/列/JOIN/聚合/口径）
        ↓
⑤ 人工核对结果（数字、行数、边界值、空结果的合理性）
        ↓
⑥ 确认业务口径（金额语义、cancelled 排除）
        ↓
⑦ 生成 gold_result_hash
        ↓
⑧ 正式入集（分难度文件/批次按顺序 append）
```

审核人（人工/总顾问）对 ④⑤⑥ 负责；开发 Agent 对 ①②③⑦ 提供候选。

---

## I. 版本控制

| 变更 | 动作 |
|---|---|
| 修改 question 逻辑 | 新版本（v1.1 / v2.0） |
| 修改 Gold SQL | 新版本 |
| 修改数据库结构 / 生成逻辑 | 新版本 + 全部 hash 重算 |
| 仅 metadata / 拼写 / 补 notes | 记录 revision，不覆盖历史文件 |

历史版本只读归档（`data/eval/archive/`），**禁止静默覆盖正式 Benchmark**。

---

## J. 评测集元数据与数据库一致性绑定（data/eval/README.md 必含）

```text
dataset_name | version | database_version | seed | created_at |
schema_version | generator_version | review_status
```

**当前绑定值**（v1.0 正式生效，校验脚本硬校验）：

```text
database_version = dev-2026-09-14
seed            = 20260914
schema_version  = 1.0
```

- `seed = 20260914`：重新运行 `scripts/init_db.py` 可复现完全一致的数据库，Gold Result 不漂移；
- **任何数据库结构或生成逻辑改变** → 必须升级 `database_version` / `schema_version` → **全部重算 gold_result_hash**；
- `validate_eval_dataset.py` 会检查 metadata.seed 与固定种子是否一致，不一致即报错（防"换库不清零"）；
- 数据库重建或生成脚本升级 → 更新版本 → 重算 hash → 更新 README 元数据。

---

## K. 指标定义（阶段 1 启用；与 evaluation-plan.md 对齐）

| 指标 | 定义 |
|---|---|
| Exec Rate | 生成的 SQL 通过校验并成功执行数 / 总题数 |
| EX（Execution Accuracy） | pred 与 gold 执行结果一致数 / 总题数（分难度/场景交叉统计） |
| Pass@1 | 一轮生成即正确数 / 总题数 |
| Latency | P50/P95 端到端耗时，分难度报告 |
| Repair Rate | 进入修复循环题占比（Repair 落地后启用） |

后续（阶段 2+）可选：结论一致率、多轮准确率（上下文依赖轮单独统计）。

---

## L. 阶段 1 明确不引入（避免为设计而设计）

```text
LLM-as-a-Judge / 多模型投票 / 复杂 embedding / 向量数据库
```

当前只把核心指标（EX、Pass@1、Exec Rate、Latency、Repair Rate）做扎实；评测 Runner 属 Task 12，本任务不实现。

---

## 附录：error_type 登记表（可扩展，新增须登记）

```text
missing_join            缺 JOIN 或 JOIN 条件错误
wrong_caliber           口径错误（未排除 cancelled、金额字段误用 subtotal/total_amount）
column_hallucination    列名幻觉
aggregation_error       聚合层级/顺序/表达式错误
condition_missing       条件遗漏（时间 / 地区 / 状态 / 阈值）
condition_type_error    条件类型错误（时间格式、数值范围）
empty_result            应有结果却为空
ratio_error             比率/占比计算错误
topn_error              Top-N 排序或截断错误
unparseable             SQL 无法解析
unsafe                  SQL 安全校验不通过
timeout                 执行超时
schema_mismatch         Schema Linking 选择了错误表/列
others                  其他（在 notes 中说明）
```

---

*本规范与 `docs/evaluation-matrix.md`、`data/eval/README.md` 共同构成 Task 11 的数据建设蓝图；Task 12 起依据本规范分批生成并逐条通过 §E/G/H 校验后入集。*