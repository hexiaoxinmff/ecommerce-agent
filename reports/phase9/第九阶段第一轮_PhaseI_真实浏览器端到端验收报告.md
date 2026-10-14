# 第九阶段 · 第一轮 · Phase I：真实浏览器端到端验收报告

> 范围：任务书 §十八 的 **Phase I**（在 Phase A–H 之后）。
> 目标命题：**「用户真的能通过界面走完整条真实链路」** ——
> `真实 UI 登录 → 真实 UI 切页 → 真实 UI 提问 → 真实 LLM → 真实 SQL → 真实 SQLite → 真实结果上屏 → 真实落库`。
> 时间：2026-09-28 18:07–18:24（GMT+8）。
> 判定：**PASS**（浏览器端到端 **25/25**；活体基线 **40/40**；出口可达性 **EGRESS_OK**）。
> ⚠️ 本报告同时如实记录**检查器自身的三次假通过** —— 其中两次会把「工具没在等」伪装成「系统坏了」，
> 一次会把「还在登录页」伪装成「已经在分析页」。

---

## 一、结论速览

| 证据层 | 脚本 | 结果 |
|---|---|---|
| ① LLM 出口可达性（**0 API 配额**） | `phaseI_reachability.py` | **`EGRESS_OK`**；3 臂 × 4 主机全部 TLS 握手成功；`real_api_calls = 0` |
| ② 活体基线（Python 直连后端） | `verify_live_baseline.py` | **40/40 PASS**（含独立重执行 + 落库 + KPI 全量重算） |
| ③ 真实浏览器端到端 | `dom_live_baseline.mjs` | **25/25 PASS** |
| ④ 浏览器网络层旁证 | `dom_net_diag.mjs` | `POST /api/agent/analyze` → **HTTP 200 / 8.9 s**，`remote=127.0.0.1:8001`，无代理头 |
| ⑤ 导航层旁证（**0 LLM 成本**） | `dom_nav_diag.mjs` | 全程 `frameNavigated(top) = 1`（无整页重载）、`exceptionThrown = 0` |

**关键结论：Phase A 记录的 LLM 出口阻塞已经不存在了。**
Phase A（10:40）实测 `dashscope.aliyuncs.com` 4 个 IP × 重复 5 次 = **9/9 TLS 超时**；
本轮（18:07）同一域名 **3 臂全部 TLSv1.3 握手成功**（direct 1.20 s / HTTP 代理 1.97 s / SOCKS5 1.37 s）。
⇒ **用户不需要再切 Clash 全局香港**，Phase A 的复测项实际已通过。

---

## 二、② 活体基线：40/40

`verify_live_baseline.py`（Python 直连 `http://127.0.0.1:8001`，业务库只读挂载）四层验证：

1. **SQL 真实性 + 只读性** —— 正则 `WRITE_KEYWORDS` 拦截任何写操作关键字；
2. **独立重执行** —— 把接口返回的 SQL 拿到 `file:{ecommerce.db}?mode=ro` + `PRAGMA query_only=ON`
   上**重新跑一遍**，逐值比对（**不是**读接口自己的返回）；
3. **落库** —— `GET /api/history` 能看到本次记录且 `success=1`；
4. **KPI 全量重算** —— `GET /api/insights/overview` 的每个 KPI 与 SQLite 直查值对账。

| 问题 | HTTP | SQL | 行数 | 结果 | 耗时 | 独立重执行 |
|---|---|---|---|---|---|---|
| 平台注册用户有多少？ | 200 | `SELECT COUNT(*) AS total_registered_users FROM users` | 1 | `2000` | 11047.29 ms | 完全一致 |
| 销售额最高的 5 个商品是什么？ | 200 | `SELECT p.name AS product_name, ROUND(SUM(oi.subtotal),2) … ORDER BY total_sales DESC LIMIT 5` | 5 | Top1 `恒源祥笔记本电脑Plus 944485.34` | 6587.15 ms | 完全一致 |

第二次运行复现出**完全相同的值** ⇒ 可重复。

---

## 三、③ 真实浏览器端到端：25/25

`dom_live_baseline.mjs`：**不注入 localStorage**，在真实 UI 上填表单、点登录、点侧边栏、敲问题、点「开始分析」。

本次运行身份：`run_id = 017146`，用户 `phaseI-live-017146`（**每次运行新建用户**），
问题 `平台注册用户有多少？`。

| # | 断言 | 结果 |
|---|---|---|
| 1 | 渲染进程存活（`1+1===2`） | PASS |
| 2 | 匿名访问 → 登录页 | PASS |
| 3 | 匿名态无业务数据泄漏 | PASS |
| 4 | 登录表单已提交 | PASS |
| 5 | UI 登录成功（登录表单消失 **且** 首页 Hero 出现） | PASS |
| 6 | 点击侧边栏「智能分析」 | PASS |
| 7 | 分析页真的挂载（`.analysis-input` 出现 **且** Hero 消失） | PASS |
| 8 | 当前激活页 == 智能分析（`nav-item--active` 自证） | PASS |
| 9 | 分析页不含首页 Hero | PASS |
| 10 | 已提交问题（作用域 `.analysis-input`） | PASS |
| 11 | 真实查询结果上屏（`.result-note` 含「以上为真实 SQLite 查询结果」） | PASS |
| 12 | 结果区含真实值 `2,000`（作用域 `.result-card`） | PASS |
| 13 | 结果区渲染真实结果表（`.result-table__grid`） | PASS |
| 14 | 页面出现生成的 SQL（`.sql-panel__code` / `.wf-sql`） | PASS |
| 15 | 分析页未进入错误态（无 `.result-error`） | PASS |
| 16–21 | 六条失真/假数据文案 0 命中（`Demo 模式` / `静态演示数据` / `7,662,921` / `1,284` / `352.6` / `星耀`） | PASS ×6 |
| 22 | 「历史记录」页出现本次提问（全新用户 ⇒ 只可能来自本次） | PASS |
| 23 | 当前激活页 == 历史记录 | PASS |
| 24 | 只发生 1 次整页加载（`frameNavigated(top)=1`，无 reload） | PASS |
| 25 | 无未捕获异常（`exceptionThrown=0`） | PASS |

浏览器侧真实产物（结果卡原文）：

```
分析结果 真实执行成功
total_registered_users  2000
返回行数 1   SQL 执行 1 次   自动修复 0 次   Agent 总耗时 11052 ms
以上为真实 SQLite 查询结果
```

生成的 SQL：`SELECT COUNT(*) AS total_registered_users FROM users`

---

## 四、三方对账：SQLite = API = UI（本轮实测）

| 层 | 取值 | 来源 |
|---|---|---|
| ① SQLite | `query_history` 行 `id=18`，`total_time_ms = 11051.84`，`success = 1`，`row_count = 1`，`sql = SELECT COUNT(*) AS total_registered_users FROM users` | `F:/p9_audit/appdb/app.db` 直查 |
| ② API | `POST /api/agent/analyze` → `execution_result.rows = [[2000]]` | `phaseI_live_baseline.json` |
| ③ UI（DOM） | 结果卡显示 `2000` / `返回行数 1` / `Agent 总耗时 11052 ms` | `dom_live_baseline.html`（57,244 字节） |

`11051.84`（DB，毫秒两位小数）与 `11052`（UI，`toFixed(0)`）为**同一数值的不同呈现精度**，
非两套数据源。三层的 SQL 文本、行数、结果值**逐项一致**。

---

## 五、④ 网络层旁证：浏览器发出的请求长什么样

`dom_net_diag.mjs` 打开 CDP `Network` 域，抓浏览器自己的请求（一次 LLM 调用）：

```
t=1969ms → OPTIONS http://127.0.0.1:8001/api/agent/analyze
           Access-Control-Request-Headers: authorization,content-type
           Access-Control-Request-Method: POST
t=1969ms ← HTTP 200   （CORS 预检通过）
t=1974ms → POST http://127.0.0.1:8001/api/agent/analyze
           Authorization: Bearer <token>      Content-Type: application/json
           body: {"question":"平台注册用户有多少？"}
t=8891ms ← HTTP 200   remote=127.0.0.1:8001   proto=http/1.1
t=8891ms ✔ loadingFinished 2340B
```

UI 状态时间线：`分析中`（t=1985…8041ms）→ **`真实执行成功`**（t=9050ms，`.result-note` 出现真实标记）。

三条可用于排除环境嫌疑的事实：

- `remoteIPAddress = 127.0.0.1`、`protocol = http/1.1` ⇒ 浏览器**直连本地后端**，没有被代理接管；
- `requestWillBeSentExtraInfo` 的头键里**没有任何 `Proxy-*` / `Via` / `X-Forwarded-*`**；
- 对照：Python 直连同一接口耗时 **5.8 s**，浏览器 **8.9 s**，同量级 ⇒ 差异只是客户端开销，不是链路故障。

> 旁证：页面加载初期可见若干 `net::ERR_ABORTED canceled=true`（t=1118ms）。
> 这是 **React StrictMode 开发态双挂载**的正常现象（effect 挂载→清理→再挂载，第一次的
> `fetchOverview` / `listHistory` / `fetchHealth` 被 `AbortController` 主动取消），
> 不是缺陷；生产构建不双挂载。

---

## 六、检查器自身的三次假通过（如实记录）

> 这一节比上面的 25 个 PASS 更重要。三次都是**测量工具坏了**，且前两次的失败表现
> 完全指向被测系统。若不做旁证，很容易得出「Phase I 被阻塞」的错误结论。

### 假通过 #1：选择器歧义（Phase E/F 遗留，本轮修）

`Hero.tsx:43` 与 `AnalysisPage.tsx:250` **共用同一个 `aria-label="输入自然语言查询问题"`**。
旧写法用全文档 `querySelectorAll("button")` 找文字导航，无法自证「页面真的切过去了」，
于是「输入框就绪」这条断言在**首页**上也成立。
⇒ 改为：侧边栏内点击 + `nav-item--active` 自证 + `analysisPageMounted()`（`.analysis-input` 出现 **且** `.hero` 消失）。

### 假通过 #2：登录等待条件**恒真**（本轮修，最严重）

旧写法 `waitFor(document.querySelector("aside.sidebar") !== null)`。
但 `App.tsx` 的 `AppShell` **永远**返回 `<MainLayout>`，而 `MainLayout` 无条件渲染 `<Sidebar />`
—— 连未登录时渲染的 `LoginPage` 也带着侧边栏。**该条件恒为真**，脚本在登录请求还没返回时就往下走了。

`dom_nav_diag.mjs`（**0 LLM 成本**）实测时间线：

```
t= 785ms  nav="智能分析"  hero=false  inputs=2  bodyLen=171   ← 其实是登录页
t= 999ms  nav="智能分析"  hero=false  inputs=2  bodyLen=171   ← 还是登录页
t=1202ms  nav="首页"      hero=true   inputs=1  bodyLen=663   ← 登录返回后被弹回首页
```

根因：`LoginPage.handleSubmit` 在 `await login()` 成功后调用 `onSuccess?.()`（`LoginPage.tsx:43-47`），
而当时挂载的是**首页那条** `ProtectedRoute` 传入的 `onSuccess = () => setPage("home")`，
于是把刚点出的「智能分析」**覆盖回「首页」**。分析页从未挂载 ⇒ 找不到输入框 ⇒ `missing-input`。
而「分析页不含 Hero」那条断言，是在**登录页**上「通过」的（登录页当然没有 Hero）。

⇒ 修法：登录等待改为**只有已认证才成立**的条件 ——
`input[type=password]` 消失 **且** `.hero` 出现；并在切页后等待 `analysisPageMounted()`。

### 假通过 #3：轮询参数错位 ⇒ 轮询体执行 **0 次**（本轮修）

`waitFor` 签名被改成 `(predicate, tries, gap)`，但两个调用点仍按旧签名多传了一个 `label`：

```js
// 错：tries 收到字符串 "real result"
await waitFor(() => cdp.eval(...), "real result", 240, 250);
```

`for (let i = 0; i < "real result"; i += 1)` → `0 < NaN` 恒为 false ⇒ **一次都不轮询，立刻返回 `false`**。
表现：「真实查询结果上屏」与「历史记录出现本次提问」双双 FAIL，
看起来像后端坏了 —— 实际是检查器**压根没等**。

> 这是铁律 14「检查器崩溃会被读成全绿」的**镜像版本**：
> 检查器**静默失效**会被读成「被测对象全红」。

⇒ 修法：`waitFor` 参数改为**显式断言**，非法即抛（不再静默返回 `false`）：

```js
if (!Number.isFinite(tries) || tries <= 0 || !Number.isFinite(gap) || gap <= 0) {
  throw new Error(`waitFor 参数非法：tries=… gap=…`);
}
```

### 定位方法论（本轮实际用的顺序）

1. 先跑 **`dom_nav_diag.mjs`（0 LLM 成本）** —— 证明「登录 → 切页」链路本身没问题，
   并抓到「登录成功回调把页面弹回首页」这条时间线；
2. 再用 **`dom_net_diag.mjs`（1 次 LLM 调用）** —— 证明浏览器发出的
   `POST /api/agent/analyze` **8.9 s 拿到 200**、UI 出现「真实执行成功」；
3. 同时用 **Python 直连** 证明后端本身 5.8 s 返回 200，且 `app.db` 里**没有新增历史行**
   ⇒ 分歧既不在后端也不在链路；
4. 于是嫌疑收敛到**检查器自己**，复查调用点即发现 `waitFor` 参数错位。

> 教训：**「三个旁证都指向同一结论」比「把主脚本改到绿」可靠得多。**

---

## 七、本轮交付物清单

| 文件 | 说明 |
|---|---|
| `F:/p9_audit/phaseI_reachability.py` / `.json` | 出口可达性探针（纯 TCP+TLS，0 API 配额，带对照域名） |
| `F:/p9_audit/verify_live_baseline.py` / `phaseI_live_baseline.json` | 活体基线 40/40（含独立重执行） |
| `F:/p9_audit/dom_live_baseline.mjs` / `.html` / `.analysis.html` / `.json` | 真实浏览器端到端 25/25 |
| `F:/p9_audit/dom_nav_diag.mjs` / `.html` / `.json` | 导航层诊断（0 LLM 成本，抓到假通过 #2） |
| `F:/p9_audit/dom_net_diag.mjs` / `.json` | 网络层诊断（抓到真实 200 + 无代理头） |

> 全部**验收产物**位于 `F:/p9_audit/`（**仓库外**）⇒ 本次 Phase I 的测量过程**未改动仓库任何文件**。
> 仓库内只有两处改动，且逐条可归属：
> - `docs/TEST_REPORT.md`（**M**）—— 追加 §0.2 与 Phase H/I 行（该文件在本段之前已是 M，故 M 计数不变）；
> - `reports/phase9/第九阶段第一轮_PhaseI_真实浏览器端到端验收报告.md`（**新增 ??**）—— 本报告。
>
> `git status --porcelain -uall`：开工 **2001** → 收工 **2002**，delta = `??` **+1**，已 100% 归属，**无未解释残差**。
> 分类：`?? 1960` / `M 41` / `D 1`。
>
> ⚠️ **本结论只对 2026-09-28 18:23 那一刻的工作树成立。** 该工作树此后被改动，
> 本节数字随之失效 —— 见文末 **§十 重测**（20:47，对**当前**工作树 + **正式** 8000/5173 重新取证）。

---

## 八、遗留 / 不在本轮范围

| 项 | 状态 |
|---|---|
| Phase A 网络复测 | **已消解** —— 本轮 `EGRESS_OK`，用户无需再切 Clash |
| 用户本机 **8000 端口后端未启动** | 需用户自行重启；首页与 `/api/insights/overview` 依赖它（首页现已**要求登录**） |
| 本轮临时服务 | 后端 **8001**（`APP_DB_PATH=F:/p9_audit/appdb/app.db`）、Vite **5174**（CORS 仅放行 `http://localhost:5174`）；用户原有 8000/5173 **未被触碰** |
| 前端 dev server 建议重启 | 仍在运行的 5174 实例启动于 Phase G 之前 |
| `AppDbNotFoundError` 逃逸为 **500**（应为 401） | 既有问题，本轮未修 |
| `backend/app/api/routes/llm.py:55-66` 硬编码 "Mimo" 文案 | 既有问题，本轮未修 |
| 6 条 `.env` 口径导致的 pytest 失败 | 既有状态，改 `.env` 不在授权范围 |
| `run_eval.py:215` 模型标签失真 | 既有问题，本轮未修 |

---

## 九、复现命令

```bash
CHROME="C:/Users/29593/AppData/Local/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-win64/chrome-headless-shell.exe"
NODE="C:/Users/29593/.workbuddy-ai/binaries/node/versions/22.22.2-2/node.exe"
PY="C:/Users/29593/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe"

# ① 出口可达性（0 API 配额）
"$PY" F:/p9_audit/phaseI_reachability.py

# ② 活体基线（真实 LLM，2 次提问）
"$PY" F:/p9_audit/verify_live_baseline.py

# ③ 真实浏览器端到端（真实 LLM，1 次提问）
"$NODE" F:/p9_audit/dom_live_baseline.mjs "$CHROME" "http://127.0.0.1:8001" "http://localhost:5174" "F:/p9_audit/dom_live_baseline.html"

# ④ 诊断脚本（dom_nav_diag 零成本；dom_net_diag 1 次调用）
"$NODE" F:/p9_audit/dom_nav_diag.mjs "$CHROME" "http://127.0.0.1:8001" "http://localhost:5174" "F:/p9_audit/dom_nav_diag"
"$NODE" F:/p9_audit/dom_net_diag.mjs "$CHROME" "http://127.0.0.1:8001" "http://localhost:5174" "F:/p9_audit/dom_net_diag"
```

---

## 十、重测（2026-09-28 20:47）：当前工作树已重新取证

### 为什么要重测

本报告 §一–§九 的 25/25，是对 **18:23 那一刻的工作树**取的证。
之后该工作树被**另一条工作线**继续改动（`frontend/src` 在 19:34–20:22 有 9 个文件被写入），
且改动点**恰好落在本验收所依赖的那条链路上**：

| 文件 | mtime | 为何与本次验收相关 |
|---|---|---|
| `frontend/src/pages/LoginPage.tsx` | 19:35:45 | 本报告假通过 #2 的根因就在这个文件的 `onSuccess` |
| `frontend/src/pages/AnalysisPage.tsx` | 19:36:08 | 提问框 / 结果区 / `.result-note` 都在这里 |
| `frontend/src/api/http.ts` | 19:53:09 | 统一请求层：Bearer 注入、401 处理 |
| `frontend/src/auth/AuthContext.tsx` | 19:41:30 | 登录态与路由守卫 |
| `frontend/src/api/insights.ts` | 19:36:22 | 首页取数 |
| `frontend/src/components/BackendUnavailable.tsx` | 19:34:57 | **新增组件**（后端不可用态） |
| `frontend/src/auth/AuthContext.test.tsx` | 19:36:49 | — |
| `frontend/src/api/http.test.ts` | 19:37:05 | — |
| `frontend/src/utils/connection.test.ts` | 20:22:49 | — |

> ⚠️ 这正是铁律 2 的现场：`git status --porcelain` 的**行数**从 2002 涨到 **2018**，
> 但涨的几乎全是**新增未跟踪文件**；上面 6 个**受跟踪文件**的"内容又变了"这件事，
> porcelain **完全看不见**（它们本来就在 `M` 桶里）。⇒ 「行数对得上」不等于「内容没变」。

### 重测结果：**25/25 PASS**

- 对象：**当前工作树**（含上述 19:34–20:22 的全部改动）；
- 服务：**正式** 8000 / 5173（不再是本轮的临时 8001/5174）；
- 脚本：同一个 `dom_live_baseline.mjs`（已修掉三个假通过），产物另存
  `dom_live_baseline_recheck.html` / `.json`（**不覆盖** 18:23 的原始证据）；
- 身份：`run_id = 646619`，用户 `phaseI-live-646619`。

结果卡原文：

```
分析结果 真实执行成功
total_registered_users  2000
返回行数 1   SQL 执行 1 次   自动修复 0 次   Agent 总耗时 7781 ms
以上为真实 SQLite 查询结果
```

生成的 SQL 与上一轮一致：`SELECT COUNT(*) AS total_registered_users FROM users`。

### 三方对账（**正式** `db/app.db`）

| 层 | 取值 |
|---|---|
| ① SQLite（正式库） | `query_history` 行 `id=63`，`total_time_ms = 7781.05`，`success = 1`，`row_count = 1` |
| ② API | `execution_result.rows = [[2000]]` |
| ③ UI（DOM） | `2000` / `返回行数 1` / `Agent 总耗时 7781 ms` |

`7781.05`（DB）与 `7781`（UI `toFixed(0)`）为同一数值的不同精度呈现。

### 边界复核（重测后）

| 项 | 结果 |
|---|---|
| `db/ecommerce.db`（业务库，只读） | sha256 前缀 **`65e5d8b2`** —— 与 Phase G 记录一致，**只读边界完好** |
| `_delivery_build/`（v1.0.0 冻结交付包） | 18:23 之后 **0 个文件被写入** |
| `db/app.db`（应用库） | 本次重测**写入 1 个测试用户 + 1 条历史行**（`phaseI-live-646619`）⇒ 见下方披露 |
| 假数据/失真文案 | 六条哨兵 **0 命中** |
| 整页重载 / 未捕获异常 | `frameNavigated(top)=1` / `exceptionThrown=0` |

> ⚠️ **副作用披露**：本轮重测指向**正式** 8000，因此 `db/app.db` 新增
> 1 个测试用户（`phaseI-live-646619`）与 1 条历史行（`id=63`）。
> 该库是**本地开发库**且已被 `.gitignore` 排除；同目录下已有其它验收留下的同类测试账号。
> 若需清理，按用户名删除该用户及其历史行即可（**不影响** `db/ecommerce.db` 业务库）。

### 结论

**当前工作树的真实链路同样是通的**：`真实 UI 登录 → 切页 → 提问 → 真实 LLM → 真实 SQL → 真实 SQLite → 结果上屏 → 历史落库`，
25/25 全绿，三方逐值一致。本报告 §一–§九 的 18:23 快照与本节 20:47 的快照**互不覆盖**，可分别引用。
