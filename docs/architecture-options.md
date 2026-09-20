# 架构候选分析（Architecture Options）

> 阶段：基线方案最终收敛（阶段 1）· 已按最终决策修订
> 日期：2026-09-14
> 状态：与最终项目决策一致，作为唯一基线（重点：第 5 节推荐结论、第 6 节状态流、第 7 节数据库设计）

---

## 1. 三种候选架构

### 方案 A：直连式（Baseline）

```
自然语言 → LLM → SQL → Execute → 表格返回
```

### 方案 B：增强流水线（单轮流水线 + 修复）

```
自然语言 → Schema Retrieval → Few-shot Retrieval
        → LLM(SQL 生成) → SQL Validation → Execute
        → (失败) Repair → 重新 Validation → Execute → 表格返回
```

### 方案 C：控制式 Agent（LangGraph：固定流程 + 条件分支 + 有界循环 + 显式状态）

```
自然语言 → Agent(LangGraph)
        → Question Analysis → Schema Linking → Few-shot Retrieval
        → [后续能力: 复杂问题任务拆解]
        → SQL Generation → SQL Validation(独立安全校验层) → SQL Execution
        → [后续能力: 失败修复循环 N 次,带错误反馈]
        → Structured Result
        → [后续能力: Result Analysis → Visualization → Conclusion  → Multi-turn 记忆]
```

---

## 2. 六维度对比

| 维度 | A 直连式 | B 增强流水线 | C 控制式 Agent |
|---|---|---|---|
| 实现复杂度 | 极低 | 中（流水线 + 自拼修复逻辑） | 中高（LangGraph 状态设计一次性成本，按 B 风格裁剪后增量可控） |
| 可维护性 | 差（prompt 混在一个函数，改一处全崩） | 好（模块清晰，但修复逻辑与主流程耦合，多轮需自建） | 好（节点边界清晰，state 显式，条件边/循环显式，易插拔） |
| 准确率 | 低（无 schema 裁剪、无示例、无校验，实际表现需本项目实验验证） | 较高（先行设计预期；提升幅度需本项目消融实验验证） | 高（设计预期；在 B 基础上增加复杂任务拆解与反馈循环，收益需本项目实验验证） |
| 可评测性 | 差（无中间态，出错无法定位环节） | 中（可记录中间产物，但多轮/分支难还原） | 强（每个节点输入输出可回放；Loop 次数、分支路径都是评测维度；天然支撑消融实验与 Bad Case 归因） |
| 开发成本 | 极低 | 低 | 中（LangGraph 学习成本 + 状态设计成本一次性） |
| 答辩展示效果 | 差：一个黑盒 demo | 中：能讲链路，但"Agent"名不副实 | 强：状态图可视化 = 现成答辩图；固定流程 + 条件分支 + 有界循环 + Trace 都有故事可讲；任务书指定 LangGraph 名正言顺 |

---

## 3. 为什么比"简单 LLM→SQL"更值得采用（对 A 的正式反驳）

1. **任务书硬性要求**：Schema 理解、SQL 语法校验、SQL 异常自修复、多轮追问、可视化、评测——A 方案一项都不满足，B/C 是及格线。
2. **准确率预期（研究假设，非本项目实测）**：公开研究表明 schema linking 与 few-shot 是 Text2SQL 准确率的主要杠杆（如 DAIL-SQL 在 Spider 上 86.6% EX、裸生成基线明显更低——**均为文献报道结果**）。本项目以这些研究结果作为设计假设，**具体数字必须通过本项目实验测量**。
3. **安全要求**：A 方案"生成即执行"正是 Vanna 公开漏洞（CVE-2024-5753 相关攻击链）的形态，违背本项目"SQL 生成与 SQL 执行之间必须存在独立安全校验层"的原则。
4. **结论一致性（后续能力）**：只有 C 能把"结论"与"查询结果"绑定校验，A/B 的返回物没有承载"分析"的边界。

---

## 4. B 与 C 的关键差异：什么时候需要"Agent"，什么时候只是"流程"

- **流水线（B 足够）**：单轮、结构中等、无状态问题 → 顺序执行即可。阶段 1 最小基线即形态。
- **状态机（C 的必要性）**：
  1. 校验失败 / 执行失败 → 修复 → 重试的**有界循环**（后续能力；B 用 while 也能写，但不可观测、不可配置、不可回放）；
  2. 复杂问题上"拆解或直接生成"的**条件分支**（后续能力；取决于问题理解节点输出）；
  3. 多轮对话的**状态保持**（后续能力；历史 schema 子集、上轮结果、指代上下文）;
  4. 每个节点独立限流/重试/日志，评测时**单节点插桩**（消融实验）。
- 这些不是"把简单函数拆成节点"的表演需求，而是真实存在的控制流需求。**因此推荐 C，但按 B 的克制风格实现**（见下）。

---

## 5. 推荐方案：C 的工程化裁剪版（最终决策）

**采用：方案 C——LangGraph 控制式 Agent。**

明确原则：

1. **不用自由 ReAct 作为主架构**：模型不决定"下一步做什么"，控制流全部在图上显式定义（固定主流程 + 条件分支 + 有界循环 + 显式状态）→ 可控、可测试、可复现、成本可控、适合课程项目答辩。
2. 每个节点默认只有一个 LLM 调用；**简单问题不触发额外节点**（零额外成本）。
3. 修复循环（后续能力）通过条件边实现，上限 N=3（可配置），超限降级回答（给出错误说明并建议改写问题）。
4. 复杂任务拆解、多轮、结论一致性、多候选等为**后续能力扩展**，阶段 1 主基线不混入（见第 6 节）。
5. SQL 生成与 SQL 执行之间**必须有独立安全校验层**（见第 8 节），不允许"生成即执行"。

**运行时 LLM**：Mimo V2.5 Pro API（OpenAI-compatible 适配层，可替换）。
**开发 Agent**：TRAE + DeepSeek-V4-Pro（工程实施，不是运行时模型）。

---

## 6. LangGraph 使用原则与初步状态流

### 6.1 使用原则

1. 只有**控制流要害**才建模成节点：条件分支、循环、可复用的工具封装；
2. 一次 prompt 封装 ≠ 一个节点（如"结果分析+结论生成"可合并为一个节点）；
3. **State 显式化**：所有中间产物进 state，禁止节点间隐式传参；
4. **checkpointer** 用于多轮（thread_id = 会话 ID，后续能力）；
5. 每个节点函数纯 Python 可测，LangGraph 只负责编排（业务逻辑不依赖 LangChain 高层封装，避免框架锁死）。

### 6.2 阶段 1 最小基线链（Minimal Text2SQL Baseline Pipeline）

> 注意：以下为阶段 1 唯一主线，共 **7 个阶段**（Minimal Text2SQL Baseline Pipeline）。

```
自然语言问题
   ↓
1. Question Analysis        理解意图/主题/时间范围；阶段 1 以单轮为主
   ↓
2. Schema Linking           表/列候选打分裁剪（规则+LLM），输出 schema 子集（含选择依据/Trace）
   ↓
3. Few-shot Retrieval       SQL 骨架相似度 + 场景标签检索示例
   ↓
4. SQL Generation           基于裁剪 schema + 示例生成 SQL
   ↓
5. SQL Validation           独立安全校验层：sqlglot AST + schema 存在性 + 安全策略
   ↓
6. SQL Execution            只读连接、超时、行数上限、错误捕获
   ↓
7. Structured Result        结构化结果输出（表头 + 行 + 元信息 + Trace）
```

**阶段 1 明确不纳入主基线**（后续能力扩展）：

- SQL Repair
- Task Decomposition
- Multi-turn Context
- Conclusion / 结论一致性校验
- 完整图表生成
- 用户管理
- 多 Agent Consensus
- Multi-candidate SQL

### 6.3 完整系统目标状态流（后续阶段，说明用）

```
                       ┌─────────────────────────────┐
   用户问题 ──────────▶│ question_analysis           │ 理解意图/难度/主题；合并历史上下文（指代消解）
                       └─────────────┬───────────────┘
                                     ▼
                       ┌─────────────────────────────┐
                       │ schema_linking              │ 表/列候选打分裁剪（规则+LLM），输出 schema 子集
                       └─────────────┬───────────────┘
                                     ▼
                       ┌─────────────────────────────┐
                       │ example_retrieval           │ SQL 骨架相似度+标签检索 few-shot
                       └─────────────┬───────────────┘
                                     ▼
                       ┌─────────────────────────────┐
                       │ [复杂?] task_decomposition  │ 仅复杂问题：拆子任务（后续能力）
                       └─────────────┬───────────────┘
                                     ▼
                       ┌─────────────────────────────┐
                       │ sql_generation              │ 生成 SQL（单条或多条）
                       └─────────────┬───────────────┘
                                     ▼
                       ┌─────────────────────────────┐
                ┌──────│ sql_validation              │ 独立安全校验层：sqlglot AST + schema + 安全策略
                │      └─────────────┬───────────────┘
                │   [通过]           │ [失败→error_feedback]
                │                    ▼
                │      ┌─────────────────────────────┐
                │      │ sql_execution               │ 只读连接、超时、行数上限
                │      └─────────────┬───────────────┘
                │        [成功]      │ [失败→error]
                │                    ▼
                │      ┌─────────────────────────────┐
                │      │ result_analysis             │ 结果解读、数值校验（后续能力）
                │      └─────────────┬───────────────┘
                │                    ▼
                │      ┌─────────────────────────────┐
                │      │ conclusion & visualization  │ 文字结论+图表规格（后续能力）
                │      └─────────────┬───────────────┘
                │                    ▼
                │              返回用户（写入多轮记忆）
                │
                └──▶ ┌─────────────────────────────┐
                     │ sql_repair  (次数 < N)      │ 带错误反馈修复；超过 N 次 → 降级回答（后续能力）
                     └─────────────┬───────────────┘
                                   └──▶ 回到 sql_validation
```

**AgentState（初稿）**：

```
question, history_slots(多轮继承的实体/条件), difficulty_level,
schema_subset, retrieved_examples, decomposed_tasks,
sql_candidates, validation_reports, exec_results,
repair_count, analysis, chart_spec, conclusion,
trace(节点级日志), session_id
```

---

## 7. 数据库设计（SQLite 电商库）——最终决策

### 7.1 表结构（初版 DDL 语义）

| 表 | 核心字段 | 主键 | 外键 | 时间分析 | 聚合/JOIN 关键 |
|---|---|---|---|---|---|
| users | user_id, name, gender, birth_date, province, city, register_time, status | user_id | — | register_time（注册趋势）、birth_date（年龄分组） | 与 orders 1:N |
| categories | category_id, name, parent_id | category_id | parent_id→categories | — | 品类层级（大/中/小类） |
| products | product_id, name, category_id, brand, price, cost, status, listing_time | product_id | category_id | listing_time（上架分析） | 与 order_items 1:N |
| orders | order_id, user_id, order_time, status(待支付/已支付/已发货/已完成/已取消/退款), total_amount, pay_time, province, city, channel(渠道) | order_id | user_id | **order_time/pay_time 核心时间轴** | 与 order_items 1:N；与 users N:1 |
| order_items | item_id, order_id, product_id, quantity, unit_price, discount, subtotal | item_id | order_id, product_id | —（继承订单时间） | JOIN 枢纽；金额聚合主力 |
| payments（可选扩展） | pay_id, order_id, pay_time, method, amount, status | pay_id | order_id | pay_time | 支付方式分析 |
| reviews（可选扩展） | review_id, order_id, product_id, user_id, rating, content, review_time | review_id | order_id | review_time | 评分/口碑分析 |

### 7.2 金额字段业务语义（统一口径，唯一权威定义）

> 数据生成、Schema 描述、Prompt/Example、评测数据说明必须**四端一致**遵循以下口径。

**`order_items.subtotal` = 商品明细行金额（line-item amount）**

> 单个订单明细行的金额，即该行商品的价格 × 数量的明细金额。

**`orders.total_amount` = 订单最终实付金额（final paid order amount）**

> 整个订单最终支付的金额，包含所有订单级调整。

**两者不要求天然相等**。差异来自可解释的业务因素：

- 商品折扣（明细行 discount）
- 订单级优惠（满减/优惠券等）
- 运费
- 税费
- 退款
- 其他订单级金额调整

> **明确禁止**：把两个字段的差异写成"数据随机造成的误差"。后续生成测试数据时，也必须按照上述业务语义设计（每个差异项要有明确来源）。

**口径示例**：`sum(order_items.subtotal)` 与 `orders.total_amount` 是两个合法的不同口径，分别回答"商品明细金额合计"与"订单实付金额合计"。Schema 注释、示例、评测 gold 都必须写明所用口径，系统不得存在"说不清哪个是真的"的状态。

### 7.3 数据规模（两档，唯一权威定义）

#### 开发阶段规模（阶段 1 及普通开发/调试/常规测试使用）

| 表 | 规模 |
|---|---:|
| users | 约 2,000 |
| categories | 约 30 |
| products | 约 500 |
| orders | 约 10,000 |
| order_items | 约 30,000 |

> 实际生成结果允许轻微误差，但设计目标以此为基准。**阶段 1 只实现开发阶段规模**，不生成 20 万订单。原因：阶段 1 优先验证 Text2SQL 链路正确性，而非 SQLite 大数据性能。

#### 性能测试规模（后续性能/扩展性验证使用）

| 表 | 规模 |
|---|---:|
| users | 约 20,000 |
| categories | 约 50 |
| products | 约 3,000 |
| orders | 约 200,000 |
| order_items | 约 600,000 |

> 第二档**不是当前功能验收条件**，不得写成阶段 1 的 P0 功能要求。用途：查询性能测试、P50/P95 延迟、大数据量执行稳定性、工程扩展性验证。

### 7.4 其他设计要点

- 所有实体带**业务口径注释**（如 `status` 枚举含义、金额口径定义），注释进入 schema 元数据，作为 Schema Linking 输入；
- 时间字段统一存 `YYYY-MM-DD HH:MM:SS`（SQLite TEXT 或整型时间戳二选一，按 SQLite 日期函数习惯定，建库脚本中统一）；
- 索引：order_time、user_id、product_id、category_id 建索引（JOIN/过滤性能）；
- 时间跨度 2023-01～2026-08，设计节假日/大促效应（双 11、618 等），让分析题有"故事"可讲。

---

## 8. 安全设计（最终决策，核心地位）

> 核心原则：**SQL 生成与 SQL 执行之间必须存在独立安全校验层。**"模型生成 SQL ≠ 可以直接执行 SQL。"安全校验由确定性代码执行，不依赖 LLM 自觉。

| # | 风险 | 策略 |
|---|---|---|
| 1 | SQL 注入 | 模型输出不直接拼接调用；所有 SQL 走 sqlglot AST 解析；**禁止多语句**（仅允许单条）；字符串值内的引号/注释等由 AST 结构天然隔离；数据库连接只读 |
| 2 | 危险 SQL（DML/DDL） | **默认只读 SQL**：AST 根节点必须为 SELECT；禁止 INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE / CREATE / ATTACH / PRAGMA(write) / REPLACE / LOAD_EXTENSION；SQLite 专属危险函数/语句单独拦截 |
| 3 | 只读数据库 | 连接使用 `file:xxx.db?mode=ro` + `PRAGMA query_only=ON` 双保险；应用层不持有写连接 |
| 4 | Prompt Injection | 结构分离：system/任务指令、schema 数据、历史对话分块拼接并对边界做标识；问题文本仅作为"查询意图"注入；示例库 SQL 入库必须过校验器+人工审核（吸取 Vanna 训练投毒教训）；模型输出解析严格按格式（SQL 提取），拒绝执行格式外内容；禁止模型"生成工具调用指令" |
| 5 | 查询超时 | SQLite `progress_handler` / 语句级超时（可配置，如 5s）；执行器开启独立线程看门狗，超时即中断并返回受控错误 |
| 6 | 结果行数限制 | 生成阶段提示 + 校验阶段强制注入 `LIMIT ≤ 500`（AST 改写，不接受模型自己写的更大值）；结果集大小限制（可配置，如 2MB） |
| 7 | 敏感字段 | 电商合成数据不生成真实敏感信息（手机号、身份证不出现）；schema 元数据维护"受限列"清单（如有），受限列不出现在 schema 视图并禁止 SELECT * 命中后输出 |
| 8 | 错误信息泄露 | 对外仅输出友好提示（"问题无法解析，建议换种问法"）；内部错误详情（表名、堆栈、schema）只进 trace/log，不进用户响应 |

---

## 9. 项目目录规划（规划稿，阶段 2 开始创建）

```
项目根/
├── docs/                    # 文档（本阶段已建）
├── src/
│   ├── agent/               # LangGraph 组装
│   │   ├── state.py         #   AgentState 定义
│   │   ├── graph.py         #   节点/边/条件边组装
│   │   └── nodes/           # question_analysis, schema_linking, example_retrieval,
│   │                        #   sql_generation, sql_validation, sql_execution, structured_result
│   │                        #   （后续能力）task_decomposition, sql_repair, result_analysis, conclusion
│   ├── llm/                 # LLM 适配层（OpenAI-compatible，默认 Mimo V2.5 Pro，可切换）
│   ├── schema/              # schema 元数据加载、注释口径、linking 打分
│   ├── retriever/           # few-shot 检索（骨架相似度/BM25/标签）
│   ├── validator/           # sqlglot 封装：语法/结构/安全策略/行数改写（独立安全校验层）
│   ├── executor/            # 只读执行器（超时/行数/错误捕获）
│   ├── analyzer/            # 结果分析、结论生成、一致性校验（后续能力）
│   ├── visualizer/          # ECharts option 规格生成（后续能力）
│   ├── prompts/             # 版本化 prompt（yaml/json + 版本号）
│   ├── api/                 # FastAPI 路由、请求/响应模型、会话管理
│   └── utils/               # 日志、trace、配置加载
├── db/                      # 建库 DDL、数据生成器、种子数据（生成物不入 git）
├── data/
│   ├── eval/                # 测试集（json）、gold SQL、bad cases
│   └── examples/            # few-shot 示例库
├── evaluation/              # 评测入口：runner、指标计算、报告生成、消融实验配置
├── tests/                   # 单元/集成测试（pytest）
├── web/                     # React + Vite + ECharts 前端
└── scripts/                 # 一键脚本：init_db / generate_data / run_eval / run_api
```

**克制原则**：阶段 2 初版只创建最小基线链所需模块（agent、llm、schema、retriever、validator、executor、prompts、api、db、evaluation、tests、data），每个模块首版 1～3 个文件，不预建空壳；`analyzer`、`visualizer` 及拆解/修复节点等后续能力不预建。

---

## 10. 技术栈清单（最终决策，选型不含"创新"含义）

- **后端**：Python 3.12+，FastAPI + uvicorn，Pydantic v2
- **Agent 编排**：LangGraph（任务书指定；当前 PyPI 最新 1.2.11）
- **SQL 校验**：sqlglot（零依赖）
- **数据库**：SQLite；数据访问可用 SQLAlchemy（如需要）或轻依赖 sqlite3 + pandas
- **运行时 LLM**：Mimo V2.5 Pro API（OpenAI-compatible 适配层，可替换）
- **开发 Agent**：TRAE + DeepSeek-V4-Pro（工程实施，非运行时模型）
- **前端**：**React + Vite + ECharts**（结论可视化，后续能力；阶段 1 不需要前端）
- **数据生成**：numpy/pandas + 自写规则生成器（固定 seed）
- **评测**：pytest + 自研评测 runner（EX、Pass@1 起步）
- **明确不引入**：向量数据库（检索用 BM25/规则）、Redis/K8s/微服务（单体即可）

---

## 11. 遗留决策

> 原"LLM 选型 / 拆解与多候选 / 测试集规模"三项待决已在本次基线收敛中全部关闭：LLM=Mimo V2.5 Pro；拆解/多候选降级为 Secondary/Optional；测试集分阶段（100→200→可选 300～350）。

以下为当前仍需项目负责人确认的事项（**不阻塞阶段 1 基线实现**）：

1. 前端图表集清单（阶段 1 不做前端，可晚定）：默认先支持折线/柱状/饼图/Top-N 条形 + 表格。
2. "Spider 对照实验"是否纳入正式交付（建议：可选增强项，视时间与质量决定）。
3. 阶段 1 结束时的量化验收线（如 EX、Pass@1 目标值）——需在建立 Baseline 并实测后再定标，不在实现前凭假设设线。