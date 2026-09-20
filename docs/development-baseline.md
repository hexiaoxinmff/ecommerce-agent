# 开发基线（Development Baseline）

> 阶段：基线方案最终收敛（阶段 1）· 已按最终决策修订
> 日期：2026-09-14
> 本文件记录**当前环境的客观事实**、**最终技术决策**与**后续开发的约束约定**，供所有后续开发会话参照。

---

## 1. 工作区现状（2026-09-14 实测）

| 项 | 状态 |
|---|---|
| 工作区路径 | `F:\基于 Text2SQL 的电商智能数据分析 Agent` |
| 既有代码 | **无**（空项目，检查时目录条目数为 0） |
| Git | 已安装（2.55.0.windows.2）；本阶段已 `git init`，尚未有提交 |
| 本阶段产物 | `docs/` 下 5 份文档 + `.gitignore`（本次为基线收敛修订，未引入任何代码） |

## 2. 运行环境

| 项 | 版本/位置 |
|---|---|
| Python | 3.12.10（`C:\Users\29593\AppData\Local\Programs\Python\Python312\python.exe`） |
| Node.js | v24.18.0 |
| npm | 12.0.2 |
| 操作系统 | Windows（工作目录含中文路径，注意编码与路径处理） |

## 3. 最终技术决策（基线收敛后唯一版本）

| 项 | 决策 |
|---|---|
| 前端 | **React + Vite + ECharts**（不再出现 Vue 作为候选） |
| 后端 / Agent | Python 3.12+ · FastAPI · **LangGraph** · SQLite · SQLAlchemy（如需要）· **sqlglot** |
| 运行时 LLM | **Mimo V2.5 Pro API**（OpenAI-compatible 适配；Text2SQL / 分析 / 修复等 Agent 推理默认模型） |
| 开发 Agent | **TRAE + DeepSeek-V4-Pro**（编写代码、修改文件、执行测试、辅助工程实现——**不是运行时模型**）；WorkBuddy + DeepSeek-V4-Pro 为辅助审查 |
| Agent 架构 | **LangGraph 控制式 Agent**：固定主流程 + 条件分支 + 有界循环 + 显式状态；**不用自由 ReAct 作为主架构** |
| 阶段 1 主线 | **最小 Text2SQL 基线链（7 阶段，Minimal Text2SQL Baseline Pipeline）**：自然语言问题 → Schema Linking → Few-shot Retrieval → SQL Generation → SQL Validation → SQL Execution → Structured Result |
| 阶段 1 不纳入 | SQL Repair / Task Decomposition / Multi-turn / 结论一致性 / 完整图表生成 / 用户管理 / 多 Agent Consensus / Multi-candidate SQL（均为后续能力扩展） |
| 运行时模型注意 | **绝不能把 DeepSeek-V4-Pro 写成项目运行时模型**；DeepSeek-V4-Pro 仅作为开发 Agent |

## 4. 数据库与数据约束（最终决策）

### 4.1 两档数据规模（唯一权威定义，见 architecture-options.md 第 7 节）

**开发阶段规模**（阶段 1 及普通功能开发 / 调试 / 常规测试）：

| 表 | 规模 |
|---|---:|
| users | 约 2,000 |
| categories | 约 30 |
| products | 约 500 |
| orders | 约 10,000 |
| order_items | 约 30,000 |

**性能测试规模**（后续性能 / 扩展性验证，**不是当前功能验收条件**）：

| 表 | 规模 |
|---|---:|
| users | 约 20,000 |
| categories | 约 50 |
| products | 约 3,000 |
| orders | 约 200,000 |
| order_items | 约 600,000 |

> 用途（性能档）：查询性能测试 / P50/P95 延迟 / 大数据量执行稳定性 / 工程扩展性验证。**"200,000 orders"等规模不得写成阶段 1 必须完成的 P0 功能要求。**

### 4.2 其它数据库约束

- 业务库：SQLite 单文件（`db/ecommerce.db` 为生成物，**不入 git**；由 `scripts/init_db.py` 一键重建）。
- 数据全部为**合成数据**（规则生成器 + 固定随机种子），不包含任何真实个人数据。
- 只读连接方式：`file:db/ecommerce.db?mode=ro` + `PRAGMA query_only=ON`。
- 时间口径：库内时间统一为一个时区与一种存储格式。
- **金额业务口径**（四端统一：数据生成 / Schema 描述 / Prompt 与示例 / 评测数据）：
  - `order_items.subtotal` = **商品明细行金额**（line-item amount）
  - `orders.total_amount` = **订单最终实付金额**（final paid order amount）
  - 两者不要求相等，差异来自商品折扣 / 订单级优惠 / 运费 / 税费 / 退款等**可解释业务因素**，**不是数据随机误差**。

## 5. Python 包现状

**已安装（系统环境）**：

```
fastapi 0.141.1 / uvicorn 0.52.4 / pandas 3.0.5 / numpy 1.26.4
pydantic 2.13.5 / requests 2.34.2
```

**未安装（本项目需要，阶段 2 在虚拟环境中安装）**：

```
langgraph（PyPI 最新 1.2.11）
openai（或目标提供商 SDK，用于调 Mimo V2.5 Pro，OpenAI-compatible）
sqlglot           # SQL 解析/校验（零依赖）
pytest / httpx    # 测试
python-dotenv     # 配置
SQLAlchemy        # 如需要（否则轻依赖 sqlite3 + pandas）
```

## 6. 依赖管理约束（重要）

1. **必须为项目创建独立虚拟环境**（Python 3.12 自带 `venv`），禁止继续往系统 Python 装项目依赖；当前系统环境已混装 fastapi/pandas，仅作为"已具备"记录，不作为项目依赖依据。
2. 依赖清单用 `requirements.txt`（或 `pyproject.toml`）锁定版本，评测报告必须记录依赖快照。
3. **不引入**：向量数据库、Redis、K8s、微服务框架、消息队列；端到端保持"单体 FastAPI + SQLite + 本地检索"。
4. 前端依赖独立管理（web/package.json，React + Vite + ECharts），与后端解耦；阶段 1 不建前端。

## 7. 开发约束（后续每阶段共同遵守）

1. **正确性 > 架构合理性 > 可验证性 > 可维护性 > 开发速度**（项目负责人明示的原则，不得颠倒）。
2. **评测先行**：新功能必须回答"为什么要加 / 加了以后有什么提升 / 怎么证明"，无实验支撑的"优化"不保留；消融实验为标配。
3. **SQL 安全红线**：SQL 生成与 SQL 执行之间必须存在**独立安全校验层**；任何路径生成的 SQL 必须经校验后才允许执行；禁止"生成即执行"（反面案例：Vanna 公开漏洞，见 tech-research.md 2.7）。
4. **输出可追溯**：每个输出（后续含结论/图表）必须绑定其 SQL 与执行结果。
5. **不虚构数据**：实验数据必须来自真实运行；模型能力以实测为准；数字来源只能为 ① 本项目实验 / ② 文献公开结果（标注）/ ③ 明确标注的设计假设；文档区分"已完成/规划中"。
6. **文档同步**：架构/prompt/评测集发生重大变更时，同步更新 docs/ 对应文件与变更记录。
7. **禁止事项**（继承项目负责人要求）：不自行更换项目方向、不加无关技术栈、不复制开源项目代码拼接为本项目、不修改与项目无关的文件。
8. **Prompt 版本化**：所有提示词存放在 `src/prompts/` 并带版本号，评测报告记录所用版本。
9. **开发 Agent 与运行时模型严格区分**：TRAE + DeepSeek-V4-Pro 是开发 Agent（工程实施），Mimo V2.5 Pro 是项目运行时 LLM；文档与代码注释不得混淆。

## 8. 文档体系规划（后续阶段逐步创建，当前不生成）

```
docs/
├── project-understanding.md   ✔ 已建（基线收敛完成）
├── tech-research.md           ✔ 已建（基线收敛完成）
├── architecture-options.md    ✔ 已建（基线收敛完成：含安全设计/目录规划/数据库/金额口径）
├── evaluation-plan.md         ✔ 已建（基线收敛完成：分阶段测试集/创新点分级）
├── development-baseline.md    ✔ 已建（本次修订）
├── project-task.md            （后续：任务书对齐与需求分解）
├── prd.md                     （后续：产品需求文档）
├── architecture.md            （后续：定稿架构，由 architecture-options 收敛而来）
├── database-design.md         （后续：DDL 定稿 + 口径词典）
├── agent-design.md            （后续：节点/状态/prompt 定稿）
├── api-design.md              （后续：接口契约）
├── evaluation.md              （后续：评测集与指标使用说明）
├── test-report.md             （后续：各轮评测报告）
├── deployment.md              （后续：部署说明）
└── records/                   （后续：AI 协作记录、prompt 版本历史、bad cases、实验记录、PPT 素材）
```

## 9. 里程碑建议（待项目负责人批准后执行；本阶段不执行）

### 阶段 2（建议）：最小 Text2SQL 基线链

1. 环境：创建 venv、安装锁定依赖、首次 git 提交（含本阶段 docs）。
2. 建库：`db/` 下 DDL + 生成器（**开发阶段规模**：users ~2,000 / categories ~30 / products ~500 / orders ~10,000 / order_items ~30,000）；`scripts/init_db.py`。
3. 实现**最小 Text2SQL 基线链（7 阶段）**：Question Analysis → Schema Linking → Few-shot Retrieval → SQL Generation → SQL Validation → SQL Execution → Structured Result。
   - 阶段 1 **不做**：Repair / 拆解 / 多轮 / 结论生成 / 前端。
4. 评测 harness 最小版：`evaluation/runner.py` + EX / Pass@1 / 执行成功率计算（启用 E1 Schema Linking、E2 Few-shot 消融），在 100 条单轮测试集上输出第一份分数卡。
5. 评审点：项目负责人审核基线产出与分数卡，再决定后续能力扩展顺序。

### 阶段 3（建议）：完整能力

Repair 闭环、Multi-turn（checkpointer）、Task Decomposition、结论生成 + 一致性校验、可视化、WebApp（React + Vite + ECharts）。各能力接入顺序由阶段 2 评审点依据实测数据决定。

### 阶段 4（建议）：评测冲刺

测试集扩展至 200 条 + 多轮组（最终视质量决定是否 300～350）、全指标报告、消融实验 E1～E7、Bad Case 迭代、性能测试（性能档数据规模）。

### 答辩准备（贯穿）

Trace 可视化、实验对比图、demo 脚本（预设高光场景：复杂多表题、安全拦截演示、口径题、后续的多轮追问）。

## 10. 当前待决事项

> 原"LLM 选型 / 拆解与多候选 / 测试集规模"三项已在基线收敛中关闭（Mimo V2.5 Pro；降级为 Secondary/Optional；分阶段 100→200→可选 300～350）。

1. 阶段 1 结束时的量化验收线（EX / Pass@1 目标值）：建议**先建立 Baseline 并实测**后再定标，不在实现前凭假设设线。
2. Mimo V2.5 Pro 的 API base_url / key 接入方式：由项目负责人提供后写入 `.env`（不入 git），`src/llm/` 适配层按 OpenAI-compatible 实现。
3. "Spider 对照实验"是否纳入正式交付：建议可选增强项。