# 基于 Text2SQL 的电商智能数据分析 Agent

> 课程项目 / 本地 Demo。通过自然语言提问，自动完成「Schema Linking → Few-shot 检索 → SQL 生成 → 安全校验 → 只读执行 → 结构化结果」全链路电商数据分析。
>
> 最终回归基线：**ECO-SQL-Bench v1.1 + Prompt V1.3 + FEWSHOT_V3（23 例）+ DB dev-2026-09-14 + Mimo V2.5 Pro = 90.0% EX**。

---

## 1. 项目简介

本项目是一个面向电商业务场景的智能数据分析系统（课程 / 科研项目交付物）。用户以自然语言提问（如“2025 年每月销售额是多少？”），系统基于 LangGraph 控制式 Agent 沿固定链路自动生成并**只读执行** SQL，返回结构化结果与全链路 Trace，全过程可验证、可纠错、可评测。

- 业务数据库：自建 SQLite 电商库（5 张核心表，规则化合成数据，固定种子可复现）。
- 评测体系：项目自建 **ECO-SQL-Bench v1.1**（100 条单轮问题），以执行准确率（EX）为核心指标。
- 创新机制：**E3 — Gold-independent Fan-out 风险检测 + 条件触发 Hint**（proof of concept，已冻结）。

本项目**不是**：普通 AI 聊天机器人、普通 BI 后台、纯 Text2SQL Demo、单纯 SQL 生成器。

## 2. 核心能力

| 能力 | 说明 |
|---|---|
| 自然语言 → SQL | 沿固定 Agent 链路生成 SQL 并自动执行 |
| Schema Linking | 识别问题相关的表 / 字段 / 理由 / 置信度，经真实 Schema 复核 |
| Few-shot 检索 | 规则型、可解释的本地示例检索（Top-K，不依赖向量库） |
| SQL 安全校验 | 只读白名单 + 多语句禁止 + AST 校验 + 表/列存在性校验；`LIMIT ≤ 500` 强制注入 |
| SQL 只读执行 | `mode=ro` + `PRAGMA query_only=ON` 双重只读保护，结果截断保护 |
| SQL 自修复 | 有界 `≤1` 次 Repair（Repair 后二次校验 + 二次执行） |
| 全链路 Trace | 每节点成功 / 失败 / 跳过事件 + 耗时，可归因、可回放 |
| 评测闭环 | 100 条 Benchmark + Gold Hash Gate + Leakage Gate + 自动落盘报告 |
| 用户认证与查询历史 | 注册 / 登录 / 当前用户 / 登出（Bearer session）；查询历史按登录用户隔离记录与删除 |

## 3. 系统架构

```text
Frontend (React 19 + Vite + ECharts, 自定义 CSS)
    │  HTTP / JSON (POST /api/agent/analyze)
    ▼
Backend (FastAPI)
    ├── /api/health         健康检查（含 SQLite 只读探活）
    ├── /api/auth/register  注册（201；冲突 409）
    ├── /api/auth/login     登录（签发 Bearer access_token）
    ├── /api/auth/me        当前用户（Bearer）
    ├── /api/auth/logout    登出（删除当前会话）
    ├── /api/history        查询历史（按登录用户隔离，分页）
    ├── /api/history/{id}   删除一条历史（仅本人）
    ├── /api/system/database 数据库信息（只读）
    ├── /api/llm/test       LLM Provider 连接测试
    ├── /api/schema/link    Schema Linking
    ├── /api/fewshot/retrieve Few-shot 检索
    ├── /api/sql/generate   SQL 生成（只生成不执行）
    ├── /api/sql/execute    SQL 只读执行
    ├── /api/sql/repair     SQL 修复（单独测试）
    ├── /api/sql/execute-with-repair  有限 Repair 闭环（≤1 修复 / 2 执行）
    └── /api/agent/analyze  LangGraph Agent 编排（核心入口，需 Bearer 登录）
             │
             ├── SchemaLinker → FewShotRetriever → SQLGenerator(LLM) → SQL Safety → SQLExecutor
             │   └─（数据库执行错误时）→ SQLRepairer(≤1) → 二次 Safety/执行
             │
             ▼
        SQLite (db/ecommerce.db, 只读)
             │         ▲
             │         │ 评测
   Mimo V2.5 Pro (OpenAI-compatible)   ECO-SQL-Bench v1.1 + evaluation/ 评测框架
```

Agent 图（LangGraph）：`START → schema_link → fewshot_retrieve → sql_generate → sql_safety → sql_execute →（repair ≤1）→ sql_execute_repaired → result → END`。有界：`repair_count ≤ 1`、`execute_count ≤ 2`，绝不无限循环。

## 4. 技术栈

**实际使用（本项目实测）**：

| 层 | 技术 | 说明 |
|---|---|---|
| 语言 | Python 3.12+ | 后端 |
| Web 框架 | FastAPI | REST API + `/docs` 自动文档 |
| Agent 编排 | LangGraph | 有界状态图（显式节点 + 条件边） |
| 数据库访问 | sqlite3（标准库） | 只读连接 `mode=ro` + `query_only=ON` |
| SQL 解析 | sqlglot | AST 级安全校验 / 只读白名单 / LIMIT 注入 |
| LLM Provider | OpenAI-compatible Mimo API | `mimo-v2.5-pro`，官方端点为 OpenAI 兼容接口 |
| 前端 | React 19 + Vite + ECharts 6 + TypeScript | 单页应用 |
| 前端样式 | **自定义 CSS** | 未使用组件库 |

**明确未使用（与任务书技术栈清单的差异，如实声明）**：

- **SQLAlchemy 未使用** —— 数据库访问使用 Python 标准库 `sqlite3`；
- **Tailwind CSS 未使用**；
- **Ant Design 未使用**；
- 前端采用**自定义 CSS**（设计 Token + 深海军蓝主题，见 `docs/UI-UX.md`）。

> 因此文档与汇报中**不得**表述为“完全采用任务书所有技术栈”。

## 5. 项目目录

```text
.
├── backend/                 # FastAPI 后端 + LangGraph Agent
│   ├── app/
│   │   ├── main.py          # 应用入口（路由清单见 docs/API_ENDPOINTS.md，由脚本生成）
│   │   ├── api/routes/      # Health / System / LLM / Schema / Few-shot / SQL / Agent / Auth / History 路由
│   │   ├── agent/           # LangGraph 图、节点、状态、模型
│   │   ├── schema/          # Schema 元数据 + Linking
│   │   ├── fewshot/         # 示例数据集 + 规则型检索
│   │   ├── sqlgen/          # SQL 生成 + Prompt + 安全校验
│   │   ├── sqlexec/         # 只读执行器
│   │   ├── sqlrepair/       # 有限自修复
│   │   ├── sqlcheck/        # E3 Fan-out Detector（冻结）
│   │   ├── experiments/     # E3 Hint 模块（冻结）
│   │   ├── llm/             # Mimo Provider（OpenAI-compatible）
│   │   ├── trace/           # Trace 事件
│   │   ├── db/              # sqlite.py 业务库只读访问层 + appdb.py 应用库（认证 / 会话 / 历史）
│   │   └── core/config.py   # 全局配置（.env）
│   └── tests/               # pytest（967 passed / 1 skipped，2026-09-25 实测）
├── frontend/                # React 19 + Vite + ECharts 前端
├── data/
│   ├── eval/                # ECO-SQL-Bench v1.1（100 题）+ bad_cases/
│   ├── fewshot/             # FEWSHOT_V3（23 例）
│   └── prompts/             # sql_generator_v1 / v1.1 / v1.3.txt
├── db/ecommerce.db          # SQLite 业务库（dev-2026-09-14，脚本重建，只读访问）
├── db/app.db                # 应用库（auth_user / auth_session / query_history，scripts/init_auth_db.py 创建）
├── evaluation/              # 评测框架（runner / metrics / normalization / report）
├── scripts/                 # init_db / init_auth_db / validate / run_eval 等脚本
├── reports/                 # 评测报告与最终验收报告（冻结历史证据）
├── docs/                    # 项目文档（见 §18）
├── requirements.txt         # 后端依赖（最小必要集合）
├── .env.example             # 环境变量示例（真实 API Key 只在本机 .env）
└── README.md
```

## 6. 环境要求

| 依赖 | 版本 |
|---|---|
| Python | 3.12+（开发环境实测 3.12.10） |
| Node.js | 18+（Vite 8 实测可构建） |
| npm | 与 Node 配套 |
| 阿里云百炼 API Key | 可用的 `DASHSCOPE_API_KEY`（**推荐运行环境**，调用 SQL 生成 / Schema Linking / Repair / Agent 时必须；配置见第 8 节） |
| Mimo API Key | 可用的 `MIMO_API_KEY`（可选：正式评测基线 Provider `mimo-v2.5-pro`） |

## 7. 安装

### 7.1 克隆与准备

```bash
git clone <repo-url>
cd "基于 Text2SQL 的电商智能数据分析 Agent"
```

### 7.2 后端依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

> 依赖最小集合见 [requirements.txt](requirements.txt)：`fastapi`、`uvicorn`、`pydantic`、`python-dotenv`、`langgraph`、`sqlglot`、`pytest`、`httpx`、`openai`。

### 7.3 前端依赖

```bash
cd frontend
npm install
cd ..
```

### 7.4 生成业务数据库（可选）

```bash
python scripts/init_db.py
```

`db/ecommerce.db`（dev-2026-09-14 / seed 20260914）可由脚本重建，完全可复现。

### 7.5 初始化应用库（认证 / 查询历史必需）

```bash
python scripts/init_auth_db.py
```

创建 `db/app.db` 并初始化三张应用表：`auth_user`（账号，仅存 PBKDF2 口令哈希）、`auth_session`（会话，仅存 token 哈希）、`query_history`（查询历史）。幂等，可重复执行。

## 8. LLM Provider 配置

复制环境变量示例并填写真实值（**真实 API Key 只允许存在于本机 `.env` / 环境变量，严禁提交到 Git**）：

```bash
cp .env.example .env
```

**推荐运行环境（Demo / 日常运行）：阿里云百炼**。`.env` 关键项（均在 [backend/app/core/config.py](backend/app/core/config.py) 中读取）：

```text
LLM_PROVIDER=bailian
DASHSCOPE_API_KEY=<你的百炼 Key>
BAILIAN_MODEL=qwen3.7-flash
BAILIAN_PRIMARY_MODEL=qwen3.7-flash
LLM_MODEL_LOCK=true
```

> **口径声明**：正式历史评测基线（Clean Baseline v1.1，Mimo V2.5 Pro，90.0% EX）与当前
> Demo Runtime Provider 是两个不同口径。正式评测基线保持冻结，不因运行配置切换而改变。

可选：改用正式评测基线 Provider（Mimo）：

```text
LLM_PROVIDER=mimo
MIMO_API_KEY=<你的 Key>
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5-pro
MIMO_TIMEOUT=30
```

可选环境变量：

```text
ECOMMERCE_DB_PATH=db/ecommerce.db      # 覆盖业务库路径
APP_DB_PATH=db/app.db                  # 覆盖应用库路径（认证 / 会话 / 历史）
AUTH_SESSION_TTL_SECONDS=604800        # 会话有效期（默认 7 天）
CORS_ORIGINS=http://localhost:5173      # 逗号分隔，默认允许 Vite 前端
FEWSHOT_DATASET_PATH=...                # 覆盖 Few-shot 数据集路径
```

若未配置 Key，服务可启动，但所有依赖 LLM 的接口（`/api/llm/test`、`/api/schema/link`、`/api/sql/generate`、`/api/sql/repair`、`/api/agent/analyze`）将返回明确的“未配置”错误。

检验链路：

```bash
curl -X POST http://127.0.0.1:8000/api/llm/test \
  -H "Content-Type: application/json" \
  -d '{"prompt": "你好"}'
```

## 9. 数据库

- 路径：`db/ecommerce.db`（默认，可被 `ECOMMERCE_DB_PATH` 覆盖）。
- 5 张核心表：`users`（2000）/ `categories`(30) / `products`(500) / `orders`(10000) / `order_items`(30457)。
- **只读执行机制**：所有连接使用 SQLite URI `mode=ro`（文件级只读）+ `PRAGMA query_only=ON`（会话级只读）；写操作（INSERT / UPDATE / DELETE / DROP 等）会被直接拒绝。
- 结果截断保护：单次查询最多返回 500 行（`MAX_RESULT_ROWS`），超出标记 `truncated=true`。
- 口径约定（四端统一）：`order_items.subtotal` = 明细行金额；`orders.total_amount` = 订单最终实付金额；`cancelled` 订单不计入“实际销售”类统计。详见 `docs/database-schema.md`。

数据库信息查看：

```bash
curl http://127.0.0.1:8000/api/system/database
```

## 10. 启动（推荐：一条命令）

```bash
python scripts/start_dev.py
```

脚本会依次完成：**检查 Python / Node / 后端依赖 / 前端依赖 / `.env` / 数据文件 / 端口**
→ 启动 Backend `8000` + Frontend `5173` → 健康检查，最后输出：

```text
Backend : http://127.0.0.1:8000
Frontend: http://localhost:5173
Health  : OK
```

- Windows 也可双击 `scripts\start_dev.bat`（失败时窗口**不会闪退**，错误信息留在屏幕上）。
- 停止：前台按 `Ctrl+C`；若用 `--detach` 后台启动，执行 `python scripts/stop_dev.py`。
- 只做预检不启动：`python scripts/start_dev.py --check-only`。
- 换端口：`--backend-port 8001 --frontend-port 5174`。

失败场景都有**明确文案 + 退出码**（端口占用 7、`.env` 缺失 6、依赖缺失 3/5、
数据文件缺失 8、后端启动失败 9、前端启动失败 10），详见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) §2.5。

## 11. 启动（手动，两条等价命令）

上面的脚本调用的就是下面这两条命令，没有第二套启动体系：

```bash
cd backend
uvicorn app.main:app --reload   # 默认 http://127.0.0.1:8000
```

- 交互式 API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- ⚠️ 手动启动时若 5173 被占用，Vite 会**静默**改用 5174；脚本用 `--strictPort` 把它变成明确报错。

```bash
cd frontend
npm run dev        # 默认 http://localhost:5173
```

前端通过 `VITE_API_BASE_URL` 连接后端（默认 `http://127.0.0.1:8000`，见 `frontend/.env.example`）。

- 生产构建：`npm run build`（`tsc -b && vite build`）
- 代码检查：`npm run lint`（oxlint）

## 12. 使用示例

前端首页输入以下问题并点击分析（也可直接用 API）：

```text
哪个地区的用户最多？
哪个类目的销售额最高？
2025 年每月销售额是多少？
近30天销量最高的商品 Top 5 是哪些？
```

Agent API 需登录后调用（未登录返回 401）。先注册 / 登录获取 `access_token`（注册 / 登录 / 历史接口详见 [docs/API.md](docs/API.md)）：

```bash
curl -X POST http://127.0.0.1:8000/api/agent/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"question": "2025年每月销售额是多少？"}'
```

响应包含：`generated_sql`、`execution_result`（列 / 行 / 截断标记 / 耗时）、`execute_count` / `repair_count`、全链路 `trace`、`total_time_ms`。

## 13. API Overview

<!-- API-ENDPOINTS:BEGIN (generated by scripts/export_api_endpoints.py — do not edit) -->
**API 端点：18 个**（12 个 router；需鉴权 6 ／ 公开 12）。权威清单见 [`docs/API_ENDPOINTS.md`](docs/API_ENDPOINTS.md)。
<!-- API-ENDPOINTS:END -->

本节的端点总数与清单由 `scripts/export_api_endpoints.py` 从运行中的 FastAPI app 生成，
**不手工维护**；改代码即改清单，`backend/tests/test_api_endpoints_manifest.py` 负责在漂移时变红。

**认证与查询历史（已实现，Task37 起）**：本地注册 / 登录（PBKDF2 口令哈希 + Bearer session，库中只存 token 哈希）/ 当前用户 / 登出；Agent 查询成功与失败都会按登录用户写入查询历史，历史支持分页查询与本人删除、跨用户隔离。已知限制见 §17。

**当前版本未实现**（不虚构）：

- 多轮 conversation API（Multi-turn 属 PRD 阶段 2）。

## 14. Evaluation

### 14.1 评测数据集

**ECO-SQL-Bench v1.1**：100 条单轮问题（Easy 25 / Medium 30 / Hard 30 / Extra Hard 15），Gold SQL 全部人工审核 + 真实库执行 + `gold_result_hash` 记录（`data/eval/ecommerce_eval_v1.json`）。

### 14.2 运行评测

```bash
python scripts/run_eval.py                 # 完整 100 条（串行，耗时较长）
python scripts/run_eval.py --limit 10      # 前 10 条快速验证
python scripts/run_eval.py --ids E-0001,E-0086
python scripts/run_eval.py --difficulty hard
```

Runner 启动前自动执行 **Gold Hash Gate**（100/100 重算）与 **Leakage Gate**（FEWSHOT_V3 ↔ Benchmark 无泄漏），漂移即整体停止；报告输出到 `reports/eval/eval_{run_id}.json/.md`。

### 14.3 最终回归基线（唯一正式引用）

```text
Benchmark = ECO-SQL-Bench v1.1
Prompt    = V1.3（SQLGENERATOR_PROMPT_V1.3，快照 data/prompts/sql_generator_v1.3.txt）
Few-shot  = FEWSHOT_V3（23 例，data/fewshot/ecommerce_examples.json）
DB        = dev-2026-09-14
Model     = Mimo V2.5 Pro（mimo-v2.5-pro）
Clean Baseline EX = 90.0%
```

分项：Exec Rate 99.0% / Pass@1 90.0% / provider failures 0 / timeout 0；延迟 Avg ≈ 10.9s、P50 ≈ 10.5s、P95 ≈ 15.4s；10 条 Bad Case 明细见 `reports/eval/clean_baseline_v1_1/clean_baseline_v1_1.md`。

> 历史实验（Baseline 72%、E1 88%、E2 91%、E4~E7、Stability 等）因涉及 Few-shot 泄漏、Gold 缺陷与旧口径，**仅作项目历程背景，不得作为最终指标引用**。

## 15. 测试

**必须从项目根目录运行**。部分评测相关测试依赖项目根目录下 `data/` 的相对路径。

```bash
python -m pytest backend/tests
```

结果：**967 passed / 1 skipped**（2026-09-25 Task41 文档阶段复测；含 Task37 认证 / 历史测试与 Task39 G7 回归）。历史阶段数字（Task 23：367 passed）保留于 [docs/TEST_REPORT.md](docs/TEST_REPORT.md)，标注 Historical。

测试分类与覆盖详见 [docs/TEST_REPORT.md](docs/TEST_REPORT.md)。

## 16. E3 实验

**E3 = Gold-independent Fan-out 风险检测 + 条件触发 Hint（proof of concept / mechanism validation，已 FROZEN）**。

冻结事实（源自 `reports/eval/E3_FINAL_FREEZE.md` 与 Task 21 对照实验）：

- **E-0086 fan-out 放大约 4.14×**：预测 SQL 单 JOIN 直接 `SUM(o.total_amount)`，累计消费额 `369854.65 → 89397.46`（DB 直连验证）；
- **Detector 命中**：仅输入 Pred SQL（不读 Gold），正确识别 `orders × order_items` 粒度风险；
- **Hint 单例修复**：alarm → 注入 FANOUT_RECHECK_HINT → 1 次 regeneration → E-0086 由 EX✗ 变 EX✓；
- **Task 21 OFF / ON**：`OFF 90% / ON 93%` 是**观测差异**，其中**只有 E-0086 的 +1pt 有直接 Hint 归因证据**（E-0099 / E-0100 未注入 Hint，改善来自独立样本随机性）；`alarm n=1`；
- 结论边界：E3 属于机制验证，**不得表述为“Hint 提升 EX 3 个百分点”**。

| Task | 目录 |
|---|---|
| 17 | `reports/eval/task17_e3_fanout_validator/` |
| 18 | `reports/eval/task18_e3_detector_correlation/` |
| 19 | `reports/eval/task19_e3_fanout_audit/` |
| 20 | `reports/eval/task20_e3_hint_intervention/` |
| 21 | `reports/eval/task21_e3_hint_intervention/` |

## 17. 已知限制

**当前未实现（范围边界，如实声明）**：

- **Multi-turn**（多轮上下文 / 追问）：PRD 阶段 2 / Out-of-Scope；当前为单轮 Agent；
- 结论生成、完整图表规格生成（前端 ECharts 映射为规则 Map）：未实现，仅占位；
- 前端 `datasets / settings` 为占位页（`history` 已实现：登录后可查看与删除本人查询历史）。

**认证与查询历史：已知限制（Task37 验收时明确接受，如实声明）**：

> **后端不可用 ≠ 未登录**（第十阶段 P0-1）：`/api/auth/me` 的失败按类型分派 ——
> `401/403` → 未登录（清理会话）；**网络失败 → 后端不可用**（保留会话 + 显示重试）；
> `5xx` → 后端异常。后端挂掉时不再把用户丢到登录页，也不回退任何本地假数据。

- 登录无限流 / 验证码；
- 登录失败响应统一文案，但未做恒时模糊（存在理论上的时序侧信道）；
- 过期会话无后台清理，仅登录态校验时惰性失效；
- 无 refresh token（会话 TTL 默认 7 天，过期需重新登录）；
- access_token 存于浏览器 localStorage，存在 XSS 暴露面（已配套统一 401 清理会话）。

**E3 当前限制（冻结）**：

- 只检测 `orders × order_items` 粒度风险；
- 子查询剪枝存在已知问题（未生效）；
- 未限定列名存在漏报盲区；
- Hint 属 proof of concept，`alarm n=1`，不支持整体 EX 稳定提升结论。

**技术选型差异**：SQLAlchemy / Tailwind / Ant Design 未使用（见 §4）。

## 18. 项目文档索引

```text
docs/                                # 项目文档（30 份）
│
├── 【产品与设计】
│   ├── PRD.md                       # 产品需求文档（基线）
│   ├── UI-UX.md                     # UI/UX 设计规范（5 导航 / 深色主题）
│   ├── database-schema.md           # 数据库 Schema 与口径说明
│   ├── architecture-options.md      # 架构选型对比（备选方案与取舍）
│   └── tech-research.md             # 技术调研（Text2SQL 方案调研）
│
├── 【后端实现】
│   ├── backend-architecture.md      # 后端架构
│   ├── langgraph-agent.md           # Agent 图设计（有界状态图）
│   ├── schema-linking.md            # Schema Linking 设计
│   ├── fewshot-retrieval.md         # Few-shot 检索设计
│   ├── sql-generator.md             # SQL 生成设计
│   ├── sql-executor.md              # SQL 执行器设计（只读双保险）
│   ├── sql-repair.md                # SQL 修复设计（≤1 次）
│   ├── agent-trace.md               # Agent Trace 记录规范
│   └── llm-integration.md           # LLM 集成（Mimo Provider）
│
├── 【接口与运维】
│   ├── API.md                       # API 参考（逐端点说明；端点总数见 API_ENDPOINTS.md）
│   ├── DEPLOYMENT.md                # 部署指南（安装 / 配置 / 应用库初始化 / 启动）
│   └── OPERATIONS.md                # 运行维护手册（巡检 / 日志 / 常见问题）
│
├── 【评测】
│   ├── evaluation-plan.md           # 评测计划（冻结基线）
│   ├── evaluation-matrix.md         # 评测矩阵
│   ├── evaluation-dataset-spec.md   # 评测数据集规范
│   ├── evaluation-batch-1-review.md # 批次 1 人工复核记录
│   ├── evaluation-batch-2-review.md # 批次 2 人工复核记录
│   ├── evaluation-batch-3-review.md # 批次 3 人工复核记录
│   └── evaluation-batch-4-review.md # 批次 4 人工复核记录（含 v1.0→v1.1 卫生修订）
│
└── 【工程与协作】
    ├── project-understanding.md     # 项目理解（交接期梳理）
    ├── development-baseline.md      # 开发基线
    ├── project-parameters.md        # 项目说明（参数文档：运行参数 / 环境变量 / 未实现清单）
    ├── TEST_REPORT.md               # 测试报告（Latest Verification：967 passed / 1 skipped；历史阶段数字保留）
    ├── AI_COLLABORATION.md          # AI 协作过程记录
    └── phase4-task10-acceptance.md  # 阶段 4 任务 10 验收记录

reports/                             # 交付与实验产出
│
├── 【答辩材料】
│   ├── 基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx   # ★ 唯一正式答辩 PPT（16 页）
│   ├── PPT_CONTENT.md               # PPT 全部可见文字记录（与 PPTX 逐页一致）
│   ├── DEMO_SCRIPT.md               # 现场 Demo 脚本（4 条真实验证问题）
│   ├── DEFENSE_QA.md                # 答辩 Q&A 预案
│   ├── DEFENSE_CHECKLIST.md         # 答辩检查清单
│   └── ppt_assets/                  # PPT 用真实运行截图（5 张）
│
├── 【最终交付报告】
│   ├── FINAL_ACCEPTANCE_REPORT.md   # Task 23 最终技术验收报告
│   ├── FINAL_EXPERIMENT_MATRIX.md   # 最终实验矩阵（唯一正式引用 Clean Baseline v1.1）
│   ├── FINAL_BAD_CASE_CATALOG.md    # 最终 Bad Case 目录
│   ├── FINAL_REQUIREMENTS_CHECKLIST.md  # 需求核对清单
│   ├── FINAL_DELIVERY_GAP_CHECK.md  # 交付缺口核查
│   ├── task28_final_delivery.md     # Task 28 最终交付报告（含 §9 Closeout）
│   ├── task27_defense_materials_completion.md  # Task 27 答辩材料完成记录
│   ├── task26_ppt_completion.md     # Task 26 PPT 完成记录（含 Task 28 勘误）
│   ├── task24_documentation_completion.md      # Task 24 文档补全记录
│   └── WORKBUDDY_HANDOVER_REPORT.md # 第二开发 Agent 交接审计报告（含 §15.5 闭环状态）
│
├── eval/                            # 评测数据与冻结实验结果
│   ├── E3_FINAL_FREEZE.md           # E3 最终冻结摘要
│   ├── bad_case_analysis_v1.md      # Bad Case 分析 v1
│   ├── bad_case_analysis_v2.md      # Bad Case 分析 v2
│   ├── clean_baseline_v1_1/         # ★ Clean Baseline v1.1（90.0% EX，唯一正式基线）
│   ├── baseline_v1/                 # 历史基线
│   ├── e1_semantics_v1/ ~ e7_case_boundary/   # 历史专项实验 E1~E7
│   ├── stability_v1/                # 稳定性复测
│   ├── task16~task22/               # E3 五阶段实验与冻结证据
│   └── eval_*.json / eval_*.md      # 各次评测原始产物
│
├── task26_ppt/                      # PPT 源工程（HTML deck + goal.json + 主题运行时）
│   ├── goal.json                    # ★ deck 权威数据源
│   ├── ppt/index.html               # HTML 演示源（可浏览器直接翻页）
│   └── ppt/assets/                  # 主题运行时与素材
│
└── _archive_pptx/                   # 归档的旧版 PPTX（.superseded-20260917，非最终版）
```

> **索引完整性**：本节已覆盖 `docs/` 全部 30 份文档与 `reports/` 全部顶层交付文档
> （2026-09-17 Task 28 Closeout 补齐）。
> 新增文档请同步更新本节，避免索引与磁盘不一致。

---

> 文档与指标均基于仓库真实实现与冻结实验数据（2026-09-16）。E3 已 FROZEN：本仓库文档阶段不修改 E3 / Detector / Hint / Benchmark / Gold / Prompt / Few-shot / DB。