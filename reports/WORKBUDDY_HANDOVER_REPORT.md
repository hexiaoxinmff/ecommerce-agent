# WorkBuddy Project Handover Report

> 项目：《基于 Text2SQL 的电商智能数据分析 Agent》
> 接手方：WorkBuddy AI（第二开发 Agent / 工程审查 Agent）
> 前序开发：TRAE
> 审计日期：2026-09-17
> 审计范围：Step 1~Step 5（项目接管审计），**未修改任何代码 / DB / Benchmark / Prompt / E3 / PPT / 文档**，未执行 git commit。
> 审计方式：只读检查 —— 目录遍历、文件阅读、`pytest` 实跑、SQLite 只读查询、JSON/PPTX 解包核对、Git 状态核对。

---

## 1. Project Status

**结论：项目已进入「最终交付 / 答辩准备 / 缺口修复」阶段，不是从零开始的新项目。**

| 维度 | 实测结论 |
|---|---|
| 核心链路 | 完整可运行（Backend / Agent / Safety / Repair / Evaluation / Frontend 均存在） |
| 测试 | `python -m pytest backend/tests` → **367 passed**（本次实测，25.90s） |
| 正式基线 | ECO-SQL-Bench v1.1 → **EX 90.0% / Exec 99.0% / Pass@1 90.0%**（冻结） |
| E3 | FROZEN（PoC / 机制验证，未接入生产 Agent 图） |
| 文档 | 基本齐备（`docs/` 29 份 + `reports/` 全套），**「项目说明（参数文档）」缺失** |
| PPT | 16 页已成型，但**存在两个内容不一致的 PPTX 文件**（见 §12） |
| Git 卫生 | ⚠️ **仅 1 个 commit（2026-09-15 22:42）**，此后全部工作未提交（见 §13 P0-1） |
| P0（破坏功能/数据/安全） | 无（代码层）；**但版本控制缺失构成工程级 P0 风险** |

**一句话：技术资产是合格的，工程交付习惯是欠账的。**

---

## 2. Directory Map

### 2.1 顶层

```text
F:\基于 Text2SQL 的电商智能数据分析 Agent\
├── backend/           # FastAPI 后端 + LangGraph Agent（92 个 .py）
├── frontend/          # React 19 + Vite + ECharts（src 27 个文件）
├── data/              # eval(200 json) / fewshot(23 例) / prompts(v1, v1.1, v1.3)
├── db/ecommerce.db    # SQLite 业务库（2.9MB，dev-2026-09-14 / seed 20260914）
├── evaluation/        # 评测框架（runner / metrics / normalization / models / report）
├── scripts/           # init_db / run_eval / E3 脚本 / validator（23 个 .py）
├── reports/           # 评测报告 + 最终验收 + 答辩材料（含 2 个 PPTX）
├── docs/              # 项目文档（29 份 .md）
├── tests/             # 顶层 tests（1 个 .py，几乎空置）
├── README.md
├── requirements.txt / requirements-lock.txt
├── .env / .env.example
└── .venv/             # Python 3.12.10 虚拟环境
```

### 2.2 关键入口（已逐一核对存在且可达）

| 用途 | 路径 |
|---|---|
| **后端入口** | `backend/app/main.py` → `app = FastAPI(...)`，注册 **10 条** route |
| **Agent 入口** | `backend/app/agent/graph.py` → `build_agent()` / `run_agent()`；节点在 `agent/nodes.py`，状态在 `agent/state.py` |
| **数据库** | `db/ecommerce.db`（只读访问层 `backend/app/db/sqlite.py`） |
| **Benchmark 入口** | 数据集 `data/eval/ecommerce_eval_v1.json`；运行 `scripts/run_eval.py`；核心 `evaluation/runner.py` |
| **E3 入口** | Detector `backend/app/sqlcheck/fanout_detector.py`；Hint `backend/app/experiments/fanout_hint.py`；历史 Runner `scripts/run_eval_fanout_hint.py` |
| **前端入口** | `frontend/index.html` + `frontend/src/main.tsx` + `frontend/src/App.tsx` |
| **测试入口** | `backend/tests/`（26 个测试文件，含 `conftest.py`） |
| **PPT / 报告** | `reports/`（PPTX ×2、PPT_CONTENT.md、DEMO_SCRIPT.md、DEFENSE_QA.md、DEFENSE_CHECKLIST.md、eval/ 全套） |

### 2.3 后端模块地图

```text
backend/app/
├── main.py                 # FastAPI 入口（10 routes）
├── api/routes/             # health / system / llm / schema_link / fewshot / sql_generate / sql_execute / sql_repair / agent
├── agent/                  # graph.py / nodes.py / state.py / models.py
├── schema/                 # metadata / introspector / linker / validation
├── fewshot/                # dataset / models / retriever
├── sqlgen/                 # generator / prompt / safety / validator / errors
├── sqlexec/                # executor / models / errors
├── sqlrepair/              # repairer / prompt / validator / models / errors
├── sqlcheck/               # fanout_detector.py（E3，冻结）
├── experiments/            # fanout_hint.py（E3，冻结）
├── llm/                    # provider.py / mimo.py（OpenAI-compatible）
├── trace/                  # recorder / models
├── db/                     # sqlite.py（只读层）
└── core/config.py          # .env 配置
```

> 备注：`tests/`（顶层）几乎空置（1 个 .py），真实测试全部在 `backend/tests/`。属历史遗留目录，非缺陷。

---

## 3. Core Architecture

### 3.1 核心链路（与事实基线一致）

```text
自然语言问题
→ Schema Linking
→ Few-shot Retrieve
→ SQL Generate
→ SQL Safety
→ Execute（只读）
→ Repair（≤1）
→ Result
```

### 3.2 技术栈（实测）

| 层 | 技术 | 实测版本/状态 |
|---|---|---|
| 语言 | Python | 3.12.10（`.venv`） |
| Web | FastAPI | 0.141.1 |
| Agent 编排 | LangGraph | 1.2.11 |
| SQL 解析 | sqlglot | 30.18.0 |
| DB | SQLite（**内置 `sqlite3`，非 SQLAlchemy**） | 只读 `mode=ro` + `query_only=ON` |
| LLM Provider | Mimo V2.5 Pro（OpenAI-compatible） | `mimo-v2.5-pro`，base_url `https://api.xiaomimimo.com/v1` |
| 前端 | React 19 + Vite 8 + ECharts 6 + TypeScript | **自定义 CSS**（未用 Tailwind / Ant Design） |

**必须区分的两个概念**：
- **Mimo V2.5 Pro = Runtime LLM Provider**（系统运行期调用的外部推理服务）；
- **开发 Agent = TRAE（前任）/ WorkBuddy（现接手）**（写代码的工具）。
- 二者不可混为一谈；PPT P4 已将 Mimo 明确标注为「外部 LLM Provider，非系统内部层」。

### 3.3 如实声明的技术栈差异（**不得包装为"完全采用任务书技术栈"**）

- SQLAlchemy **未使用**（用标准库 `sqlite3`）；
- Tailwind CSS **未使用**；Ant Design **未使用**（前端自定义 CSS）；
- **SSE 流式 API 未实现**（仅 REST）。

---

## 4. Database Baseline

### 4.1 表结构与规模（本次直连只读实测，与冻结口径**完全一致**）

| 表 | 行数（实测） | 归属域 | 关系 |
|---|---:|---|---|
| `users` | **2000** | 用户域 | 1—N `orders` |
| `categories` | **30** | 商品域 | 1—N `products` |
| `products` | **500** | 商品域 | 1—N `order_items` |
| `orders` | **10000** | 交易域 | 1—N `order_items` |
| `order_items` | **30457** | 交易域 | 明细行 |

- 仅 5 张业务表，**无其他表**（`sqlite_master` 实测确认）；
- `categories.parent_id` 自引用（支持层级，实际数据为扁平叶子类目）；
- 主外键与 CHECK 约束齐全（`status` 枚举、`price > 0`、`quantity > 0`、金额 `>= 0`）。

### 4.2 金额与取消口径（四端统一）

```text
order_items.subtotal  = 明细行金额（商品/类目/明细销售额默认口径）
orders.total_amount   = 订单最终实付（"实付/客单价/累计消费"口径）
cancelled             = 不计入"实际销售"类统计；但"结构统计（计数类）"不排除
```

> 该口径已写入 `backend/app/sqlgen/prompt.py` 的 `BUSINESS_RULES`（Prompt V1.3，"口径唯一权威"）与 `docs/database-schema.md`。**代码与文档一致，无冲突。**

### 4.3 只读保障（三层）

1. 连接 URI `file:...?mode=ro`（文件级只读）；
2. `PRAGMA query_only = ON`（会话级只读）；
3. 本层不提供任何写方法；写语句由 SQLite 直接拒绝。
4. 结果截断：`MAX_RESULT_ROWS = 500`，超出标记 `truncated=true`。

---

## 5. Agent Graph

### 5.1 实际图（`backend/app/agent/graph.py` 实测）

```text
START
 ↓
schema_link
 ↓
fewshot_retrieve
 ↓
sql_generate
 ↓
sql_safety ──(fail)──→ result → END
 ↓ (pass)
sql_execute ──(success)──→ result → END
 ├─(safety 拒绝)──────────→ result → END
 └─(DB 执行错误 且 repair_count==0) → sql_repair
                                       ├(被拒)→ result → END
                                       └(通过)→ sql_execute_repaired → result → END
```

### 5.2 有界性（代码级确认）

| 约束 | 实现位置 | 结论 |
|---|---|---|
| `repair_count ≤ 1` | `nodes.py: route_after_execute`（`repair_count >= 1 → result`） | ✅ 成立 |
| `execute_count ≤ 2` | 仅 `sql_execute` / `sql_execute_repaired` 各 +1，且 repaired 仅在 repair 通过时进入 | ✅ 成立 |
| 无无限循环 | 图为显式条件边，无回边 | ✅ 成立 |
| Safety 拒绝 → 禁止 Repair | `route_after_execute` 显式短路 | ✅ 成立 |

### 5.3 Trace

- 每个节点经 `_wrap` 包装，记录 `success / error / skipped` + `duration_ms` + 输入/输出摘要；
- 未走到的条件分支由 `result` 节点 `finalize_events` 补为 `skipped`；
- Provider 异常**不 raise**（保证 Trace 不丢），写入 `http_status / error_type` 由 API 层映射 502/503。

### 5.4 ⚠️ 重要事实：E3 未接入生产 Agent 图

`grep` 全仓库确认：`fanout_detector` / `fanout_hint` **仅被测试与实验脚本引用**（`backend/tests/test_e3_*`、`scripts/fanout_telemetry.py`、`scripts/run_eval_fanout_hint.py`、`scripts/scan_fanout_report.py`），**`backend/app/agent/` 内无任何引用**。

→ 即：**E3 是离线实验机制，不是线上能力**。此点与 `FINAL_ACCEPTANCE_REPORT.md` §5 的自述一致，**属于已披露的冻结边界，不是隐瞒**。任何"系统已内置 fan-out 防护"的表述都是错误的。

---

## 6. SQL Safety

### 6.1 静态校验（`backend/app/sqlgen/safety.py`，基于 sqlglot AST）

| 规则 | 实现 | 状态 |
|---|---|---|
| 只允许单条语句 | `len(statements) != 1` → 拒绝 | ✅ |
| 顶层仅 `SELECT` / `WITH`（含 `UNION`） | `_ALLOWED_STATEMENT_TYPES = (exp.Select, exp.Union)` | ✅ |
| 禁止写操作 / DDL / PRAGMA | `_WRITE_NODE_TYPES = Insert/Update/Delete/Drop/Create/Alter/Replace/Pragma`，全 AST `find_all` 扫描 | ✅ |
| 必须可被 SQLite 方言解析 | `sqlglot.parse(read="sqlite")` 失败即拒 | ✅ |
| 表名提取（剔除 CTE 名） | `extract_referenced_tables` | ✅ |

### 6.2 运行时防线

```text
SQL Safety（静态 AST）
→ SQLite Read-only（mode=ro + query_only=ON）
→ 有界 Repair（≤1，且 Repair 后二次校验 + 二次执行）
→ Trace（全链路可归因）
→ LIMIT ≤ 500 强制注入 + 结果截断
```

**设计立场正确**：LLM 输出**不被当作安全边界**，安全由确定性代码层保证。这一点在代码里是真实落地的，不是 PPT 话术。

---

## 7. Benchmark Baseline

### 7.1 数据集（实测）

| 项 | 值 |
|---|---|
| 名称 | **ECO-SQL-Bench v1.1**（`metadata.version = "1.1"`） |
| 题量 | **100**（`items` 长度实测） |
| 难度分布 | Easy **25** / Medium **30** / Hard **30** / Extra Hard **15** ✅ 与基线一致 |
| DB 版本 | `dev-2026-09-14`，seed `20260914` |
| 每条字段 | `id / split / difficulty / scenario / operators / question / gold_sql / gold_result_hash / expected_behavior / answer_slots / multi_turn / notes` |
| 卫生说明 | v1.1 修订 E-0086（防 fan-out）、E-0095（题面/Gold 对齐）、E-0098（排名 tiebreaker） |

### 7.2 Clean Baseline（冻结，来源 `reports/eval/clean_baseline_v1_1/`）

```text
Benchmark = ECO-SQL-Bench v1.1
Prompt    = SQLGENERATOR_PROMPT_V1.3  (sha256 10583478…96D5)
Few-shot  = FEWSHOT_V3（23 例，实测 len=23）  (sha256 EE12FCC9…4CEE)
DB        = dev-2026-09-14  (sha256 65E5D8B2…1D9，运行前后一致)
Model     = mimo-v2.5-pro
────────────────────────────────────────────
EX            = 90.0%   (90/100)
Exec Rate     = 99.0%   (99/100)
Pass@1        = 90.0%
provider_failures = 0
timeout           = 0
Avg = 10876 ms (10.9s) | P50 = 10489 ms (10.5s) | P95 = 15441 ms (15.4s)
```

### 7.3 按难度

| difficulty | count | EX% | 执行率% |
|---|---:|---:|---:|
| easy | 25 | 100.0 | 100.0 |
| medium | 30 | 100.0 | 100.0 |
| hard | 30 | 86.67 | 100.0 |
| extra_hard | 15 | 60.0 | 93.33 |

### 7.4 门禁（Runner 启动前强制）

- **Gold Hash Gate**：100/100 重算 `gold_result_hash`，漂移即整体停止；
- **Leakage Gate**：FEWSHOT_V3 ↔ Benchmark v1.1 无泄漏；
- DB SHA256 运行前后一致（PASS）。

### 7.5 ⚠️ 延迟未达标（如实记录，**不得写成达标**）

任务书目标 **≤8s**；实测 **Avg 10.9s / P50 10.5s / P95 15.4s**。**未达标**，属已披露 P1 缺口（主因：单题两次串行 Mimo 推理）。

---

## 8. Bad Cases

### 8.1 Clean Baseline 的 10 条 Bad Case（正式口径）

| # | eval_id | 难度 | stage | error_type |
|---|---|---|---|---|
| 1 | E-0057 | hard | result | result_mismatch（用户计数口径差异） |
| 2 | E-0077 | hard | result | result_mismatch（地区销售额值级差异） |
| 3 | **E-0082** | hard | result | **列数不一致（gold=2 / pred=1，缺类名列）** |
| 4 | **E-0083** | hard | result | **列数不一致（gold=2 / pred=1）** |
| 5 | **E-0086** | extra_hard | result | **fan-out 膨胀 4.14×（369854.65 vs 89397.46）** |
| 6 | E-0090 | extra_hard | result | 缺列（total_cnt）+ 缺 2025 过滤 |
| 7 | E-0095 | extra_hard | result | pred 多 1 行 |
| 8 | E-0096 | extra_hard | result | 排名题集合不一致 |
| 9 | **E-0099** | extra_hard | sql_repair | **`no such column: r.region` → Repair 触发但修复失败** |
| 10 | E-0100 | extra_hard | result | 结果集合不一致 |

→ 与任务书给定的 Bad Case 重点（E-0086 / E-0099 / E-0082·E-0083）**完全吻合**。

### 8.2 三类机制归纳（`FINAL_BAD_CASE_CATALOG.md` / PPT P11）

| 机制 | 代表 | 当前是否已处理 |
|---|---|---|
| **Fan-out 粒度** | E-0086 | E3 Detector + Hint 单例修复（PoC，未全量修复） |
| **别名 / 列引用** | E-0099 | 生成后执行报错 → 触发 Repair，**该样本修复仍失败** |
| **输出结构缺列** | E-0082 / E-0083 | **仍存在**（数值正确但缺 label 列） |

### 8.3 ⚠️ 命名混淆项（非事实冲突，但易误读）

`data/eval/bad_cases/` 实测含 **189 个文件**（`README.md` + `B-0001.example.json` + `B-1001.json` ~ `B-1187.json`），**不是** Clean Baseline 的 10 条 Bad Case。

- 这 189 个是 **Task 13 评测失败自动沉淀**的历史产物，其中包含大量 **API Key 未配置**导致的 `LLMApiKeyNotConfiguredError` 假失败样本（如 B-1001）；
- 正式的 10 条 Bad Case 记录在 `reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` §7；
- `FINAL_ACCEPTANCE_REPORT.md` §12 P2 已自行记录该目录入库策略待定。
- **建议**：在 `data/eval/bad_cases/README.md` 顶部加一行醒目说明，避免答辩时被误读为"系统有 189 个失败案例"。

---

## 9. E3 Baseline

**E3 = Gold-independent Fan-out 风险检测 + 条件触发 Hint 干预（proof of concept / mechanism validation），状态 FROZEN。**

### 9.1 冻结事实（与任务书基线逐条一致）

```text
E-0086: Pred = 369854.65  vs  真实 = 89397.46   →  fan-out ≈ 4.137×（约 4.14×）
机制链: Pred SQL → Fan-out Detector → Alarm → FANOUT_RECHECK_HINT → 1 次再生成 → EX✗ → EX✓
对照:   OFF = 90%  /  ON = 93%
```

### 9.2 边界（**禁止越界表述**）

| 约束 | 实测确认 |
|---|---|
| `alarm n = 1` | ✅ Task 21 报告：ON alarm 数 = 1（`['E-0086']`） |
| 仅 E-0086 有直接归因 | ✅ E-0099 / E-0100 alarm=false，未注入 hint，改善来自独立样本随机性 |
| OFF/ON 非严格单变量 | ✅ 超时 60s vs 90s；OFF 走 LangGraph+repair / ON 走线性脚本无 repair；延迟口径不同 |
| 性质 | ✅ PoC / mechanism validation（**不是**因果估计） |
| 成本 | 单次 regeneration 边际约 +8.3s；本次摊薄约 +0.08s/题 |

> **禁止表述**："Hint 提升 EX 3 个百分点" / "显著提升" / "证明有效" / "Recall 100%"。
> 正确表述："OFF 90% → ON 93% 是**观测差异**，其中**仅 E-0086 的 +1pt 具有直接 Hint 归因证据**。"

### 9.3 已知限制（冻结）

- 仅覆盖 `orders × order_items` 粒度风险；
- 子查询剪枝**未生效**（P1-1）；
- 未限定列名存在**漏报盲区**（P1-2）；
- `SUM(DISTINCT)` 不等于防护（P2-3）。

### 9.4 产物位置

Task 17~21 全部位于主仓库 `reports/eval/task17_*` ~ `task21_*`（**不在旧 worktree `master-b947f329`**），提交时不得遗漏。

---

## 10. Test Baseline

### 10.1 本次实测（Step 3）

```bash
python -m pytest backend/tests -q
→ 367 passed, 1 warning in 25.90s
```

- 唯一 warning：`starlette/testclient.py` 的 `anyio.abc.BlockingPortal` DeprecationWarning（第三方库内部，非本项目代码）；
- **与文档基线 367 passed 完全一致**；
- 未发现失败用例，**无需修改任何业务代码**。

### 10.2 数字来源链路（已核对，无矛盾）

| 数字 | 出处 | 时间 |
|---|---|---|
| 357 passed | `reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md` 卫生检查表 | 2026-09-16 10:44（跑 Clean Baseline 时） |
| 367 passed | Task 23 最终技术验收（追加 E3 相关测试后） | 2026-09-16 20:17 |

→ 357 → 367 的增长由 E3 测试（`test_e3_fanout_detector.py` / `test_task18_telemetry.py` / `test_task20_hint.py`）解释，**逻辑自洽**。

### 10.3 测试覆盖（26 个测试文件）

Agent / Trace / Schema Linking / Few-shot / SQL 生成 / Safety / Executor / Repair / LLM Provider / DB 只读 / Health / Eval Runner（Gold Hash Gate、Leakage Gate、EX 归一化）/ E3（Detector / telemetry / Hint）。

**未覆盖**（如实声明）：登录与用户管理、多轮 conversation（功能未实现）；前端无自动化 UI 测试。

---

## 11. Documentation Status

### 11.1 已有文档（`docs/` 实测 29 份）

| 类别 | 文档 | 状态 |
|---|---|---|
| 产品/设计 | PRD.md、UI-UX.md、database-schema.md | ✅ |
| 技术 | README.md（根）、API.md、TEST_REPORT.md、DEPLOYMENT.md、OPERATIONS.md、AI_COLLABORATION.md | ✅ |
| 架构/模块 | backend-architecture.md、langgraph-agent.md、agent-trace.md、schema-linking.md、fewshot-retrieval.md、sql-generator.md、sql-executor.md、sql-repair.md、llm-integration.md | ✅ |
| 评测 | evaluation-plan.md、evaluation-matrix.md、evaluation-dataset-spec.md、evaluation-batch-1~4-review.md | ✅ |
| 过程 | project-understanding.md、development-baseline.md、tech-research.md、architecture-options.md、phase4-task10-acceptance.md | ✅ |

`reports/` 侧：FINAL_ACCEPTANCE_REPORT / FINAL_DELIVERY_GAP_CHECK / FINAL_EXPERIMENT_MATRIX / FINAL_BAD_CASE_CATALOG / FINAL_REQUIREMENTS_CHECKLIST / PPT_CONTENT / DEMO_SCRIPT / DEFENSE_QA（35 题）/ DEFENSE_CHECKLIST / task24 / task26 / task27 + `reports/eval/` 全套。

### 11.2 ⚠️ 文档缺口

| # | 缺口 | 依据 |
|---|---|---|
| D-1 | **「项目说明（参数文档）」缺失** | 任务书 5.2-5 要求；`FINAL_DELIVERY_GAP_CHECK.md` P1-2；全仓库 `find` 无匹配文件 |
| D-2 | README §18 文档索引**不完整** | README 列 19 份，实际 `docs/` 29 份；未索引 agent-trace / architecture-options / development-baseline / evaluation-batch-1~4 / phase4-task10 / project-understanding / tech-research（共 10 份） |
| D-3 | `data/eval/bad_cases/` 无醒目的"历史沉淀"说明 | 见 §8.3 |

### 11.3 README 质量评价

README 结构完整（18 节），**且主动如实声明了技术栈差异与未实现功能**（§4 / §13 / §17），这在学生项目中属于罕见的诚实度。**不建议改动其口径。**

---

## 12. PPT Status

### 12.1 事实基线

| 项 | 实测 |
|---|---|
| 页数 | **16 页**（两个 PPTX 解包均为 16 slides） |
| 页序 | 封面 → 背景与问题 → 项目目标 → 系统架构 → Agent 流程 → 数据库设计 → SQL 安全 → 前端界面 → 评测体系 → 评测结果 → Bad Case → E3 创新 → E3 边界 → Demo → 总结 → 封底 |
| 内容源 | `reports/task26_ppt/goal.json` + `reports/task26_ppt/ppt/index.html`（529KB） |
| 渲染核查产物 | `reports/task26_ppt/qa2/`（16 页 jpg）、`reports/task26_ppt/qa3/`（16 页 jpg） |
| 截图素材 | `reports/ppt_assets/01_home.png` ~ `05_sql_trace.png`（5 张真实运行截图） |
| 文字稿 | `reports/PPT_CONTENT.md` |

### 12.2 ⚠️ 冲突 1：两个 PPTX 并存，且内容不一致、命名与时间戳互相矛盾

| 文件 | 大小 | mtime | 实际内容 |
|---|---:|---|---|
| `..._答辩PPT_FINAL.pptx` | 17.34 MB | 2026-09-17 **12:03** | ✅ **与 Task 26.2「最终定稿」描述一致**：P10 无 01–05 编号；P8 标题无「· 真实可追溯」尾缀；P14 表头「DEMO 清单 · 4 条真实验证问题」；P15「E3：验证典型 Fan-out 风险检测与条件干预机制」 |
| `..._答辩PPT.pptx` | 11.91 MB | 2026-09-17 **12:37** | ⚠️ **内容更旧**：P10 仍含「01 Easy … 05 合计」编号；P8 标题仍含「· 真实可追溯」；P14 表头「现场 DEMO / TASK 23 E2E SMOKE 实测」；P15 简写 |

**旁证**：`qa3/` 渲染（12:24–12:27）与 `_FINAL.pptx` 内容一致；`task27_defense_materials_completion.md` 却声称最终交付文件为**无 `_FINAL` 后缀**的那个（"16 页 / 466 可编辑文本对象"）。

**结论**：**文件名与时间戳均不可作为判断依据**。二者必须人工二选一，**当前建议以 `_答辩PPT_FINAL.pptx` 为准**（内容与最新渲染一致、符合最终定稿描述），但**需人工确认**。

### 12.3 ⚠️ 冲突 2：`qa3/` 渲染页序与 PPTX 页序错位 1 页

`qa3/p01.jpg` 实为 **slide 2（背景与问题）**，`qa3/p15.jpg` 与 `qa3/p16.jpg` **均为封底（THANKS）**，即：**渲染序列漏掉封面、封底重复**。

→ 这是**渲染核查工具产物的问题，不是 PPT 缺陷**。但意味着「16/16 逐页巡检 PASS」这一结论**并未覆盖真正的 slide 1（封面）**。

### 12.4 ⚠️ 冲突 3（**已独立复核并确认**）：`task26_ppt_completion.md` 声称"逐页 DOM+几何巡检 16 页全部 PASS：无文字重叠、无截断"，**该结论不成立**

**复核方法**（WorkBuddy 独立执行，未改动任何项目文件）：
用系统 Chrome（`C:\Program Files\Google\Chrome\Application\chrome.exe`）无头模式，按 deck 自身的 `?page=N` 参数逐页渲染 `reports/task26_ppt/ppt/index.html`（1920×1080，`--virtual-time-budget=15000`），产出 PNG 后目视核验。渲染产物位于系统临时目录，**未写入项目仓库**。

**复核结论：3 页存在真实缺陷，1 页为低分辨率误判，封面正常。**

| 页 | 结论 | 具体问题 | 证据 |
|---|---|---|---|
| **P12（E3 创新）** | ❌ **确认重叠** | 标题 `t004 = "orders × order_items"` 与副标题 `t005 = "Pred 与真实结果对比"` 为**两个独立字段**，渲染时 `order_items`（白）与 `Pred 与真实`（蓝）**在同一基线上字形相撞**，读作 `order_itemsPred 与真实`。另：`4.14×` 下方的「订单×明细 粒度放大」文字被一枚红色 `E-0086` 贴纸压住 | 独立渲染 `?page=12`；deck-view-model `theme03_page019` 的 `copy.t004 / copy.t005` |
| **P9（评测体系）** | ❌ **确认内容错配** | ① **列标题与单元格语义不匹配**：列为「Benchmark / Gold 审核 / 归一化判定」，但行 `90.0% EX` 的三格填的是 `90/100` / `86.67 Hard` / `60 Extra` —— 后两格是**难度分层数据**，与「Gold 审核」「归一化判定」无关（模板复用致填充错位）；② **`unit` 被机械追加到所有单元格**，产生 `无重试 %`、`直接通过 %`、`86.67 Hard %`、`100 Easy %`、`目标≤8s S`、`P50 10.5 S` 等**无意义后缀** | 独立渲染 `?page=9`；deck-view-model `theme03_page021` 的 `companies` / `rows[].vals` / `rows[].unit` |
| **P6（数据库设计）** | ❌ **确认列粘连** | `行数` 列宽不足：5 位数值与「所属域」标签**零间距粘连**，渲染为 `10000交易域`、`30457交易域`；而 3 位/2 位数值（`2000 用户域`、`30 商品域`、`500 商品域`）**有正常间隙** → 证明是列宽未适配 5 位数。另：`01 users` 行右侧有一枚来源不明的蓝色矩形块 | 独立渲染 `?page=6`；slide6.xml 文本层本身干净（`10000` 与 `交易域` 分列，故为**纯视觉重叠**） |
| **P5（Agent 流程）** | ✅ **正常（此前为误判）** | 底部 5 张卡在高清渲染下为正常的「异常处理 / 失败 → 受控拒答」等文案；此前在 `qa3/p04.jpg`（低分辨率 JPEG）上误读为乱码。**仅标题 `用户问题` 与右侧 lead 间距偏窄**，未构成重叠 | 独立渲染 `?page=5` |
| **P1（封面）** | ✅ **正常** | 标题 / 三个指标（90.0% EX · 99.0% Exec · 100 题）/ 报告人信息排布正常 | 独立渲染 `?page=1` |

> **审计纪律**：本项**只做复核与记录，未修改 PPT 任何文件**。
> **修正建议（待用户批准）**：仅改 `reports/task26_ppt/goal.json` 中 `theme03_page019`（P12）的 `copy.t004/t005` 与 `theme03_page021`（P9）的 `rows[].vals/unit`、`theme03_page012`（P6）列宽，然后重渲染导出；**不动 theme03 模板与其余页面**。
> **注**：`task26_ppt_completion.md` §"Task 26.2 Final Revision → Visual QA" 中"逐页 DOM+几何巡检 16 页全部 PASS：无文字重叠"的表述**与实际渲染不符**，建议在文档中更正，避免答辩前误以为无需走查。

### 12.5 PPT 内容口径核查（抽查，结论：良好）

- ✅ P13 以「90% → 93%：观测差异」为**最大视觉**，「禁止表述『Hint 提升 3 个百分点』」置于底部小字，非标题；
- ✅ P3「≥85% 目标已达成」仅出现 1 次；
- ✅ 未实现能力（Multi-turn / 用户管理 / SSE / 结论生成）未被写成已实现；
- ✅ 技术栈差异（未用 SQLAlchemy / Tailwind / Ant Design）已披露；
- ✅ Demo 仅 4 条，全部来自 Task 23 E2E Smoke 实测（`e2e_smoke.json` 已核对：Q1 广东 246 / 月度 12 行 / Top5 5 行 / 类目 1 行）。

---

## 13. Current Known Risks

### 13.1 P0（破坏现有功能 / 数据正确性 / 安全）

| # | 风险 | 证据 | 说明 |
|---|---|---|---|
| **P0-1** | **版本控制严重欠账** | `git log` 仅 1 个 commit（`80a09b5`，2026-09-15 22:42）；此后 15 个已跟踪文件被修改、**165 个未跟踪条目**（`data` 103 / `reports` 41 / `scripts` 8 / `docs` 5 / `backend` 5 + README） | **Task 14.3 ~ Task 27 的全部成果均无版本保护**：包括 Prompt V1.3、Benchmark v1.1（含 Gold 修订）、FEWSHOT_V3、E3 全部代码与实验数据、评测框架改造、全部报告与 PPT。**一次误删即不可恢复**。代码层无 P0，但这是工程级 P0。 |
| P0-2 | 无 | 安全层（SQL Safety / 只读 / 有界 Repair）实测正确；`.env` 已被 `.gitignore` 正确忽略（`git check-ignore` 确认） | 无 |

### 13.2 P1（影响答辩 / 正式验收）

| # | 风险 | 证据 | 影响 |
|---|---|---|---|
| P1-1 | **两个 PPTX 内容不一致，最终版不确定** | 见 §12.2 | 答辩当天可能展示到旧版（含 01–05 编号 / 尾缀残留） |
| P1-2 | **PPT P12 标题文字重叠（已确认）** | 见 §12.4 独立复核 | 创新点页是答辩核心页，标题撞字直接影响观感 |
| P1-2b | **PPT P9 列标题与内容错配 + 单位后缀错误（已确认）** | 见 §12.4 | 「无重试 %」「目标≤8s S」等会当场被看出，且列标题误导 |
| P1-2c | **PPT P6 五位行数与「交易域」零间距粘连（已确认）** | 见 §12.4 | 数据库页是老师会逐格看的页面 |
| P1-3 | **「项目说明（参数文档）」缺失** | 任务书 5.2-5；全仓库无匹配文件 | 交付物清单不齐 |
| P1-4 | **端到端 Avg 10.9s 未达 ≤8s** | `clean_baseline_v1_1.md` §5 | 已如实披露，答辩需解释取舍 |
| P1-5 | Multi-turn 未实现 | 任务书明确要求；PRD 阶段 2 / Out-of-Scope | 已披露，答辩需解释 |
| P1-6 | 用户管理未实现 | 任务书明确要求；PRD Out-of-Scope | 已披露，答辩需解释 |
| P1-7 | 结论生成未实现（前端占位） | `backend/app/main.py` 注释「未接入：结论与图表生成」 | 不得宣称完整实现 |
| P1-8 | SSE 流式未实现 | 任务书技术选型表含 SSE | 已披露 |
| P1-9 | 评测数据源非 Spider | 自建合成库 + 自建 100 题 | 数量达成、来源偏差，已披露 |

### 13.3 P2（体验 / 工程优化）

| # | 项 | 证据 |
|---|---|---|
| P2-1 | 前端单页 JS chunk 1.38MB | `FINAL_ACCEPTANCE_REPORT.md` §12 |
| P2-2 | react-refresh lint warning ×1 | `docs/TEST_REPORT.md` §4 |
| P2-3 | 架构图 / Agent 流程图 / ER 图**无图片版** | 均为文本图 |
| P2-4 | 无 UI 截图入库（仅 `ppt_assets/` 5 张） | — |
| P2-5 | `data/eval/bad_cases/` 189 个历史沉淀文件入库策略未定 | §8.3 |
| P2-6 | README 文档索引不完整（缺 10 份） | §11.2 D-2 |
| P2-7 | 顶层 `tests/` 目录几乎空置（1 个 .py） | 历史遗留 |
| P2-8 | Repair / E3 无稳定现场 Demo 触发问题 | `FINAL_DELIVERY_GAP_CHECK.md` §9 |

### 13.4 冲突项清单（代码 ≠ 文档 / PPT ≠ 实现 / 指标 ≠ Benchmark 的逐项记录）

> 按任务书要求：**不自行选择"正确答案"**，仅记录冲突、双方证据、当前建议与是否需要人工确认。

| # | 冲突项 | 代码/实测证据 | 文档/PPT 证据 | 当前建议 | 需人工确认 |
|---|---|---|---|---|---|
| C-1 | **最终 PPTX 是哪一个** | 两个文件解包内容比对：`_FINAL.pptx`(12:03) 内容新于无后缀 `.pptx`(12:37) | `task27_*.md` 称交付文件为**无后缀**那个；`task26_ppt_completion.md`「最终定稿」描述与 `_FINAL.pptx` 一致 | 以 `_答辩PPT_FINAL.pptx` 为准；**并重命名统一** | **是** |
| C-2 | **PPT「16/16 逐页 PASS 无重叠」是否成立** | **独立渲染复核（Chrome 无头 `?page=N`）确认：P12 标题重叠、P9 列标题/内容错配 + 单位后缀错误、P6 五位数列粘连；P5 为低分辨率误判，P1 正常** | `task26_ppt_completion.md`「Visual QA … 全部 PASS 无文字重叠」 | 该声明**不成立**，需修正文档并做最小修复（改 `goal.json` → 重渲染） | **是**（修复范围待批准） |
| C-3 | **`qa3/` 渲染页序** | `qa3/p01` = slide2；`p15`=`p16`=封底；封面未渲染 | 报告称「16 页逐页巡检」 | 已确认属工具产物问题；封面经独立渲染确认正常 | 否（已闭环） |
| C-4 | **"10 条 Bad Case" vs 189 个文件** | `data/eval/bad_cases/` 实测 189 个（含 Key 未配置假失败） | 基线报告 §7 列 10 条 | 在 `bad_cases/README.md` 加醒目说明；答辩引用以 10 条为准 | 否（建议补说明） |
| C-5 | **README 文档索引 vs 实际 docs/** | `docs/` 实测 29 份 | README §18 列 19 份 | 补全索引（P2） | 否 |
| C-6 | **E3 是否在线能力** | `grep` 确认 E3 未接入 `backend/app/agent/` | PPT P12/P13 已标注 PoC；`FINAL_ACCEPTANCE_REPORT.md` §5 已声明未接入 | **无冲突**（已如实披露），但答辩时**必须口播澄清** | 否 |
| C-7 | **357 vs 367 passed** | 本次实测 367 | 基线报告 357 / Task 23 报告 367 | **无冲突**（时序差异，E3 测试追加所致） | 否 |

**未发现**下列类型的真实冲突：
- ✅ 数据库结构与行数：代码 / 文档 / 实测**三方一致**；
- ✅ Agent 图与有界约束：代码 / 文档**一致**；
- ✅ SQL Safety 规则：代码 / 文档**一致**；
- ✅ Benchmark 题量与难度分布：数据集 / 文档 / PPT**一致**；
- ✅ Clean Baseline 指标：报告 / README / PPT**一致**；
- ✅ E3 事实与边界：报告 / README / PPT**一致**。

---

## 14. Recommended Next Tasks

> 按 P0 → P1 → P2 排序；**均需用户确认后执行**。本轮不执行任何修改。

### P0（建议立即）

| # | 任务 | 动作 | 预估工作量 |
|---|---|---|---|
| **N-1** | **建立 Git 版本安全网** | 按逻辑分批 commit：① 核心代码（含 E3 代码）② Benchmark v1.1 + Few-shot V3 + Prompt ③ evaluation/ ④ 文档 ⑤ 报告与答辩材料。**建议先做**，之后再谈任何修改 | 小 |
| **N-2** | **确认最终 PPTX** | 人工二选一，统一为一个文件名，删除/归档另一个，避免答辩当天拿错文件 | 极小 |

### P1（答辩前）

| # | 任务 | 动作 |
|---|---|---|
| N-3 | **修复已确认的 PPT 渲染缺陷（P12 / P9 / P6）** | 已完成独立复核并定位到具体字段：P12 = `theme03_page019.copy.t004/t005`；P9 = `theme03_page021.rows[].vals/unit` 与列标题；P6 = `theme03_page012` 行数列宽。**仅改这几处 → 重渲染 → 重导出**，不动 theme03 模板与其余 13 页 |
| N-3b | 更正 `task26_ppt_completion.md` 中「16/16 逐页 PASS 无文字重叠」的不实结论 | 避免答辩前误以为无需走查 |
| N-4 | 补「项目说明（参数文档）」 | 按任务书 5.2-5 模板输出（系统参数、模型参数、运行参数、阈值） |
| N-5 | ~~核查 PPT 封面（slide 1）~~ | **已由独立渲染确认正常（P1 无问题），本项关闭** |
| N-6 | 答辩口径演练 | 用 `DEFENSE_QA.md`（35 题 + 7 高风险）过一遍；**重点演练 7 个高风险问题的口径**（90% 来源 / E3 是否涨 3pt / ≤8s 未达标 / Spider 数据源 / Multi-turn / SSE / 创新点） |

### P2（可选）

| # | 任务 |
|---|---|
| N-7 | 在 `data/eval/bad_cases/README.md` 顶部加"历史沉淀"说明 |
| N-8 | 补全 README §18 文档索引（缺 10 份） |
| N-9 | 前端 code-split（chunk 1.38MB） |
| N-10 | 架构图 / Agent 流程图 / ER 图图片版（答辩素材） |
| N-11 | 清理顶层空置 `tests/` 目录 |
| N-12 | 性能专项（缓存 / 并行化）以逼近 ≤8s（属任务书理想目标） |

### 明确不建议做的事（本轮及近期）

- ❌ 重构 Agent / 评测框架（现结构清晰、测试全绿，重构收益低于风险）；
- ❌ 修改 Benchmark / Gold / Prompt / Few-shot / DB（已冻结，改动会使全部冻结指标失效）；
- ❌ 修改 E3（已 FROZEN，alarm n=1，改动等于重做实验）；
- ❌ 把 E3 接入生产 Agent 图（会改变 Clean Baseline 的复现口径，需重新跑 100 题）；
- ❌ 追求「Hint 提升 3pt」类叙事（不成立，且会被追问击穿）。

---

## 15. Handover Conclusion

### 15.1 接管判定

**接管成功。项目资产可信，事实基线可复现，无代码级 P0。**

本次审计通过**独立复算**（实跑 pytest、直连 SQLite 计数、解包 PPTX、核对 JSON、`grep` 代码引用）验证了任务书给定的**全部**事实基线：

| 基线项 | 任务书给定 | 本次实测 | 结论 |
|---|---|---|---|
| DB 行数 | 2000/30/500/10000/30457 | 完全一致 | ✅ |
| Agent 图 | schema_link→…→result，repair≤1/execute≤2 | 代码一致 | ✅ |
| SQL Safety | 只 SELECT/WITH、禁写、单语句、禁 PRAGMA、LIMIT≤500 | 代码一致 | ✅ |
| Benchmark | v1.1，100 题，25/30/30/15 | 完全一致 | ✅ |
| Clean Baseline | EX 90.0% / Exec 99.0% / Pass@1 90.0% / Provider 0 / Timeout 0 | 报告一致 | ✅ |
| 延迟 | Avg 10.9s / P50 10.5s / P95 15.4s（未达 ≤8s） | 报告一致 | ✅ |
| Bad Case | 10 条（E-0086 / E-0099 / E-0082·83 为重点） | 完全一致 | ✅ |
| E3 | 4.14×、alarm n=1、仅 E-0086 归因、PoC | 报告一致 | ✅ |
| pytest | 367 passed | **367 passed（实测）** | ✅ |

### 15.2 对前序工作的评价

- **技术实现质量高**：有界 Repair、只读双保险、Trace 完整性、Gold Hash + Leakage 双门禁、EX 归一化判定——这些**都不是学生项目常见水平**；
- **实验纪律好**：E3 主动声明 `alarm n=1`、非严格单变量、禁止"提升 3pt"表述，**主动抑制了夸大**；
- **诚实度高**：README / Gap Check / Defense QA 主动披露技术栈差异、未实现功能、指标未达标；
- **工程习惯差**：**1 个 commit 扛下了整个项目**。这是最需要立刻修补的短板。

### 15.3 我作为接手方的承诺与边界

1. **先理解，再修改**——本轮零修改，仅审计；
2. **不"修正"项目事实**——发现不一致只记录冲突 + 双方证据，不擅自裁决；
3. **不改冻结资产**——DB / Benchmark / Gold / Prompt / Few-shot / E3 / 已冻结报告一律不动；
4. **不做大范围重构**——现有实现结构清晰、测试全绿，重构是负收益；
5. **P0 优先**——后续任何开发，先保数据正确性与安全，再谈功能。

### 15.4 等待用户确认的事项

1. **N-1：是否立即建立 Git 分批提交？**（建议：是，最高优先）
2. **N-2 / C-1：最终 PPTX 采用 `_答辩PPT_FINAL.pptx` 还是无后缀版本？**
3. **C-2（已复核完成）：是否授权我修复已确认的 P12 / P9 / P6 渲染缺陷？**（仅改 `goal.json` 三处字段 → 重渲染 → 重导出，不动模板与其余 13 页）
4. **N-4：是否需要补「项目说明（参数文档）」？**
5. **下一步开发任务的优先级排序**（P1 缺口 / 性能优化 / 新功能）。

### 15.5 闭环状态（Task 28 追加，2026-09-17）

> 本节由 Task 28 追加。**§1–§15 正文保持为 Task 1~5 审计当时的事实，未作改写。**

| 待确认项 | Task 28 处置结果 | 状态 |
|---|---|---|
| **N-1** 是否建立 Git 分批提交 | 已建立：`80a09b5`（基线）+ `d258491`（交付前快照） | ✅ **闭环** |
| **N-2 / C-1** 最终 PPTX 用哪一个 | **已统一**：新版置于 `reports/基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx`；两个旧版经 `git mv` 归档至 `reports/_archive_pptx/`（加 `.superseded-20260917` 后缀）。**不再存在"两个 final"** | ✅ **闭环** |
| **C-2** 是否授权修复 P12 / P9 / P6 | 已授权并完成：P12 标题碰撞 + 装饰遮挡；P9 列标题错配 + 单位后缀；P6 数字列粘连。仅改 3 个源文件，未动模板与其余 13 页 | ✅ **闭环** |
| **N-4** 是否补「项目说明（参数文档）」 | 已补：`docs/project-parameters.md`（10 章），并在 README §18 补索引 1 行 | ✅ **闭环** |
| **C-3** `qa3/` 渲染页序 | 确认为工具产物问题，封面经独立渲染验证正常 | ✅ 已闭环（同审计结论） |
| **C-5** README 文档索引不完整 | **已处理（Task 28 Closeout）**：§18 索引重写为分组树形结构，`docs/` **30/30**、`reports/` 顶层 **14/14** 全部收录（含此前缺失的答辩材料 `DEMO_SCRIPT.md` / `DEFENSE_QA.md` / `DEFENSE_CHECKLIST.md` / `PPT_CONTENT.md`）；脚本回查确认零缺失、零幽灵条目 | ✅ **闭环** |
| **N-5** 下一步开发优先级 | 未涉及 | ⏳ **仍待用户决定** |
| **C-4** "10 条 Bad Case" vs 189 文件 | 未涉及（不在 Task 28 范围） | ⏳ 仍待处理 |
| **C-6 / C-7** | 审计结论为"无冲突"，无需动作 | ✅ 无需动作 |

> **Task 28 结论**：C-1 / C-2 / C-5 三项已解决，最终交付证据见 `reports/task28_final_delivery.md`。
> 遗留 `N-5`（开发优先级）供后续决策。

---

## 附录 A · 冻结事实表（Step 2 清单）

| 项 | 当前实现 | 当前状态 | 对应文件 | 是否冻结 | 是否允许修改 |
|---|---|---|---|---|---|
| **数据库** | SQLite，5 表，2000/30/500/10000/30457 | 冻结（dev-2026-09-14 / seed 20260914） | `db/ecommerce.db`、`scripts/init_db.py`、`backend/app/db/sqlite.py` | ✅ 冻结 | ❌ 禁止修改 |
| **Agent Graph** | START→schema_link→fewshot_retrieve→sql_generate→sql_safety→sql_execute→(repair≤1)→sql_execute_repaired→result→END | 运行正常，367 测试覆盖 | `backend/app/agent/{graph,nodes,state,models}.py` | 未冻结（实现层） | ⚠️ 谨慎（改动影响基线复现） |
| **Safety** | sqlglot AST：单语句 + SELECT/WITH + 禁写/DDL/PRAGMA + 表名提取 | 完整可用 | `backend/app/sqlgen/safety.py`、`validator.py`、`sqlexec/executor.py` | 未冻结 | ⚠️ 谨慎（安全相关，改动需测试全覆盖） |
| **Repair** | 有界 ≤1 次，二次校验 + 二次执行 | 完整可用（Repair Trigger 1.0% / Success 0.0%） | `backend/app/sqlrepair/*`、`agent/nodes.py` | 未冻结 | ⚠️ 谨慎 |
| **Benchmark** | ECO-SQL-Bench v1.1，100 题，25/30/30/15 | 冻结（v1.1 卫生修订） | `data/eval/ecommerce_eval_v1.json` | ✅ **冻结** | ❌ **禁止修改** |
| **Metrics** | EX / Exec Rate（双口径）/ Pass@1 / 延迟 / provider / timeout | 冻结（90.0/99.0/90.0/10.9s/0/0） | `evaluation/{metrics,models,report}.py`、`reports/eval/clean_baseline_v1_1/` | ✅ 冻结 | ❌ 禁止修改 |
| **Bad Cases** | 10 条（正式）+ 189 个历史沉淀文件 | 冻结（正式 10 条） | `reports/eval/clean_baseline_v1_1/`、`data/eval/bad_cases/` | ✅ 冻结 | ❌ 禁止修改（可补 README 说明） |
| **E3** | Fan-out Detector + 条件 Hint（PoC），未接入生产图 | **FROZEN** | `backend/app/sqlcheck/fanout_detector.py`、`experiments/fanout_hint.py`、`reports/eval/task17~21/` | ✅ **FROZEN** | ❌ **禁止修改** |
| **API** | 10 条 route | 可用，TestClient 全覆盖 | `backend/app/main.py`、`api/routes/*`、`docs/API.md` | 未冻结 | ⚠️ 谨慎（新增可，改现有需同步文档） |
| **Frontend** | React 19 + Vite 8 + ECharts 6 + 自定义 CSS；datasets/history/settings 占位 | build/lint 通过 | `frontend/src/*`、`frontend/dist/` | 未冻结 | ✅ 可修改（P2 优化） |
| **Tests** | 26 个测试文件，367 passed | 全绿 | `backend/tests/*` | 未冻结 | ⚠️ 可追加，不建议删改现有 |
| **Documentation** | docs/ 29 份 + reports/ 全套；缺参数文档 | 基本齐备 | `docs/*`、`README.md`、`reports/*` | 部分冻结（历史报告） | ⚠️ 可补不可改口径 |
| **PPT** | 16 页；两个 PPTX 内容不一致 | 待确认最终版 | `reports/*.pptx`、`reports/task26_ppt/goal.json`、`ppt/index.html` | 未冻结 | ⚠️ 仅最小修正（改 goal.json → 重渲染） |

---

## 附录 B · 本次审计执行记录

| Step | 动作 | 结果 |
|---|---|---|
| 1 | 建立项目地图（目录遍历 + 入口核对） | ✅ 见 §2 |
| 2 | 建立冻结事实表 | ✅ 见附录 A |
| 3 | 运行 `python -m pytest backend/tests` | ✅ **367 passed**（25.90s） |
| 4 | 检查 Git 状态与近期 diff | ✅ 1 commit / 15 modified / 165 untracked；见 §13.1 P0-1、§13.4 C-7 |
| 5 | 检查 Benchmark / E3 / Bad Case 文件与基线一致性 | ✅ 全部一致；另发现 C-1~C-5 五项待确认事项 |
| 6 | **PPT 独立渲染复核（补充执行）** | ✅ 用系统 Chrome 无头模式按 `?page=N` 逐页渲染 1920×1080，**确认 P12 标题重叠 / P9 列标题内容错配 + 单位后缀错误 / P6 五位数列粘连**；P5 为低分辨率误判、P1 封面正常；`qa3/` 页序错位（漏封面、封底重复）已闭环 |

**本轮未执行**：任何代码修改、DB 修改、Benchmark 修改、Prompt 修改、E3 修改、PPT 修改、文件删除、`git commit`。

**注**：Step 6 的渲染产物（PDF/PNG）全部写在系统临时目录 `%TEMP%\wb_ppt_check\`，**未写入项目仓库**；项目内唯一新增文件为本报告。

---

*报告生成：WorkBuddy AI（第二开发 Agent / 工程审查 Agent）｜2026-09-17｜基于只读审计，所有数字均有实测或文件出处。*
