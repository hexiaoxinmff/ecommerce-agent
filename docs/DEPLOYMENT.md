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

### 2.3 生成业务数据库（可选，仓库已带 db/ecommerce.db）

```bash
python scripts/init_db.py
```

### 2.4 初始化应用库（认证 / 查询历史必需）

```bash
python scripts/init_auth_db.py
```

创建 `db/app.db` 并初始化三张应用表：

| 表 | 用途 |
|---|---|
| `auth_user` | 应用账号（只存 PBKDF2-HMAC-SHA256 口令哈希，绝不明文） |
| `auth_session` | 登录会话（只存 token 的 SHA-256 哈希，含过期时间） |
| `query_history` | 查询历史（按 user_id 隔离，Agent 每次请求后自动写入） |

幂等，可重复执行。应用库与业务库物理隔离（见 §5）。

### 2.5 启动（推荐：一条命令）

项目根目录下：

```bash
python scripts/start_dev.py
```

它把 §2.5 与 §3 的两条命令编排起来，并在启动前做预检：

| 步骤 | 检查内容 |
|---|---|
| 1 | Python 版本 ≥ 3.12 |
| 2 | 后端依赖（fastapi / uvicorn / dotenv / pydantic / langgraph / sqlglot / openai）可导入 |
| 3 | Node / npm 存在 |
| 4 | 前端依赖（`frontend/node_modules`）已安装 |
| 5 | `.env` 存在 |
| 6 | 数据文件 `db/ecommerce.db` + `db/app.db` 存在 |
| 7 | 端口 8000 / 5173 空闲（**IPv4 与 IPv6 都查**） |

全部通过后启动两个服务、轮询 `/api/health`，并输出：

```text
Backend : http://127.0.0.1:8000
Frontend: http://localhost:5173
Health  : OK
```

**常用选项**：`--check-only`（只预检）、`--detach`（后台启动 + 写 `logs/start_dev_pids.json`）、
`--backend-port` / `--frontend-port`（换端口）、`--skip-env-check` / `--skip-data-check`（逃生口）。

**停止**：前台 `Ctrl+C`（脚本会杀掉**整棵进程树**，不留孤儿 vite）；后台 `python scripts/stop_dev.py`。

**失败场景与退出码**（错误文案明确，窗口不会闪退）：

| 退出码 | 场景 | 行为 |
|---:|---|---|
| 2 | Python 版本过低 | 提示所需版本 |
| 3 | 后端依赖缺失 | 给出 `pip install -r requirements.txt` |
| 4 | Node / npm 缺失 | 给出安装指引 |
| 5 | 前端依赖缺失 | 给出 `cd frontend && npm install` |
| 6 | `.env` 缺失 | 给出 `copy .env.example .env` |
| 7 | 端口被占用 | 点名是哪个端口 + 换端口建议（**不静默改端口**） |
| 8 | 数据文件缺失 | 给出 `scripts/init_db.py` / `scripts/init_auth_db.py` |
| 9 | 后端启动失败 | 打印后端进程最后的输出（可归因） |
| 10 | 前端启动失败 | 打印前端进程最后的输出 |

Windows 也可双击 `scripts\start_dev.bat`（等价，且失败时 `pause` 保留窗口）。

### 2.6 启动 Backend（手动）

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
- ⚠️ 手动启动时若 5173 被占用，Vite 会**静默**改用 5174。`start_dev.py` 用 `--strictPort`
  把它变成明确报错，避免"访问 5173 看到别人的服务"。
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
| `LLM_PROVIDER` | `mimo` | Provider 名称：`mimo` \| `bailian`（**推荐运行环境是 `bailian`**） |
| `DASHSCOPE_API_KEY` | （无） | 阿里云百炼 Key。**百炼 Key 的唯一来源**（刻意不提供 `BAILIAN_API_KEY` 别名） |
| `BAILIAN_API_BASE` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 百炼 OpenAI 兼容端点 |
| `BAILIAN_MODEL` | `qwen3.7-flash-2026-07-15` | 百炼模型名 |
| `BAILIAN_PRIMARY_MODEL` | 同 `BAILIAN_MODEL` | 主模型 |
| `BAILIAN_TIMEOUT` | `30` | 百炼超时（秒，正数） |
| `LLM_MODEL_LOCK` | `true` | 单模型锁定；`false` 才启用模型池 fallback |
| `MIMO_API_KEY` | （无） | Mimo API Key；**只从环境变量读取，严禁写入代码 / Git；`.env` 已被 .gitignore 排除** |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | OpenAI-compatible 端点 |
| `MIMO_MODEL` | `mimo-v2.5-pro` | 模型名 |
| `MIMO_TIMEOUT` | `30` | LLM 超时（秒，正数） |
| `ECOMMERCE_DB_PATH` | `db/ecommerce.db`（项目根相对） | 覆盖业务库路径 |
| `APP_DB_PATH` | `db/app.db`（项目根相对） | 覆盖应用库路径（认证用户 / 会话 / 查询历史） |
| `AUTH_SESSION_TTL_SECONDS` | `604800`（7 天） | 登录会话有效期（秒）；过期会话在登录态校验时惰性失效 |
| `CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔的允许来源 |
| `FEWSHOT_DATASET_PATH` | `data/fewshot/ecommerce_examples.json` | 覆盖 Few-shot 数据集路径 |

> **安全提醒：任何文档 / 示例中均不出现真实 API Key。**
> 该约束由 `backend/tests/test_env_example_contract.py` 用**值级正则**扫描守住
> （不是找 `KEY` 这类标记子串 —— 那会把变量名当密钥，必然自指假阳性）。

### 4.2 前端（加载自 `frontend/.env`，见 `frontend/.env.example`）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | 后端 Agent API 地址（集中管理，业务组件不硬编码） |

> ⚠️ Vite 只读取 `frontend/` 下的 `.env*`；根目录的 `.env` 与前端无关。
> Vite 只注入 `VITE_` 前缀变量，且**这些值会被打进前端产物** ⇒ 绝不要把 Key 放这里。
> 改前端端口 / 跨机访问时，必须同步修改后端 `CORS_ORIGINS`（同源策略把
> `localhost` 与 `127.0.0.1` 视为不同 origin）。

## 5. 数据库

两个 SQLite 库物理隔离：

### 5.1 业务库（只读访问）

| 项 | 值 |
|---|---|
| 路径 | `db/ecommerce.db`（可用 `ECOMMERCE_DB_PATH` 覆盖） |
| 版本 | dev-2026-09-14 / schema 1.0 / seed 20260914 |
| 表 | users(2000) / categories(30) / products(500) / orders(10000) / order_items(30457) |
| 只读执行机制 | 连接统一 `file:…db?mode=ro`（文件级只读）+ `PRAGMA query_only=ON`（会话级只读） |
| 结果保护 | 单次查询最多返回 500 行（`MAX_RESULT_ROWS`），超出标记 `truncated=true` |
| 重建 | `python scripts/init_db.py`（固定 seed，可完全复现） |

业务库保持只读访问边界：认证 / 历史功能绝不写入业务库，业务数据不经应用库流转。

### 5.2 应用库（认证 / 历史，可写）

| 项 | 值 |
|---|---|
| 路径 | `db/app.db`（可用 `APP_DB_PATH` 覆盖） |
| 表 | `auth_user` / `auth_session` / `query_history`（无多余表） |
| 凭据存储 | 口令只存 PBKDF2 哈希；会话只存 token 的 SHA-256 哈希，绝不明文 |
| 初始化 | `python scripts/init_auth_db.py`（幂等） |

> 数据库文件由 `.gitignore` 排除（`db/*.db`），提交项目时不会携带二进制。

## 6. 启动后验证

<!-- API-ENDPOINTS:BEGIN (generated by scripts/export_api_endpoints.py — do not edit) -->
**API 端点：18 个**（12 个 router；需鉴权 6 ／ 公开 12）。权威清单见 [`API_ENDPOINTS.md`](API_ENDPOINTS.md)。
<!-- API-ENDPOINTS:END -->

```bash
# 1) 健康检查（含 SQLite 只读探活）
curl http://127.0.0.1:8000/api/health

# 2) 数据库信息
curl http://127.0.0.1:8000/api/system/database

# 3) 注册 + 登录（需已执行 scripts/init_auth_db.py）
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "email": "demo@example.com", "password": "S3cret!pass"}'

curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "password": "S3cret!pass"}'
# → 记录响应中的 access_token

# 4) LLM 链路（需要已配置 MIMO_API_KEY）
curl -X POST http://127.0.0.1:8000/api/llm/test \
  -H "Content-Type: application/json" \
  -d '{"prompt": "你好"}'

# 5) 完整 Agent 链路（需 Bearer 登录；查询会自动写入本人历史）
curl -X POST http://127.0.0.1:8000/api/agent/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"question": "2025年每月销售额是多少？"}'

# 6) 查询历史（本人可见）
curl "http://127.0.0.1:8000/api/history?page=1&page_size=20" \
  -H "Authorization: Bearer <access_token>"

# 7) 首页概览（只读聚合，需 Bearer；第九阶段 Phase C 新增）
curl http://127.0.0.1:8000/api/insights/overview \
  -H "Authorization: Bearer <access_token>"
# → 返回 KPI / Top5 商品 / 数据截止日，全部来自 db/ecommerce.db 实时聚合
```

> ⚠️ `/api/insights/overview` 与 `/api/history` **都必须带 `Authorization: Bearer <token>`**；
> 匿名访问返回统一 `401 {"detail": "Invalid credentials"}` + `WWW-Authenticate: Bearer`。
> 前端首页已纳入 `ProtectedRoute`，未登录只会看到登录页。
>
> ⚠️ **时间字段口径**：`/api/history` 的 `created_at` 是 **UTC 带偏移**的 ISO 串
> （形如 `2026-09-28T09:10:20+00:00`）。前端必须经 `utils/datetime.ts` 做时区换算后展示，
> **不得**用 `slice(0,19)` 直接截断——那会把 UTC 墙上时间当成本地时间显示（差 8 小时且无标记）。

浏览器访问 http://localhost:5173 完成注册 / 登录 / 分析 / 历史全流程 Demo 演示。

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
- 已实现本地注册 / 登录 / 查询历史（Bearer session，非生产级认证——无限流 / 验证码 / refresh token，已知限制见 README §17）；多轮 conversation API 未实现（PRD 阶段 2 / Out-of-Scope）。

**不是**已完成的“生产级部署”，文档不包装为生产系统。

---

*核对来源：`.env.example`、`backend/app/core/config.py`、`frontend/.env.example`、`backend/app/db/sqlite.py`、`backend/app/db/appdb.py`、`backend/app/sqlexec/executor.py`、`scripts/init_auth_db.py`（2026-09-25 Task41 文档一致性修复时更新）。*