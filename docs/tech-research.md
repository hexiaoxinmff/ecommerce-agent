# 技术调研（Tech Research）

> 阶段：基线方案最终收敛（阶段 1）· 已按最终决策修订
> 日期：2026-09-14
> 调研方式：GitHub 仓库 + 官方文档 + 论文。原则：学工程思想，不复制代码。
> 引用来源见各小节链接。
>
> **数字来源说明**：本文所有涉及准确率、规模的数字，凡属文献/公开 benchmark 报道，一律标注为「文献报道结果」；本项目自身尚无实验数据，不写入任何未实测数字。

---

## 0. 本项目最终技术路线（调研结论先行对齐）

最终技术路线（唯一基线，见 `architecture-options.md`）：

- **前端**：React + Vite + ECharts
- **后端/Agent**：Python 3.12+ · FastAPI · LangGraph · SQLite · SQLAlchemy（如需要）· sqlglot · LLM API
- **架构**：LangGraph 控制式 Agent（固定主流程 + 条件分支 + 有界循环 + 显式状态），不用自由 ReAct 作为主架构
- **运行时 LLM**：**Mimo V2.5 Pro API**（OpenAI-compatible 适配）
- **开发 Agent**：TRAE + DeepSeek-V4-Pro（本项目工程实施助手，**不是运行时模型**）

---

## 1. 调研范围

- Text2SQL Benchmark（Spider 系、BIRD、R-Eval 评测协议）
- LLM-based Text2SQL 方法（DAIL-SQL、MAC-SQL、CHASE-SQL、Spider-Agent、R3）
- RAG/Text2SQL 框架（Vanna）
- SQL 解析/校验工具（sqlglot）
- Agent 编排（LangGraph 官方 SQL Agent 模板）
- 国内企业级项目（DB-GPT）

---

## 2. 重点参考项目逐项分析

### 2.1 Spider 1.0 / SParC / CoSQL（Yale XLANG Lab）

- 仓库：https://github.com/taoyds/spider （SParC、CoSQL 同组织，yale-lily.github.io/spider）
- 解决的问题：跨域 Text2SQL 标准评测。Spider 1.0：200 个数据库、10,181 条问题、5,693 条 SQL，按难度分 easy/medium/hard/extra-hard（以上均为**文献报道组件数据**）；SParC（4,298 组多轮交互）与 CoSQL（对话式）用于多轮评测。
- 值得借鉴的设计：
  - **执行准确率（EX）作为主指标**：比较 pred SQL 与 gold SQL 的执行结果，而非文本匹配——这是"结果可追溯"的评测哲学。
  - **难度分级**：按 SQL 组成（JOIN、嵌套、聚合多寡）给问题分档，便于分析性能够点。
  - **多轮评测形态**：SParC/CoSQL 的"多轮对话 + 每轮 gold SQL"结构，可直接指导我们后续阶段的多轮测试集构造。
- 不适合直接采用：数据量过大（200 库）；其电商相关数据库（多为英文 schema、小规模、语义泛化）不适合直接作为本项目的业务演示库；评测脚本面向批量文件，需改造为服务化评测。
- 是否采用：**部分采用**。采用其 EX 评测思想与难度分级；不直接使用其数据作为项目主库。
- 改造方式：自建测试集沿用 EX 计算逻辑，评估"是否正确回答问题"而非"SQL 是否与 gold 相同"。

### 2.2 test-suite-sql-eval（R-Eval 执行评测工具）

- 仓库：https://github.com/taoyds/test-suite-sql-eval
- 解决的问题：EX 的随机性缺陷——同一条 gold SQL 在某个数据库实例上结果恰好相同，掩盖谓词错误。R-Eval 对同一条问题生成多个数据库实例（扰动数值），全部实例结果一致才算正确（Test-suite Accuracy）。
- 值得借鉴：`plug_value`（把 gold SQL 中的值代入 pred SQL）、`keep_distinct` 等评测细节处理；多实例评测思想。
- 不适合直接采用：完全照搬 R-Eval 生成多实例成本高，初期可先做单实例 EX，把 R-Eval 列为评测增强项。
- 是否采用：**借鉴思想**。自建评测器时保留 `plug_value` 语义与"多实例"扩展点。
- 改造方式：评测器自研（轻量），兼容我们 JSON 格式的测试集，输出分难度/分类报告。

### 2.3 DAIL-SQL（阿里，Prompt 工程系统化研究）

- 仓库：https://github.com/BeachWang/DAIL-SQL （论文：VLDB 2024《Text-to-SQL Empowered by LLMs: A Benchmark Evaluation》）
- 解决的问题：什么 Prompt 形式、怎么选 Few-shot、怎么组织，对 Text2SQL 准确率影响最大（该论文在 Spider 上取得 86.6% EX——**文献报道结果**）。
- 值得借鉴的设计：
  - **问题表示**：question + evidence + schema 的结构化组织；
  - **示例选择**：按 **SQL 骨架相似度（skeleton similarity）** 选 Few-shot，比纯语义相似更贴合 SQL 结构需求；
  - **示例组织**：仅保留 question + SQL 以省 token；
  - **监督式 schema linking**：显式产出"用到哪些表/列"再生成 SQL。
- 不适合直接采用：其结论基于 GPT-4/CodeLlama 英文基准，中文电商场景需自建提示工程体系；离线+在线混合流程偏重，初期不必要。
- 是否采用：**重点借鉴**。骨架相似度示例检索、显式 schema linking 两个思想直接进入架构方案（创新候选 I2、I1）。
- 改造方式：示例检索用本地规则+BM25（无向量库依赖），骨架相似度做 SQL 归一化后比较。

### 2.4 MAC-SQL（多 Agent 协作框架）

- 仓库：https://github.com/wbbeyourself/MAC-SQL （论文 arXiv:2312.11242，北航+腾讯）
- 解决的问题：大 schema、复杂问题、坏 SQL 三个难点。三个角色：**Selector**（裁剪 schema）、**Decomposer**（拆分子问题逐步求解）、**Refiner**（执行反馈驱动修复）。
- 值得借鉴的设计：角色分工清晰、Refiner 的诊断三角度（语法/可执行/结果非空）、修复循环上限控制。
- 不适合直接采用：多 Agent 是"角色"而不是我们一定会开的多个进程/多次调用——成本高；论文实现面向基准批量跑分，无在线服务形态。
- 是否采用：**借鉴角色思想，压缩到单图内**。Selector→schema_linking 节点（阶段 1 基线即用）；Decomposer→task_decomposition 节点（后续能力，仅复杂题触发）；Refiner→repair 节点（后续能力，失败才触发）。
- 改造方式：不是三个独立 LLM Agent 聊天，而是一条状态机流水线中的条件节点，默认路径零额外 LLM 调用。

### 2.5 CHASE-SQL（多路径生成 + 选择）

- 仓库：https://github.com/xlang-ai/CHASE-SQL
- 解决的问题：单一生成易错，提出分治候选生成（divide-and-conquer、CoT、在线检索知识）+ 多候选选择器（论文在 BIRD 基准报道领先执行准确率——**文献报道结果**）。
- 值得借鉴：**divide-and-conquer 候选生成**（把复杂问题拆段分别生成再合并）与"任务拆解"思想一致；多候选+选择机制。
- 不适合直接采用：全量多候选+自一致性投票的 token 成本是普通方案的数倍，不适合作为默认路径。
- 是否采用：**列为 Secondary/Optional 创新候选**。仅作评测驱动优化阶段的实验项，用本项目实验数字决定是否保留。
- 改造方式：作为专项消融实验，不进入阶段 1 主基线。

### 2.6 Spider-Agent（xlang-ai，Agentic Text2SQL）

- 仓库：https://github.com/xlang-ai/Spider-Agent （Spider 2.0 配套方法，paper site: spider2-sql.github.io）
- 解决的问题：在"部分可观测"环境下，Agent 通过工具交互逐步探索 schema/data 完成任务（Spider 2.0：632 个真实企业库问题——**文献报道组件数据**）。
- 值得借鉴：工具化 schema 探索（list_tables → get_schema → execute）的交互模式；把"最终输出定义为可判定结果"的评测方式。
- 不适合直接采用：Spider 2.0 面向超大规模企业库（千列级），我们业务库规模小得多，完全开放式探索成本高且不稳定。
- 是否采用：**借鉴其工具划分粒度**，但编排为固定流程而非自由探索（与"不用自由 ReAct 主架构"一致）。
- 改造方式：schema 列表/取 schema/执行作为节点函数固化，禁止模型自由决定"下一步调什么"。

### 2.7 Vanna（RAG Text2SQL 框架）——含重要安全反面教材

- 仓库：https://github.com/vanna-ai/vanna （MIT）
- 解决的问题：用 RAG 方式训练（DDL / 文档 / 问答对 / SQL）实现"聊你的数据库"。
- 值得借鉴：训练语料分层（DDL + documentation + question-SQL）——我们的"业务口径词典"和示例库正对应此设计；自学习（成功问答沉淀）机制。
- **不适合直接采用 / 必须警惕**：其 Flask API 对训练数据与生成 SQL **无任何校验**，存在公开报告的攻击链（训练数据投毒 → 检索复现恶意 SQL → 直接执行，涉及 pg_read_file 等，关联 CVE-2024-5753 / CVE-2024-5827；社区 PoC 见 GitHub issue 报告）。这恰好是本项目"SQL 必须经过独立安全校验层"要求的反面案例，将作为我们安全设计的论据与答辩素材。
- 是否采用：**仅借鉴"训练语料分层"概念，完全自研**；其"生成即执行"模式是本项目明确禁止的。
- 改造方式：示例库入库必须走校验器 + 人工审核；生成 SQL 必须经 AST 校验与安全策略才可执行。

### 2.8 sqlglot（SQL 解析/校验/改写基础库）

- 仓库：https://github.com/tobymao/sqlglot （MIT，零依赖纯 Python）
- 解决的问题：跨方言 SQL 解析、AST 构建、格式化、优化、血缘。
- 值得借鉴/直接使用的能力：
  - `parse_one` 解析失败 = 语法校验；AST 遍历可检查语句类型（SELECT 白名单）、提取表和列（schema 存在性校验）、检测多语句；
  - `schema` 校验（列/表名存在性）、`optimizer` 归一化（用于骨架相似度与 EX 比较前归一）。
- 不适合直接采用：无（作为库使用，不修改其代码）。
- 是否采用：**采用为 SQL 校验层核心依赖**。它解决"确定性校验"，LLM 解决"语义校验"，二者分层。
- 改造方式：封装 `src/validator/`，输出结构化校验报告（错误类型 → 驱动后续 repair 提示词）。

### 2.9 LangChain / LangGraph 官方 SQL Agent 模板

- 地址：https://docs.langchain.com/oss/python/langchain/sql-agent （与 langgraph sql-agent 模板）
- 解决的问题：给出 SQL Agent 的流程轮廓（取表列表 → 选相关表 → 取 schema → 生成 → 检查 → 执行 → 修正 → 回答），以及 SQLDatabaseToolkit 工具化封装。
- 值得借鉴：流程总轮廓与我们一致；checkpoint 做多轮；"先限制表集合再生成"的顺序。
- 不适合直接采用：官方模板是"自由 ReAct 工具循环"，不可控、成本高、难评测；其 QuerySQLChecker（LLM 双重检查）作为唯一校验手段太弱。
- 是否采用：**借鉴节点顺序，替换为固定流水线 + 确定性校验器**（LangGraph 控制式 Agent）。
- 改造方式：StateGraph 显式定义节点与条件边（方案见 architecture-options.md 第 6 节），LLM 只在约定节点内被调用。

### 2.10 DB-GPT（中文企业级 Data Agent 框架）

- 仓库：https://github.com/eosphoros-ai/DB-GPT （Apache 2.0）
- 解决的问题：面向企业数据场景的完整 Agent 框架（含 Text2SQL、微调、知识库、多模型管理）。
- 值得借鉴：Text2SQL 微调数据构造方式（instruction 嵌入表/列/主外键说明）；企业级功能分层思想。
- 不适合直接采用：框架庞大（部署/学习成本高），引入 = 被框架绑架，与本项目"自研可控、可评测"冲突；微调不是本项目主路线。
- 是否采用：**不采用框架**；可参考其样本结构设计我们示例库的 JSON 格式。
- 改造方式：参考"schema 摘要拼进 instruction"的做法，设计我们的 prompt 结构。

### 2.11 R3（共识式多 Agent）

- 仓库：https://github.com/HanchenXia/R3 （论文 arXiv:2402.14851）
- 解决的问题：SQL-Writer + 多 Reviewer 辩论直至共识，用执行结果驱动修正（论文报道在 Llama-3-8B 上对 CoT 显著提升——**文献报道结果**）。
- 值得借鉴：执行结果反馈进入修正循环（与我们的 repair 闭环思想一致）；弱模型也能受益。
- 不适合直接采用：多 Agent 辩论 token 成本成倍、延迟高，不适合在线问答默认路径。
- 是否采用：**列为 Secondary/Optional 实验项**（评测阶段做"单生成 vs 共识"消融，用本项目实验数据说话）。
- 改造方式：仅当模型能力不足时，作为增强策略评估。

---

## 3. 调研结论（对我们的启示）

1. **评测哲学**：EX（执行一致性）> 文本匹配（Spider/R-Eval）。
2. **精度来源顺序（研究共识，需本项目实测验证）**：Schema Linking > Few-shot 质量 > 推理结构（CoT/分解）> 自我修复；修复不能替代前置质量，只能兜底。以上顺序来自公开研究，**本项目需通过消融实验验证在自己数据上的表现**。
3. **安全是真实痛点**：Vanna 的公开漏洞证明"生成即执行"不可接受，我们的校验层不是可选项而是硬要求。
4. **确定性工具 + LLM 混合**：sqlglot 管语法/结构，LLM 管语义，分层清晰可评测。
5. **成本意识**：多 Agent/多候选是高成本手段，只适合"复杂题失败后"的条件性增强，不适合默认路径。

---

## 4. 数据方案调研与推荐

### 4.1 三种候选

| 候选 | 说明 | 优点 | 缺点 |
|---|---|---|---|
| A. 直接用 Spider 电商库 | 取 Spider 1.0 中 ecommerce 相关库 | 有 gold SQL、可对标文献 | 英文 schema、规模小（单库几十～百级行）、业务语义与中文场景脱节、无法支撑高质量业务评测 |
| B. 纯自建电商库 | 自设计 schema + 合成数据 | 完全可控、贴合产品、规模按两档设计、可以造出有意义的趋势/对比题 | 需要自写测试集 gold（成本可接受） |
| C. 组合：自建业务库为主 + Spider 部分库为通用性对照 | 主评测在自建库；Spider 抽取少量库做"跨库泛化"补充实验 | 兼顾产品演示与论文说服力 | 增加少量适配工作 |

### 4.2 推荐：C（主 B，辅 A）

**理由**：
1. 任务书要求"不少于 100 条测试问答集"且面向电商业务——自建库的每个问题都可精确标注难度/场景/gold，可支撑场景化评测（Spider 库做不到）。
2. 业务分析必须在口径可解释、自己可控的库上演示才自然（见表 4.3 金额口径）。
3. Spider 对照实验列为可选增强项而非主路径（中文问题需人工改写，成本高、收益待实验验证）。

### 4.3 自建库设计要点（详见 architecture-options.md 第 7 节）

- **表**：users / products / categories / orders / order_items（+ 可选 payments、reviews）
- **数据规模（两档，唯一权威定义见 architecture-options.md）**：
  - **开发阶段规模**（阶段 1 及普通开发/调试/常规测试使用）：users ≈ 2,000 · categories ≈ 30 · products ≈ 500 · orders ≈ 10,000 · order_items ≈ 30,000
  - **性能测试规模**（后续性能/扩展性验证使用，非当前功能验收条件）：users ≈ 20,000 · categories ≈ 50 · products ≈ 3,000 · orders ≈ 200,000 · order_items ≈ 600,000
  - 数据生成：规则化合成生成器（Python 脚本、固定随机种子 → 可复现）
- **金额业务口径（统一，唯一权威定义见 architecture-options.md 第 7 节）**：
  - `order_items.subtotal` = **商品明细行金额**（line-item amount）
  - `orders.total_amount` = **订单最终实付金额**（final paid order amount）
  - 两者不必相等，差异来自商品折扣 / 订单级优惠 / 运费 / 税费 / 退款等可解释业务因素；**不是数据随机误差**。
- **时间跨度**：2023-01 ~ 2026-08，覆盖年月周季度趋势、同比环比、节假日效应（双11、618 等电商特征可注入，让分析题有"故事"）。
- **可测试性**：字段设计必须能支撑第 4 节（project-understanding.md）的业务场景；每张表提供列注释（业务口径），作为 Schema Linking 的输入。