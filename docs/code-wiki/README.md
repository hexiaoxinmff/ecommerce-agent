# Code Wiki · 基于 Text2SQL 的电商智能数据分析 Agent

> 本 Wiki 面向**代码维护者与二次开发者**，从「整体架构 → 模块职责 → 关键类与函数 → 依赖关系 → 运行方式」五个维度，对仓库做一次结构化、可导航的完整梳理。
>
> 与 `docs/` 下既有的 30 份**设计/验收类**文档不同：既有文档回答「为什么这样设计」，本 Wiki 回答「代码长什么样、在哪里、怎么串起来、怎么跑」。两者互补，不重复。

---

## 0. 一句话理解这个项目

用户用中文提问（如「2025 年每月销售额是多少？」），系统沿一条**固定的 LangGraph 有界状态图**自动完成
`Schema Linking → Few-shot 检索 → SQL 生成 → SQL 安全校验 → 只读执行 →（失败则 ≤1 次自修复）→ 结构化结果 + 全链路 Trace`，
全程**只读**、**可验证**、**可评测**。

---

## 1. Wiki 导航

| 文档 | 内容 | 适合谁 |
|---|---|---|
| [01-架构总览.md](./01-架构总览.md) | 分层架构、端到端数据流、LangGraph 状态机、目录结构 | 所有人（先读这篇） |
| [02-后端模块与关键代码.md](./02-后端模块与关键代码.md) | 后端 15 个子包的职责边界 + 关键类/函数签名与行为说明 | 后端开发者 |
| [03-API参考.md](./03-API参考.md) | 18 个 REST 端点的请求/响应/状态码约定、鉴权要求 | 前后端 / 联调 |
| [04-前端架构.md](./04-前端架构.md) | React 19 + Vite 前端：路由、状态、认证上下文、组件树、图表映射 | 前端开发者 |
| [05-数据与评测体系.md](./05-数据与评测体系.md) | SQLite Schema 与业务口径、ECO-SQL-Bench v1.1、评测 Runner 与门禁 | 数据 / 评测 |
| [06-依赖与运行方式.md](./06-依赖与运行方式.md) | 依赖清单、模块依赖图、环境变量、安装/启动/测试/评测全流程 | 所有人（部署必读） |

---

## 2. 快速事实卡

| 项目 | 值 |
|---|---|
| 项目性质 | 课程 / 科研项目交付物（本地 Demo，非生产系统） |
| 后端 | Python 3.12+ / FastAPI / LangGraph / sqlglot / 标准库 `sqlite3` |
| 前端 | React 19 + Vite 8 + TypeScript + ECharts 6 + **自定义 CSS** |
| 业务数据库 | SQLite `db/ecommerce.db`（5 张表，**强制只读**） |
| 应用数据库 | SQLite `db/app.db`（`auth_user` / `auth_session` / `query_history`） |
| LLM Provider | 可插拔抽象：`mimo`（基线）/ `bailian`（推荐运行）+ 免费模型池 fallback |
| Agent 编排 | LangGraph 有界状态图（`repair_count ≤ 1`、`execute_count ≤ 2`） |
| API 端点数 | **18 个**（12 个 router；需鉴权 6 ／ 公开 12） |
| 测试 | `967 passed / 1 skipped`（`python -m pytest backend/tests`） |
| 评测基线 | **ECO-SQL-Bench v1.1 + Prompt V1.3 + FEWSHOT_V3(23 例) + Mimo V2.5 Pro = 90.0% EX** |
| 一条命令启动 | `python scripts/start_dev.py` |

---

## 3. 三条主线（记住这三条即可读懂全部代码）

**主线一：一次查询的数据流**
```
HTTP POST /api/agent/analyze
  → agent/graph.run_agent()
  → LangGraph 8 节点串行 + 2 处条件分支
  → 每节点产出 TraceEvent
  → AgentResult（SQL / 结果行 / 计数 / Trace / 耗时）
  → 按登录用户写入 query_history
```

**主线二：LLM 调用如何被隔离**
```
所有上层模块只依赖 llm/provider.LLMProvider(Protocol)
  → 唯一分派入口 llm/provider.get_llm_provider() 按 LLM_PROVIDER 返回
     ├─ MimoProvider        （openai SDK 仅允许出现在 llm/ 层）
     ├─ BailianProvider
     └─ FreeTierFallbackRouter（免费模型池自动 fallback）
```
> 硬约束：`openai` SDK 只允许出现在 `backend/app/llm/` 内，上层出现 `import openai` 即违规。

**主线三：SQL 永不写库**
```
sqlgen/safety.check_sql_safety()    ← sqlglot AST：单条 + 只读 + 白名单
sqlcheck/scope_validator.check_sql_scope() ← 别名/限定符作用域
db/sqlite.get_connection()          ← URI mode=ro（文件级只读）
                                    + PRAGMA query_only=ON（会话级只读）
```
四道闸门分布在「生成后校验」「执行前校验」「连接层」三个位置，任一失败都不会触碰数据库。

---

## 4. 目录速查（顶层）

```text
backend/app/          # FastAPI 应用主体（15 个子包，见 02）
backend/tests/        # pytest（967 passed / 1 skipped）
frontend/src/         # React 单页应用（pages / components / api / auth / styles）
data/eval/            # ECO-SQL-Bench v1.1（100 题）
data/fewshot/         # FEWSHOT_V3（23 例）
data/prompts/         # Prompt 快照 v1 / v1.1 / v1.3
evaluation/           # 评测框架（runner / metrics / normalization / report）
scripts/              # 初始化 / 校验 / 启动 / 评测 等脚本
db/ecommerce.db       # 业务库（只读）；db/app.db 应用库（可写）
docs/                 # 既有设计文档 30 份 + 本 code-wiki/
reports/              # 评测报告与冻结实验证据
```

---

## 5. 阅读建议

- **第一次接触项目**：按 `README.md`（项目介绍）→ 本文件 → `01-架构总览.md` → `06-依赖与运行方式.md` 跑起来。
- **要改后端逻辑**：`01-架构总览.md`（确定改哪一层）→ `02-后端模块与关键代码.md`（定位类/函数）。
- **要改前端**：`04-前端架构.md`。
- **要跑评测**：`05-数据与评测体系.md` + `06-依赖与运行方式.md`。

> 本 Wiki 内容基于仓库真实代码与生成，不含推测。若与代码冲突，以代码为准，并请同步更新本 Wiki。
