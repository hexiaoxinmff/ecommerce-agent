# 第九阶段 · 第一轮（A + B）：Runtime 网络诊断 & 首页静态数据审计

> **性质**：只读审计（READ-ONLY AUDIT）。本轮**未修改任何既有文件**、未改 UI 文案 / API / 数据库 /
> `.env` / 模型 / Prompt / 评测 / `_delivery_build/**`；未删除任何 Demo / Mock 数据。
> **唯一新增产物**：本报告文件本身。
> **审计时刻**：2026-09-28 10:40–11:00 (GMT+8)
> **仓库边界**：开工 `git status --porcelain -uall` = **1978** 行 → 收工 = **1978** 行（`diff` 空，零改动）
> **探针位置**：全部落在**仓库外** `F:\p9_audit\`（含 4 个脚本 + 3 份 JSON 证据 + 1 份 DOM dump）
>
> ⚠️ 本报告是**审计**，不是施工。所有"应该怎么改"只作为下一轮的白名单依据，本轮一行代码都没动。

---

## 0. 现场快照与冻结核验

```
git branch --show-current   → master
git rev-parse HEAD          → 6c5f51c1d25c703cc04d93a3577072552800fa51
git status --porcelain -uall → 1978 行（开工 = 收工，diff 为空）
```

**v1.0.0 冻结包哈希核验（只核验，未修改）：**

```
期望（任务书 §十七）: 3AC09864B3A6EB58661AA56E5C308CDB2644655C6B16A838184CDE719E23A30F
实测 _delivery_build/Text2SQL电商智能数据分析Agent_v1.0.0.zip:
                      3ac09864b3a6eb58661aa56e5c308cdb2644655c6b16a838184cde719e23a30f
判定: ✅ MATCH（FINAL_DELIVERY_LOCKED 未被触碰）
```

**服务现场：**

| 项 | 值 |
|---|---|
| 后端 | `127.0.0.1:8000` LISTENING，PID 21704 |
| 前端 dev server | `[::1]:5173` LISTENING，PID 21224（**仅 IPv6 回环**） |
| Clash | `127.0.0.1:7897` / `127.0.0.1:7899` LISTENING，PID 7256 |
| 沙箱代理 | `HTTP(S)_PROXY=http://127.0.0.1:65207`（WorkBuddy 注入） |
| 默认路由 | **`0.0.0.0/0 → 198.18.0.2` metric 0**（另有一条 `192.168.110.1` metric 35） |
| DNS 服务器 | `198.18.0.2` |

> ⚠️ 最后两行是本轮诊断的**环境前提**：`198.18.0.0/16` 是 Clash TUN + fake-ip 的典型网段。
> 本机**处于 TUN 模式**，因此**不存在真正的"直连"**——`trust_env=False` / `--noproxy '*'` 只能摘掉
> 应用层代理，摘不掉内核路由层的 TUN。下文所有"直连"结论都带这个前提。

---

## 1. Runtime 网络诊断（链路逐级 PASS / FAIL）

诊断目标：`https://dashscope.aliyuncs.com/compatible-mode/v1`，模型 `qwen3.7-flash`。
配置来源（只读确认，未修改）：

| 项 | 实际值 | 出处 |
|---|---|---|
| `LLM_PROVIDER` | `bailian` | `.env` |
| `DASHSCOPE_API_KEY` | **存在**（长度 115，值不外泄） | `.env` |
| `BAILIAN_API_BASE` | **未设置** → 回落默认值 | `.env` 无此键；`core/config.py:115-118` |
| 实际 endpoint | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `core/config.py:117` |
| `BAILIAN_MODEL` | `qwen3.7-flash` | `.env` |
| `LLM_MODEL_LOCK` | `true` | `.env` |
| HTTP 客户端 | `openai.OpenAI(base_url=…)` → httpx 0.28.1，**默认 `trust_env=True`** | `llm/bailian.py:104-109` |

### 1.1 分级结论表

| 级 | `dashscope.aliyuncs.com`（当前实际端点） | `dashscope-intl.aliyuncs.com`（对照） |
|---|---|---|
| **DNS** | ✅ **PASS** — 4 条 A 记录 `39.96.198.249 / 39.96.213.166 / 8.140.217.18 / 8.152.159.24`；**无 AAAA** | ✅ PASS — 3 条 A 记录 `47.245.114.142 / 47.236.117.191 / 47.236.175.160`；**无 AAAA** |
| **TCP** | ⚠️ **"PASS" 但不可信** — 4/4 IP connect 成功（见 §1.3 反例） | ⚠️ 同上，3/3 成功 |
| **TLS** | 🔴 **FAIL** — 4/4 IP × 重复 5 次 = **9/9 全失败**，`TimeoutError: _ssl.c:993 handshake operation timed out`（8.03–8.05s，高度一致） | ✅ **PASS** — 3/3 IP `TLSv1.3 CN=*.aliyuncs.com`（0.80s） |
| **HTTP** | 🔴 **FAIL** — 从未到达 HTTP 层。4 种出口配置全部 `ConnectTimeout`；curl `http=000`，12.01s | ✅ **PASS** — 到达 HTTP 层，返回 **401** `Incorrect API key provided`（传输通、凭据被拒） |
| **Provider** | 🔴 **FAIL** — 不可达 | 🟡 可达，但大陆 Key 不适用于国际站 |
| **Model** | 🔴 **FAIL** — 真实 `qwen3.7-flash` 最小调用（`max_tokens=1`）**3/3 全失败**：`APITimeoutError status=None`（24.22s / 20.01s / 20.02s） | 未测（无有效国际站 Key） |

**⇒ 链路断点：`TLS` 层。不是 DNS，不是凭据，不是 Provider 故障。**

### 1.2 出口配置对照（4 条路径，结果完全一致）

| 目标 | A. 直连<br>`trust_env=False` | B. Clash 7899 | C. Clash 7897 | D. 沙箱代理 65207<br>`trust_env=True` |
|---|---|---|---|---|
| `dashscope.aliyuncs.com` | 🔴 ConnectTimeout 10.57s | 🔴 ConnectTimeout 10.41s | 🔴 ConnectTimeout 10.44s | 🔴 ConnectTimeout 10.61s |
| `dashscope-intl.aliyuncs.com` | ✅ HTTP 401 3.15s | ✅ HTTP 401 2.47s | ✅ HTTP 401 1.72s | ✅ HTTP 401 1.70s |
| `www.baidu.com`（对照） | ✅ HTTP 404 3.39s | ✅ HTTP 404 2.21s | 🔴 SSLEOF 5.40s | ✅ HTTP 404 2.08s |
| `www.google.com`（curl 对照） | — | ✅ **HTTP 302** 6.68s | — | — |

**读法：** google 经 7899 拿到 302 ⇒ **Clash 本身活着、隧道正常**；
只有大陆 `dashscope.aliyuncs.com` 一个端点，在 4 条出口路径上**一致失败**。
⇒ 与代理配置无关，是**目标端点侧 / 路由侧**的问题。

### 1.3 ⭐ 决定性交叉实验：SNI × IP 矩阵（区分"IP 不可达"与"域名被拦"）

| IP | SNI | 结果 | 读法 |
|---|---|---|---|
| `39.96.198.249`（大陆 IP） | `dashscope.aliyuncs.com` | 🔴 TLS Timeout 8.05s | 基线 |
| `39.96.198.249` | `dashscope-intl.aliyuncs.com` | 🔴 TLS Timeout 8.04s | 换 SNI 也超时 |
| `39.96.198.249` | `www.baidu.com` | 🔴 TLS Timeout 8.03s | 换对照 SNI 仍超时 |
| `47.245.114.142`（intl IP） | `dashscope.aliyuncs.com` | 🟠 **SSLEOFError 1.56s** | **对端有回应**（拒绝该 SNI），不是超时 |
| `47.245.114.142` | `dashscope-intl.aliyuncs.com` | ✅ TLS-OK TLSv1.3 0.80s | 基线 |
| `183.2.172.177`（baidu IP） | `www.baidu.com` | 🟠 TLS Timeout 8.05s | **反例**（见下） |

**结论（三条，每条都被上表直接支持）：**

1. **失败绑定在大陆端点的 IP 上，不是绑定在 SNI 字符串上。**
   证据：把 intl 的 IP 配上 `dashscope.aliyuncs.com` 这个 SNI，拿到的是 **SSLEOFError（1.56s，对端回应了）**，
   而不是 8 秒超时。如果是"SNI 被拦"，这里必须也超时。
   ⇒ 排除"域名关键词被拦"的假设。

2. **排除"IPv6 家族"假设（这正是常见误判）。**
   两个域名**都没有 AAAA 记录**：`getaddrinfo(..., AF_INET6)` 直接 `gaierror [Errno 11004]`。
   既然没有 IPv6 地址可走，"Python 不查 AAAA"这类原因**在物理上不成立**。
   ⇒ 不要套用"IPv6 优先"那套修法。

3. **排除"只有 Python 不通"的假设。**
   `curl --noproxy '*'` 同样 `http=000`（12.01s）；`curl -sv` 停在
   `Trying 39.96.213.166:443... * Connection timed out after 12011 milliseconds`。
   curl 与 Python 行为**一致**。⇒ 不是客户端库差异。

### 1.4 ⚠️ 方法论警告：本机 `TCP = OK` 不构成可达性证据

上表第 6 行是**必须写进报告的反例**：`www.baidu.com` 的 IP 在裸 socket 探测里
**TCP connect 成功、TLS 却超时 8.05s**；而同一台机器上 curl 与 httpx 访问同一个域名
**都能拿到 200 / 404（2.2–3.4s）**。

原因：本机处于 Clash **TUN 模式**（默认路由 metric 0 → `198.18.0.2`）。
TUN 栈会在本地**代答 TCP 握手**，因此：

- `TCP connect = OK` 对**任何** IP 都可能成立 ⇒ **不构成"服务器可达"的证据**；
- `trust_env=False` / `--noproxy '*'` **无法真正绕过** TUN ⇒ "直连"与"走代理"在本机不可区分。

所以本轮判据只采信 **TLS 握手结果** 与 **HTTP 状态码**，不采信 TCP。

### 1.5 Provider 层实测（后端真实端点，1 次真实 LLM 调用）

```
POST /api/llm/test   {"prompt":"ping"}
→ HTTP 503   耗时 30.285s
→ {"success":false,"provider":"bailian","model":"qwen3.7-flash","content":"",
   "error":"Mimo request timeout"}
```

两个独立发现：

1. **LLM 实测不可用**（30.28s ≈ `BAILIAN_TIMEOUT=30.0` 到点超时）。
2. 🔴 **同一响应里 `provider` 写的是 `bailian`，错误文案却写 `Mimo request timeout`。**
   这是与"Demo 模式"**同一族的失真文案**（硬编码 `llm.py:55-66`，9 条错误映射全部写死 "Mimo"）。
   运维看到"Bailian 超时"会被误导去查 Mimo。建议与 §5 一起修。

### 1.6 时变性：这不是一个"永久结论"

`db/app.db::query_history` 里今天 **09:55–09:57** 有 6 条 `success=1` 的真实记录
（单次 5.0–27.3s，真实行数 1/12/1/12/1/5）。而本轮 10:40 起探测**全失败**。

⇒ 断点发生在 **09:57 与 10:16 之间**，出口是**时变的**。
⇒ **禁止**把"现在不通"写成"永久不通"，也**禁止**用改 `base_url` / 换模型的方式"绕过"。

### 1.7 可选修复方向（**本轮不动，需用户决策**）

| 方案 | 性质 | 代价 | 备注 |
|---|---|---|---|
| (a) Clash 切**全局** + 香港/新加坡节点，复测 | 纯环境操作，0 代码改动 | 0 | **推荐先试这条**（T80 曾用此路径成功过） |
| (b) 改用 `dashscope-intl` 端点 + 国际站 Key | **改变运行配置** | 需新 Key | 实测 intl 传输通（401），但大陆 Key 被拒；且与当前 Demo Runtime 口径冲突，必须落盘差异 |
| (c) 切回 `MIMO` provider（`.env` 里 Key 仍在） | **改变运行配置** | 0 | 会与 Clean Baseline 的 MIMO 口径纠缠，需明确说明后再做 |
| (d) 改代码绕过（换 base_url / 加 retry / 换模型） | ❌ **禁止** | — | 任务书 §三 明令：不要用换模型/改代码掩盖网络故障 |

---

## 2. Dashboard 静态数据清单（字段级）

### 2.1 渲染入口追踪（从 `HomePage.tsx` 倒着追）

```
HomePage.tsx  （0 处 api 导入 ← 全仓唯一未接真实接口的页面）
│
├─ <Hero>                    components/Hero.tsx:1   ← demo.ts::exampleQuestions   [UI 常量，非业务数据]
│
├─ <section.kpi-grid>        HomePage.tsx:67-79     ← demo.ts::kpiData            [🔴 假业务数据 ×4]
│
├─ <AnalysisFlow>            HomePage.tsx:81-88     ← demo.ts::agentStages        [UI 常量]
│   （条件渲染，phase !== idle）                      ← demo.ts::demoResult        [🔴 假结果值]
│   ⚠️ 动画是纯 setTimeout 假动画：HomePage.tsx:31-53 的 startAnalysis 里
│      **没有任何 fetch / api 调用**，只是 setStageIndex 每 700ms 走一格
│
├─ <section.analysis-grid>
│   ├─ <ChartCard 销售趋势>   HomePage.tsx:91        ← data/charts.ts:13-64
│   │                                                  ← charts.ts:2 ← demo.ts::salesTrend   [🔴 假]
│   └─ <ChartCard 分类销售>   HomePage.tsx:92        ← data/charts.ts:67-109
│                                                      ← charts.ts:2 ← demo.ts::categorySales [🔴 假]
│
├─ <TopProducts>             HomePage.tsx:96        ← demo.ts::topProducts       [🔴 假业务数据 ×5]
│
├─ <section.card 最近动态>    HomePage.tsx:97-111    ← **无数据源**，纯占位 UI
│                                                      文字："阶段 1 保留占位结构"
│
├─ <span.section-sub>        HomePage.tsx:118       ← **硬编码字面量**（无条件渲染）
│                                                      "Demo 模式：静态演示数据，未连接后端"
│
├─ <DbStatus>                HomePage.tsx:121       ← GET /api/health + /api/system/database  [✅ 真实]
│
└─ <PresentationOverlay>     HomePage.tsx:123-134   ← agentStages + demoResult + presentationChart
    （条件渲染，presentation === true）                footer 硬编码："…SQLite · 已连接 | … | Demo 模式：暂未连接后端"
                                                      ↑ 同一句里自相矛盾（既说已连接又说未连接）
```

### 2.2 字段级清单（字段名 / 来源 / 引用位置 / 用途 / 真值对照）

| # | 字段 | 来源（文件:行） | 引用位置 | 用途 | demo 值 | **SQLite 真值** | 判定 |
|---|---|---|---|---|---|---|---|
| 1 | `kpiData[0].value` | `demo.ts:11` | `HomePage.tsx:68-77` | KPI 卡「本月销售额」 | `¥7,662,921` | **`766,292.18` 元** | 🔴 **差 10.0000×** |
| 2 | `kpiData[0].trend` | `demo.ts:11` | 同上 | KPI 卡趋势 `+12.4%` | `+12.4%` | **无任何来源** | 🔴 编的 |
| 3 | `kpiData[1].value` | `demo.ts:12` | 同上 | KPI 卡「订单量」 | `1,284` 单 | **`234` 单** | 🔴 差 5.49× |
| 4 | `kpiData[2].value` | `demo.ts:13` | 同上 | KPI 卡「用户数」 | `2,000` 人 | **`2,000` 人** | 🟢 **数值完全一致** ⚠️ |
| 5 | `kpiData[3].value` | `demo.ts:14` | 同上 | KPI 卡「客单价」 | `¥352.6` | **`3,274.75` 元/单** | 🔴 差 9.29× |
| 6 | `kpiData[3].trend` | `demo.ts:14` | 同上 | KPI 卡趋势 `-1.8%` | `-1.8%` | **无任何来源** | 🔴 编的 |
| 7 | `salesTrend.months/values` | `demo.ts:18-21` | `charts.ts:26,43` → `HomePage.tsx:91` | 销售趋势折线图 | 12 月，`612…766`（万元） | 见 §6-T3（2025-09…2026-08 实际 117.9…220.7 万元） | 🔴 全假 |
| 8 | `categorySales[]` | `demo.ts:24-30` | `charts.ts:82,99` → `HomePage.tsx:92` | 分类销售柱状图 | 5 类，`218/186/172/124/98`（万元） | 叶子类目 Top5：`829.0/655.7/542.6/208.3/180.9`（万元） | 🟠 **类目名与排序完全真实，数值全假** |
| 9 | `topProducts[]` | `demo.ts:33-39` | `TopProducts.tsx:12-25` | Top5 商品榜 | 星耀/极光/轻云/灵犀/远航 | 真实库 `LIKE` 命中 **0**（5 个品牌词全 0） | 🔴 **100% 虚构** |
| 10 | `demoResult.value/unit` | `demo.ts:78-83` | `AnalysisFlow.tsx:70,72`、`HomePage.tsx:127-128` | 假流程「查询结果」 | `¥7,662,921` | — | 🔴 同 #1 |
| 11 | `presentationChart.months/values` | `demo.ts:86-89` | `charts.ts:124,141` → `HomePage.tsx:129` | 汇报模式侧图 | 7 月 `668…766` | — | 🔴 全假 |
| 12 | `exampleQuestions[]` | `demo.ts:57-64` | `Hero.tsx:51` | 首页示例问题按钮 | 6 条文案 | — | 🟢 **UI 常量，可保留** |
| 13 | `agentStages[]` | `demo.ts:67-75` | `AnalysisFlow.tsx:49,86`、`AnalysisPage.tsx:168`、`HomePage.tsx:126` | 7 阶段名称 | 7 个阶段名 | — | 🟢 **UI 常量，可保留** |
| 14 | `analysisExamples[]` | `demo.ts:97-103` | `AnalysisPage.tsx:254` | 分析页示例问题 | 5 条文案 | — | 🟢 UI 常量，可保留 |
| 15 | `dbStatus` | `demo.ts:42-54` | **0 引用** | — | — | — | ⛔ **死代码** |
| 16 | `analysisSql` | `demo.ts:106-110` | **0 引用** | — | — | — | ⛔ 死代码 |
| 17 | `stageDetails` | `demo.ts:113-139` | **0 引用** | — | — | — | ⛔ 死代码 |
| 18 | `validationError` | `demo.ts:142-145` | **0 引用** | — | — | — | ⛔ 死代码 |
| 19 | `analysisTrace` | `demo.ts:148-156` | **0 引用** | — | — | — | ⛔ 死代码 |
| 20 | `analysisResult` | `demo.ts:159-166` | **0 引用** | — | — | — | ⛔ 死代码 |

### 2.3 死代码判定（权威判据 = import 语句，不是名字出现次数）

`data/demo.ts` 的 15 个导出里，**6 个是真死代码**（`dbStatus` / `analysisSql` / `stageDetails` /
`validationError` / `analysisTrace` / `analysisResult`），全仓**零 import**。

**独立佐证（打包器证据，比 grep 更硬）**——`frontend/dist/assets/index-1yM7_xld.js` 里：

| 字面量 | bundle 命中 | 含义 |
|---|---|---|
| `7,662,921` | **2** | 活代码：`kpiData[0].value` + `demoResult.value` |
| `1,284` | 1 | 活代码：`kpiData[1].value` |
| `352.6` | 1 | 活代码：`kpiData[3].value` |
| `星耀` | 1 | 活代码：`topProducts[0].name` |
| `家用电器` | 1 | 活代码：`categorySales[0].name` |
| **`30,457`** | **0** | ⛔ **死代码被 tree-shake 掉了**——`30,457` 只出现在 `demo.ts:52` 的 `dbStatus` 里 |
| `Demo 模式` | 5 | 硬编码文案 |

> 注意 `salesTrend` / `categorySales` / `presentationChart` 三个名字在 `src/` 里"外部命中 0"，
> 但它们是**间接存活**的（唯一消费者是 `data/charts.ts:2`）。用"名字命中数"判死代码会误判，
> 必须看 import 图。

### 2.4 ⭐ 三方对照（SQLite 真值 / demo 静态值 / 渲染后 DOM）

DOM 证据来自本轮**真实无头渲染**（`chrome-headless-shell`，`--virtual-time-budget=12000`，
`http://localhost:5173/` → 67,841 B DOM，落盘 `F:\p9_audit\dom\home.html`）：

| 展示项 | ① demo.ts 静态值 | ② SQLite 真值 | ③ 渲染后 DOM | 一致性 |
|---|---|---|---|---|
| 本月销售额 | `¥7,662,921` | **`766,292.18` 元** | `¥7,662,921` | ①=③，**≠②（10×）** |
| 订单量 | `1,284` | **`234`** | `1,284` | ①=③，**≠②** |
| 用户数 | `2,000` | **`2,000`** | `2,000` | **①=②=③（巧合一致）** |
| 客单价 | `¥352.6` | **`3,274.75`** | `¥352.6` | ①=③，**≠②** |
| Top5 商品名 | 星耀/极光/轻云/灵犀/远航 | 九阳毛绒玩具旗舰款 … | demo 名（各命中 2 次） | ①=③，**≠②（0 命中）** |
| DbStatus 6 项 | （死代码） | 5/2000/30/500/10000/**30457** | **5/2000/30/500/10000/30457** | **②=③ ✅ 真实 API** |
| Header Runtime LLM | — | bailian / qwen3.7-flash | **`bailian · qwen3.7-flash`** | **②=③ ✅ 真实 API** |
| 状态文案 | — | — | `Demo 模式：静态演示数据，未连接后端`（命中 1） | 🔴 假失败 |

> 分类图与趋势图渲染进 `<canvas>`，类目名/月份不出现在 DOM 文本里
> （`家用电器`/`电脑办公`/`手机通讯`/`运动装备` 在 DOM 中命中 **0**）——这是 ECharts 的正常行为，
> 不构成"没渲染"的证据。对图表的验收必须用 ECharts instance 的 `getOption()`，不能 grep DOM。

### 2.5 🔴 三个必须记住的"自欺陷阱"

**陷阱 1 —— 假数据不是乱编的，是"照真实库抄了形状、错了量级"。**

`¥7,662,921 ÷ 766,292.18 = 10.0000`（精确 10 倍）。
⇒ 它**来自真实库**，只是量级搞错了（元/角，或万/十万）。这比 `12345` 这种明显占位危险得多——
它"看起来非常真实"，肉眼无法识破。

**陷阱 2 —— 分类图的类目名与排序 100% 正确。**

demo 的 5 个类目 `家用电器 > 电脑办公 > 手机通讯 > 家具 > 运动装备`，
与真实库按 `SUM(oi.subtotal)` 排序的**叶子类目 Top5 完全一致**（含顺序）。
（注意：真实库按**销量**排序时 `运动装备(1887) > 家具(1884)`，与 demo 顺序不符 ⇒ 可确认
demo 是照**销售额**排序抄的。）
⇒ 只有数值是编的。**"名字对"会让人误以为"数据对"。**

**陷阱 3 —— 用户数 `2,000` 在接线前后数值完全相同。**

`demo.ts:42` 的注释自己写着"真实开发库规模，来源于 database-schema.md"——
它当初就是照真实库抄的。所以：
> **验收判据必须选"值会变的项"（销售额 / 订单量 / 客单价 / Top5 第 1 名），
> 绝对不能用"用户数"。** 用用户数验收，接线成功与失败都显示 `2,000`，等于没验。

---

## 3. 当前 API 能力（全部实测，非代码推断）

`GET /openapi.json` → **16 条 `/api` 路由**。逐条实测：

| 端点 | 方法 | 认证 | 实测结果 | 能否支撑 Dashboard |
|---|---|---|---|---|
| `/api/health` | GET | 无 | **200** `{"status":"ok","service":"ecommerce-analysis-agent","database":{"status":"ok","type":"sqlite","name":"ecommerce.db"},"llm":{"provider":"bailian","model":"qwen3.7-flash"}}` | 🟡 见 §3.1 |
| `/api/system/database` | GET | 无 | **200** `{"database":"ecommerce.db","tables":5,"users":2000,"categories":30,"products":500,"orders":10000,"order_items":30457}` | ✅ 规模汇总 |
| `/api/system/schema` | GET | 无 | 200，5 表逐字段结构 | ✅ 数据集页已用 |
| `/api/history` | GET | **Bearer** | 无 token → **401** `{"detail":"Invalid credentials"}` | ✅ 最近动态（本人隔离） |
| `/api/history/{id}` | DELETE | Bearer | — | — |
| `/api/agent/analyze` | POST | Bearer | 无 token → 401；错误方法 → 405 `{"detail":"Method Not Allowed"}` | ✅ 分析页已用 |
| `/api/llm/test` | POST | **无** | **503**（30.28s）`{"success":false,"provider":"bailian","model":"qwen3.7-flash","error":"Mimo request timeout"}` | 🟡 唯一 LLM 探活，见 §3.1 |
| `/api/auth/{login,register,me,logout}` | POST/GET | 部分 | — | ✅ |
| `/api/schema/link`、`/api/fewshot/retrieve`、`/api/sql/{generate,execute,execute-with-repair,repair}` | POST | 无 | — | ❌ 非 Dashboard 所需 |
| **`/api/insights/overview`** | — | — | **404 `{"detail":"Not Found"}`** | ⛔ **尚不存在（已实测证明）** |

### 3.1 ⚠️ 关键发现：`/api/health` **不能**用来判定「LLM Available」

`health.py:28-32` 的注释自己写明了：

> 「`get_llm_provider()` 是全系统唯一的 Provider 分派入口…**构造 Provider 实例只读环境配置，
> 不产生任何网络请求**」

**本轮实测把这个矛盾直接钉死了：**

| 时刻 | 端点 | 结果 |
|---|---|---|
| 10:52 | `GET /api/health` | **200**，`llm: {"provider":"bailian","model":"qwen3.7-flash"}` |
| 10:55 | `POST /api/llm/test` | **503**，30.28s 超时 |

**同一个后端、同一分钟内：health 说 LLM 配置正常，llm/test 说 LLM 超时。**
⇒ 若前端用 `health.llm` 渲染「LLM Available」，就会在 LLM 已经挂了 30 秒超时的同时显示绿灯。
**这正是任务书 §七 点名禁止的那种假状态。**

现有唯一可用的真实 LLM 探活机制是 `POST /api/llm/test`，但它有 4 个问题：
1. 是 **POST**（不能用于页面挂载时的轻量状态查询）；
2. **无认证**（任何人可打，每次消耗一次真实 LLM 调用）；
3. 每次**消耗真实配额**（不能每 30 秒轮询）；
4. 失败文案硬编码 `"Mimo …"`（`llm.py:55-66`），`provider=bailian` 时输出 `Mimo request timeout` —— **文案说谎**。

### 3.2 `/api/history` 的既有隔离（可直接复用）

`history.py:6-11`：`WHERE user_id = ?` 强制隔离；跨用户/不存在统一 404；响应模型**不含** `user_id`/`session_id`/hash。
返回字段：`id / question / sql / success / error_message / result_summary / row_count / total_time_ms / created_at`。

⇒ 任务书 §十 要的「时间 / 问题 / 状态 / 耗时」**四项已齐**；
「用户」这一项**接口刻意不返回**（防越权）。**不能为了展示"用户"而把全站历史暴露出去。**

### 3.3 封装层复用评估（前端）

| 模块 | 已有能力 | 对 overview 是否可复用 |
|---|---|---|
| `api/http.ts` | `apiRequest<T>()`：统一 base URL、Bearer 自动注入、`detail`/`error` 解析、401 全局登出 | ✅ **必须复用**；注意 `auth` 默认 `true`，overview 若要匿名访问必须显式 `auth: false` |
| `api/system.ts` | 自建 `getJson()`（**不走 http.ts**），`SystemApiError`，错误体 `detail`/`error` 双解析 | 🟡 可作参考；不建议新增第三套 fetch 封装 |
| `api/history.ts` | `listHistory(page,pageSize,signal)` | ✅ 最近动态直接复用 |
| `utils/chart.ts` | `buildChartOption(result)` 规则型映射（列名匹配、最多 50 点） | ❌ **不建议复用**：它面向 `columns/rows` 动态结构，overview 是固定 shape，硬套反而脆弱 |
| `data/charts.ts` | 3 个 option 构造函数，**但内部直读 demo.ts** | ⚠️ 需改造为**接收数据参数**（保留视觉配置，切断 demo 依赖） |

`http.ts:101` 注释明确：「所有 API 模块经由本函数，页面不得散落 fetch」——
新增 `api/insights.ts` 必须遵守这条，不得自建 fetch。

---

## 4. 新增 `GET /api/insights/overview` 的设计（本轮只设计，不实现）

### 4.1 接口契约

```
GET /api/insights/overview
```

| 决策点 | 建议 | 理由 |
|---|---|---|
| **认证** | **不加 Bearer**（公开只读聚合） | 首页在未登录时也必须显示真实数据。若加 Bearer，未登录用户首页直接 401 → 与「首页必须真实」自相矛盾。overview 是**全局聚合**，不含任何用户隐私，与 `/api/health`、`/api/system/database` 同级。<br>⚠️ **此决策需用户确认。** |
| **只读实现** | 复用 `app.db.sqlite.get_connection()` | 该函数已提供 `mode=ro`（文件级）+ `PRAGMA query_only=ON`（会话级）**双重只读**（`sqlite.py:4-5,70-77`）。**绝不新增第二条 DB 访问路径**，也绝不放宽这两个约束。 |
| **SQL 形态** | 只允许 `SELECT` / `WITH`；**不接收任何用户输入**（无参数、无 query string） | 与 `/api/system/database` 的"固定 SQL"策略一致，从根上消除注入面 |
| **缓存** | 第一版**不加**，先实测延迟再定 | 3 表 join（`order_items` 30,457 × `orders` 10,000）延迟未知；实测后可加 30–60s 进程内 TTL |
| **异常行为** | DB 不可读 → **503** `{"detail": "..."}`；空库 → **200** + 0/空数组 | 503 响应体形态与 `/api/system/database`（实测同为 `{"detail":...}`）保持一致 |

### 4.2 响应体（字段全部可回溯到真实列）

```json
{
  "as_of": "2026-09-12",
  "generated_at": "2026-09-28T03:00:00Z",
  "kpis": {
    "month_sales":      { "label": "本月销售额", "value": 766292.18, "unit": "元",    "month": "2026-09" },
    "month_orders":     { "label": "订单量",     "value": 234,       "unit": "单",    "month": "2026-09" },
    "users_total":      { "label": "用户数",     "value": 2000,      "unit": "人" },
    "avg_order_value":  { "label": "客单价",     "value": 3274.75,   "unit": "元/单", "month": "2026-09" }
  },
  "sales_trend": [ { "month": "2025-10", "sales": 1327764.13 }, "…共 12 项" ],
  "category_distribution": [
    { "category": "家用电器", "sales": 8290243.71, "quantity": 2959 }, "…共 5 项"
  ],
  "top_products": [
    { "rank": 1, "product": "九阳毛绒玩具旗舰款", "quantity": 130, "sales": 22800.70 }, "…共 5 项"
  ]
}
```

### 4.3 明确拒绝的三个做法

1. ❌ **不返回 `trend`（`+12.4%` / `-1.8%`）**。
   demo 里这两个百分比**没有任何真实来源**（既不是环比也不是同比，无法回溯）。
   第一版**不返回、UI 也不显示箭头**，避免又一次编数字。若确需，必须明确定义口径（环比上月？）并单独落盘。
2. ❌ **不在 overview 里返回 `recent_activity`**。
   历史是**用户私有数据**，必须走 `/api/history` 的既有 `user_id` 隔离。
   塞进 overview 只有两个后果：要么破坏隔离（暴露全站历史，违反 §十），要么强制 overview 也要 Bearer（与 4.1 冲突）。
   ⇒ **最近动态由前端单独调 `GET /api/history`**。
3. ❌ **不在前端拼 SQL、不在前端做聚合**。所有数值必须由后端 SQL 产出。

### 4.4 `top_products` 指标必须二选一并写进 UI

真实库两种口径结果**完全不同**（已实测）：

| 口径 | Top1 |
|---|---|
| 按**销量** `SUM(oi.quantity)` | 九阳毛绒玩具旗舰款（130 件） |
| 按**销售额** `SUM(oi.subtotal)` | 恒源祥笔记本电脑Plus（¥944,485.34） |

**建议按销售额**（与分类图口径统一），并把 `TopProducts.tsx:9` 的副标题
从「按销量排序 · Demo 数据」改成「按销售额排序 · 实时业务数据」。

### 4.5 `as_of` 必须在 UI 上展示

真实库 `MAX(order_date) = 2026-09-12`，而今天是 09-28。
⇒「本月销售额」实际只覆盖 **09-01 ~ 09-12**。
若不展示 `as_of`，用户会以为 766,292.18 是整个 9 月，**这本身就是一种新的失真**。
⇒ 首页必须出现「数据截至 2026-09-12」之类的字样。

---

## 5. 前端改造点

### 5.1 必须修改（最小白名单）

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `frontend/src/api/insights.ts` | **新增**。封装 overview 契约，复用 `http.ts::apiRequest`（`auth: false`），导出 `OverviewDto` 与 `fetchOverview(signal)` |
| 2 | `frontend/src/pages/HomePage.tsx` | ① 引入 `LOADING / READY / ERROR` 三态（对齐 `DbStatus.tsx:20,59` 的既有模式）；② **删除 `:118` 与 `:131` 的硬编码「未连接后端」**；③ KPI 4 卡改真实数据（`:67-79`）；④ 图表改真实数据（`:90-93`）；⑤ 最近动态接 `/api/history`（`:97-111`）；⑥ 失败时**显示错误态，禁止回退 demo** |
| 3 | `frontend/src/components/TopProducts.tsx` | 去掉 `:1` 的 `demo.ts` 导入，改为 **props 接收** `items`；`:9` 副标题写明指标口径 + 实时数据 |
| 4 | `frontend/src/components/AnalysisFlow.tsx` | 删除 `:41` 的「Demo 模式」徽标与 `:95` 的失真文案；改由传入的真实 phase 驱动（`AnalysisPage` 已有真流程可参考） |
| 5 | `frontend/src/components/Header.tsx` | `:55` 的 `SQLite · 已连接` 改为读 `fetchHealth()` 的 `database.status`。**该组件已经在调 `/api/health`（`:39`），只是没把 database 字段用起来**——改动量极小 |
| 6 | `frontend/src/pages/AnalysisPage.tsx` | `:188` 与 `:474` 的无条件「已连接」改为真实 health 状态 |
| 7 | `frontend/src/data/charts.ts` | 3 个 option 函数改为**接收数据参数**（保留全部视觉配置，删除 `:2` 对 `demo.ts` 的 import） |
| 8 | `frontend/src/data/demo.ts` | ⚠️ **本轮不动**。按 §十六 要求，先完成接线 → 再搜引用 → 确认 0 有效引用 → 再决定删除。可先加 `@deprecated` 注释标记 6 项死代码 |

### 5.2 可选修改（默认不做，需单独授权）

| 项 | 说明 | 为什么默认不做 |
|---|---|---|
| `DbStatus.tsx` 增加 LLM 状态 | 需要先解决 §3.1 的机制问题 | 机制未定，先做会返工 |
| 新增 `GET /api/insights/health`（轻量 LLM 状态） | 替代昂贵的 `/api/llm/test` | 属**新增后端能力**，超出本轮；且"LLM 可用性"是否需要每次探活需产品决策 |
| 复用 `utils/chart.ts` | — | 固定 shape 用不上规则型映射 |
| 引入前端路由（React Router） | `App.tsx:22` 用 `useState<PageKey>` 切页，刷新丢页、无深链 | 超出本轮范围，且改动面大 |

### 5.3 禁止修改

| 类别 | 具体 |
|---|---|
| 冻结交付 | `_delivery_build/**`（v1.0.0 `FINAL_DELIVERY_LOCKED`，SHA256 已核验） |
| 运行配置 | `.env`（当前是 Demo Runtime 口径：`bailian` + `qwen3.7-flash` + `LLM_MODEL_LOCK=true`） |
| 数据 | `db/ecommerce.db`、`db/app.db` |
| 评测冻结物 | `evaluation/**`、`scripts/run_eval.py`、`backend/app/sqlgen/prompt.py`、`semantic_contracts.py`、`date_window.py`、scope validator |
| 既有后端行为 | 所有既有路由的现有响应/状态码——本轮只允许**新增** insights 路由，不改既有端点 |
| 只读约束 | `app/db/sqlite.py` 的 `mode=ro` + `query_only=ON` —— **不得为了 Dashboard 绕过**（任务书 §六） |

### 5.4 样式容量评估（结论：**可做到零 CSS 修改**）

| 需求 | 现有类 | 结论 |
|---|---|---|
| 四态徽标 | `base.css:114 .badge-success` / `:122 .badge-warning` / `:130 .badge-error` / `:138 .badge-processing` | ✅ 四态齐全 |
| KPI 卡 | `home.css:157 .kpi-card` + `__head/__icon/__value/__foot/__trend--up/--down/__unit` | ✅ 齐备 |
| 图表卡 | `.chart-card` + `__head` | ✅ |
| 列表 | `home.css` `.top-products` + `__item/__rank/__name/__meta/__sales/__amount` | ✅ |
| DB 卡 | `home.css:310 .db-card` + `__head/__file/__type/__stats/__stat` | ✅ |
| 辅助小字 | `.section-sub` | ✅ |

⇒ 新增 `LOADING`（`badge-processing` + "加载中"）与 `ERROR`（`badge-error` + `btn-primary` 重试）
两个状态，**用既有类就能拼出来**，无需新增 CSS。

---

## 6. 数据库 SQL 来源（每条指标可回溯，全部已实测执行）

**真实表结构**（`PRAGMA table_info`，只读）：

```
categories   (30)   id, name, parent_id          ← 层级：8 个顶层 + 22 个叶子
products     (500)  id, name, category_id, price, status   ← status: on_sale 461 / off_sale 39
orders       (10000) id, user_id, order_date, status, region, discount_amount, shipping_fee, total_amount
order_items  (30457) id, order_id, product_id, quantity, unit_price, subtotal
users        (2000)  id, username, email, region, register_date, status
```

**值域探查（决定口径，全部实测）：**

```
orders.status   : completed 6072 / shipped 1503 / paid 991 / pending 956 / cancelled 478
orders.order_date: 2024-01-01  →  2026-09-12      ← MAX = 2026-09-12（今天 09-28）
products.status : on_sale 461 / off_sale 39
users.status    : active 1707 / 其余 293          ← 全表 2000
```

### T1 · KPI-本月销售额

```sql
SELECT ROUND(SUM(total_amount), 2) AS sales
FROM orders
WHERE strftime('%Y-%m', order_date) = (SELECT strftime('%Y-%m', MAX(order_date)) FROM orders)
  AND status != 'cancelled';
-- 实测 = 766292.18
```

### T2 · KPI-订单量

```sql
SELECT COUNT(*) AS orders_count
FROM orders
WHERE strftime('%Y-%m', order_date) = (SELECT strftime('%Y-%m', MAX(order_date)) FROM orders)
  AND status != 'cancelled';
-- 实测 = 234
```

### T3 · KPI-用户数（**口径必须选定**）

```sql
SELECT COUNT(*) FROM users;                      -- 实测 = 2000  ← demo 用的就是这个
SELECT COUNT(*) FROM users WHERE status='active';-- 实测 = 1707
```
⚠️ 两者差 293，**必须选一个并写进 UI 文案**（如"平台注册用户 2,000"），否则是新的口径黑洞。

### T4 · KPI-客单价

```sql
-- = T1 / T2
-- 实测 = 3274.75 元/单
```

### T5 · 销售趋势（近 12 个月，锚定 `MAX(order_date)`）

```sql
SELECT strftime('%Y-%m', order_date) AS month, ROUND(SUM(total_amount), 2) AS sales
FROM orders
WHERE status != 'cancelled'
GROUP BY month
ORDER BY month DESC
LIMIT 12;      -- 取回后按 month 升序返回
```
实测区间 `2025-10 … 2026-09`（2025-09…2026-08 实测值见 §2.2 #7）。

### T6 · 类目分布（**叶子类目** Top5，与 demo 视觉一致）

```sql
SELECT cat.name AS category,
       ROUND(SUM(oi.subtotal), 2) AS sales,
       SUM(oi.quantity)           AS quantity
FROM order_items oi
JOIN orders     o   ON o.id = oi.order_id
JOIN products   p   ON p.id = oi.product_id
JOIN categories cat ON cat.id = p.category_id
WHERE o.status != 'cancelled'
GROUP BY cat.id
ORDER BY sales DESC
LIMIT 5;
-- 实测：家用电器 8,290,243.71 / 电脑办公 6,556,561.93 / 手机通讯 5,425,863.40
--       家具 2,083,433.74 / 运动装备 1,808,941.20
```
（若改按顶层类目，需 `JOIN categories root ON root.id = COALESCE(leaf.parent_id, leaf.id)`，
实测 Top1 = 数码家电 20,272,669.04 —— 但会与 demo 的视觉结构不一致，故建议叶子。）

### T7 · Top5 商品（**按销售额**，与 T6 口径统一）

```sql
SELECT p.name AS product,
       SUM(oi.quantity)           AS quantity,
       ROUND(SUM(oi.subtotal), 2) AS sales
FROM order_items oi
JOIN orders   o ON o.id = oi.order_id
JOIN products p ON p.id = oi.product_id
WHERE o.status != 'cancelled'
GROUP BY p.id
ORDER BY sales DESC
LIMIT 5;
-- 实测：恒源祥笔记本电脑Plus 944,485.34 / 良品铺子智能手机Air 833,577.08
--       珀莱雅笔记本电脑青春版 813,380.79 / 小米智能手机Air 777,364.69 / 无印良品笔记本电脑臻享款 761,414.58
```

### 口径决策清单（必须落盘，否则下轮返工）

| # | 决策 | 建议值 | 状态 |
|---|---|---|---|
| D1 | 「本月」定义 | `MAX(order_date)` 所在月（=2026-09），**不是 `date('now')`** | 🟡 待确认 |
| D2 | 销售额是否排除 `cancelled` | **排除**（本月实测影响为 0，但全库必须一致） | 🟡 待确认 |
| D3 | 用户数口径 | `COUNT(*)` = 2,000（UI 写"平台注册用户"） | 🟡 待确认 |
| D4 | 类目分布粒度 | 叶子类目 Top5 | 🟡 待确认 |
| D5 | Top5 指标 | 按**销售额** | 🟡 待确认 |
| D6 | overview 是否要 Bearer | **不要**（公开只读聚合） | 🟡 待确认 |
| D7 | 是否展示 `as_of` | **必须展示** | 🟡 待确认 |

---

## 7. 风险

| # | 级别 | 风险 | 证据 / 影响 |
|---|---|---|---|
| **R1** | 🔴 高 | **出口时变**：09:57 还能成功，10:16 起 100% 失败。任何依赖 LLM 的验收会随机失败 | §1.6。**缓解**：Dashboard 链路（SQLite→API→UI）**不依赖 LLM**，可先独立交付——这正是 §十五 要求分开验收的价值 |
| **R2** | 🔴 高 | **假数据比看起来更接近真值**：销售额差 10.0000×（不是乱写）；类目名与排序 100% 正确；用户数完全一致 | §2.5。**缓解**：验收判据必须用"值会变的项"，且必须做 §十四 三方对照 |
| **R3** | 🔴 高 | **`/api/health` 的 `llm` 字段会被误读成「LLM 可用」** | §3.1 已实测证伪：同一分钟 health=ok / llm/test=503。**缓解**：前端渲染 LLM 状态前必须先解决机制问题 |
| **R4** | 🟠 中 | **LLM 失败文案硬编码 "Mimo"**（`llm.py:55-66`），`provider=bailian` 时输出 `Mimo request timeout` | §1.5 实测。与「Demo 模式」同族失真文案，建议与 §5 一并修 |
| **R5** | 🟠 中 | **overview 若要求 Bearer，未登录首页将 401** | 与"首页必须真实"直接冲突。D6 需先决策 |
| **R6** | 🟠 中 | **CORS 只允许 `http://localhost:5173`**；Vite 仅监听 `[::1]` | 实测 `127.0.0.1:5173` 被拒 400。验收必须用 `http://localhost:5173`，否则会误判"前端挂了" |
| **R7** | 🟡 低 | **overview 延迟未知**：`order_items(30,457) × orders(10,000)` 三表 join 未实测 | Phase C 必须实测后再决定是否加 TTL 缓存 |
| **R8** | 🟡 低 | `demo.ts` 6 项死代码仍在仓库 | 接线不彻底时后人可能误用；建议 `@deprecated` 标记 |
| **R9** | 🟡 低 | 前端无路由（`App.tsx:22` `useState<PageKey>`），刷新丢页、无深链 | 不影响本轮，但影响"可分享的验收链接" |
| **R10** | 🟡 低 | **本机为 Clash TUN + fake-ip 模式**，所有"网络可达性"结论都绑定当前 TUN 配置 | §1.4。换模式（如切系统代理）结论会变。报告必须带此环境前提，否则后人会误读为"服务端故障" |

---

## 8. 下一轮实施计划

### 8.1 本轮（第一轮）交付边界 —— 已完成的只是 A + B

```
✅ Phase A  Runtime LLM 网络只读诊断      → §1（含 SNI×IP 决定性交叉实验）
✅ Phase B  Dashboard 静态数据依赖审计    → §2（字段级 20 项 + 死代码判定 + 三方对照）
✅ 附赠：当前 API 能力实测（§3）、overview 设计（§4）、前端改造点（§5）、SQL 来源（§6）
⛔ 未做：C / D / E / F / G / H / I（一行代码未改）
```

### 8.2 下一轮（第二轮）建议范围 —— 严格按依赖顺序

**第 0 步（阻塞项，必须先回答）**：确认 §6 的 D1–D7 七个口径决策。
其中 **D6（overview 是否要 Bearer）** 是硬阻塞——它决定前端接线方式，答错要整体返工。

**第 1 步 · Phase C：后端新增只读聚合端点**

- 新增 `backend/app/api/routes/insights.py`（`APIRouter(tags=["insights"])`，`main.py` 注册 `prefix="/api/insights"`）
- 新增 `backend/app/schemas/insights.py`（响应模型）
- 只读实现：复用 `app.db.sqlite.get_connection()`，**不新增 DB 访问路径**
- 新增 `backend/tests/test_insights_api.py`，至少 5 类用例：
  1. 正常返回（字段齐全 + 数值类型）
  2. **空数据库**行为（0 行 → 200 + 0/空数组，**不是 500**）
  3. **数据库异常**行为（不可读 → 503 + `detail`）
  4. **只读约束**测试（`query_only` 生效，任何写操作抛错）
  5. **非法参数**测试（overview 无参数；越界/多余 query string 被忽略而非 500）

**第 2 步 · Phase D（收窄版）：首页只接 KPI + Top5**

- 新增 `frontend/src/api/insights.ts`
- `HomePage.tsx` 引入三态；KPI 4 卡 + Top5 接真实数据
- **图表与"最近动态"留到第三轮**（缩小单轮改动面，便于定位问题）
- 前端测试至少 4 例：真实数据正常 / API 失败（→ ERROR 态且**不回退 demo**）/ 加载中 / 空数据

**第 3 步 · 验收（§十四 要求的三方对照）**

用**会变的项**做判据，每项 3 条：

| 对照项 | ① SQLite 直查 | ② `GET /api/insights/overview` | ③ 浏览器 DOM |
|---|---|---|---|
| KPI-本月销售额 | `766292.18` | 同 | 渲染值 |
| KPI-订单量 | `234` | 同 | 渲染值 |
| KPI-客单价 | `3274.75` | 同 | 渲染值 |
| Top5 第 1 名 | `恒源祥笔记本电脑Plus` | 同 | 渲染值 |
| 销售趋势 2026-08 | `2206807.1` | 同 | ECharts `getOption()`（**不能 grep DOM**） |

⚠️ **不要用「用户数 2,000」做验收**（接线前后都一样，见 §2.5 陷阱 3）。

**第 4 步 · Phase A 复测（与代码改造并行，互不阻塞）**

- 请用户把 Clash 切**全局 + 香港/新加坡节点**，然后**只重跑** `F:\p9_audit\net_probe.py`
- **不要**为了"让 Agent 能跑"而改 `base_url` / 换模型（任务书 §三 明令禁止）

### 8.3 第三轮 / 第四轮（预告）

| 轮次 | 范围 |
|---|---|
| 第三轮 | 图表接线（`charts.ts` 改参数化）+ 最近动态接 `/api/history` + **Phase G 删除 demo fallback** + **Phase E Health/Runtime 状态统一**（含 LLM 状态机制决策，见 §3.1） |
| 第四轮 | **Phase H 全量测试** + **Phase I 真实浏览器验收** + `demo.ts` 死代码清理（先证 0 引用） |

### 8.4 一句话提醒

> 本阶段真正的目标不是"删掉 Demo 两个字"，而是
> **让用户看到的每一个数字都能追溯到真实数据库**。
> 本轮审计最大的收获恰恰是：**demo 里的假数据是照着真实库抄的**——
> 所以"看起来对"完全不能作为验收依据，只有**三方对照 + 会变的判据**才算数。

---

## 附录 A：本轮只读边界证明

```
开工  git status --porcelain -uall  = 1978 行   (HEAD = master @ 6c5f51c)
收工  git status --porcelain -uall  = 1978 行
diff   → 空（无差异）
唯一新增 = reports/phase9/第九阶段第一轮AB_Runtime网络诊断与首页静态数据审计报告.md
```

- 未修改任何既有文件（含 `frontend/`、`backend/`、`.env`、`_delivery_build/`、`db/*.db`）
- 未删除任何 Demo / Mock / UI 文案；未启动、未停止任何服务；未注册账号
- 数据库访问全部经 `mode=ro` + `query_only=ON` 的只读连接（`get_connection()`）
- 探针与产物全部在**仓库外** `F:\p9_audit\`：

```
F:\p9_audit\
├─ net_probe.py            分级诊断（DNS/TCP/TLS/HTTP/Model，4 出口配置）
├─ net_probe_result.json
├─ net_probe2.py           SNI×IP 交叉矩阵 + curl 对照 + 重复测量
├─ net_probe2_result.json
├─ dump_schema.py          表结构 + 值域探查
├─ schema_dump.json
├─ truth_baseline.py       demo 静态数字的真实库真值
├─ truth_baseline.json
└─ dom\
   ├─ home.html           无头渲染后的 DOM（67,841 B）
   └─ profile\
```

## 附录 B：本轮实际发出的外部/LLM 调用清单（配额透明）

| 类型 | 次数 | 说明 |
|---|---|---|
| 真实 LLM 调用 | **1** | `POST /api/llm/test`（30.28s 超时，未产生 token 计费） |
| 真实 LLM 调用（SDK 直连） | **3** | `openai` SDK `max_tokens=1` 探针 × 3 种出口配置，全部 `APITimeoutError`（未到达服务，无计费） |
| 外部 HTTP 探测 | 12 | `/compatible-mode/v1/models` × 3 主机 × 4 出口配置（0 配额） |
| 裸 TCP/TLS 探测 | 20 | 0 配额 |
| 本机后端只读 GET | 5 | `/api/health`、`/api/system/database`、`/api/insights/overview`(404)、`/api/history`(401)、`/openapi.json` |
| 无头浏览器渲染 | 1 | `http://localhost:5173/`，12s 虚拟时间预算 |
| 数据库写入 | **0** | 全部只读连接 |
| 文件修改（仓库内） | **1** | 仅本报告 |
