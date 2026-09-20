# 部署指南（Deployment Guide）

> 适用范围：**课程项目 / 本地 Demo**（非生产级部署；本仓库不提供 Docker / 反向代理 / 多进程编排）。
> 所有路径、命令均来自仓库真实实现（核对于 Task 24，2026-09-16）。

---

## 1. 环境要求

| 依赖 | 要求 |
|---|---|
| Python | 3.12+（开发实测 3.12.10） |
| Node.js | 18+（Vite 8） |
| npm | 与 Node 配套 |
| 网络 | 可访问 Mimo API（`https://api.xiaomimimo.com/v1`） |

## 2. 后端安装 / 启动

### 2.1 安装依赖

```bash
# 项目根目录
python -m venv .venv

# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2.2 配置 .env

```bash
cp .env.example .env
# 编辑 .env，填写 MIMO_API_KEY（真实 Key 严禁提交 Git）
```

### 2.3 生成数据库（可选，仓库已带 db/ecommerce.db）

```bash
python scripts/init_db.py
```

### 2.4 启动 Backend

```bash
cd backend
uvicorn app.main:app --reload
```

- 默认监听 http://127.0.0.1:8000
- 交互式 API 文档：http://127.0.0.1:8000/docs

## 3. 前端安装 / 启动

```bash
cd frontend
npm install
npm run dev
```

- 默认 http://localhost:5173
- 其他可执行脚本（见 `frontend/package.json`）：

```bash
npm run build     # 生产构建：tsc -b && vite build
npm run lint      # oxlint 代码检查
npm run preview   # 预览构建产物
```

## 4. Environment Variables

### 4.1 后端（加载自项目根 `.env` / 系统环境变量，见 `backend/app/core/config.py`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `mimo` | Provider 名称（本阶段仅 mimo 有实现） |
| `MIMO_API_KEY` | （无） | Mimo API Key；**只从环境变量读取，严禁写入代码 / Git；`.env` 已被 .gitignore 排除** |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | OpenAI-compatible 端点 |
| `MIMO_MODEL` | `mimo-v2.5-pro` | 模型名 |
| `MIMO_TIMEOUT` | `30` | LLM 超时（秒，正数） |
| `ECOMMERCE_DB_PATH` | `db/ecommerce.db`（项目根相对） | 覆盖数据库路径 |
| `CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔的允许来源 |
| `FEWSHOT_DATASET_PATH` | `data/fewshot/ecommerce_examples.json` | 覆盖 Few-shot 数据集路径 |

> **安全提醒：任何文档 / 示例中均不出现真实 API Key。**

### 4.2 前端（加载自 `frontend/.env`，见 `frontend/.env.example`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | 后端 Agent API 地址（集中管理，业务组件不硬编码） |

## 5. 数据库

| 项 | 值 |
|---|---|
| 路径 | `db/ecommerce.db` |
| 版本 | dev-2026-09-14 / schema 1.0 / seed 20260914 |
| 表 | users(2000) / categories(30) / products(500) / orders(10000) / order_items(30457) |
| 只读执行机制 | 连接统一 `file:…db?mode=ro`（文件级只读）+ `PRAGMA query_only=ON`（会话级只读） |
| 结果保护 | 单次查询最多返回 500 行（`MAX_RESULT_ROWS`），超出标记 `truncated=true` |
| 重建 | `python scripts/init_db.py`（固定 seed，可完全复现） |

> 数据库文件由 `.gitignore` 排除（`db/*.db`），提交项目时不会携带二进制。

## 6. 启动后验证

```bash
# 1) 健康检查（含 SQLite 只读探活）
curl http://127.0.0.1:8000/api/health

# 2) 数据库信息
curl http://127.0.0.1:8000/api/system/database

# 3) LLM 链路（需要已配置 MIMO_API_KEY）
curl -X POST http://127.0.0.1:8000/api/llm/test \
  -H "Content-Type: application/json" \
  -d '{"prompt": "你好"}'

# 4) 完整 Agent 链路
curl -X POST http://127.0.0.1:8000/api/agent/analyze \
  -H "Content-Type: application/json" \
  -d '{"question": "2025年每月销售额是多少？"}'
```

浏览器访问 http://localhost:5173 完成 Demo 演示。

## 7. 评测环境（可选）

```bash
python scripts/validate_eval_dataset.py   # 数据集结构 + 真实库只读执行校验
python scripts/run_eval.py                # 完整 100 条评测（串行，耗时较长）
```

## 8. 定位声明

本项目的定位为 **课程项目 / 本地 Demo**：

- 单进程 uvicorn + Vite dev server，未配置生产级部署；
- SQLite 单文件、无连接池、无分布式；
- LLM 依赖外部 Mimo 按量付费 API；
- 无登录 / 用户管理 / 多轮（PRD 阶段 2 / Out-of-Scope）。

**不是**已完成的“生产级部署”，文档不包装为生产系统。

---

*核对来源：`.env.example`、`backend/app/core/config.py`、`frontend/.env.example`、`backend/app/db/sqlite.py`、`backend/app/sqlexec/executor.py`。*