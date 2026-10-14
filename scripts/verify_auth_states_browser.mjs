/**
 * 第十阶段 P0-1 浏览器实测：四种认证状态的真实渲染行为。
 *
 * 覆盖任务书 §十一「浏览器测试」的四个场景：
 *
 *   正常    —— 真实 UI 登录 → 首页 Dashboard 显示**真实** KPI
 *   未登录  —— 无会话 → 登录页，且不出现任何本地假数据
 *   后端断开 —— 杀掉后端（保留前端）→ 重新加载 → **不进入登录页**、不出现假数据、显示错误与重试
 *   恢复    —— 重启后端 → 点「重试」→ 无需重新登录即回到真实系统
 *
 * 用法：
 *   node scripts/verify_auth_states_browser.mjs <chrome.exe> <python.exe> <projectRoot> \
 *        <backendPort> <frontendPort> <outFile>
 *
 * 零依赖：只用 Node 内置 fetch + WebSocket + child_process（Node >= 22）。
 *
 * ---------------------------------------------------------------------------
 * ⚠️ CDP 五个坑（第九阶段踩过，勿重蹈）：
 * 1. `chrome-headless-shell` 本身就是 headless，再传 `--headless=new` 会启动即退出；
 * 2. `--in-process-gpu` 是陷阱：浏览器活着、attach 也成功，但渲染进程已死，
 *    之后所有 session 命令**静默超时**。唯一可靠判据 = `Runtime.evaluate("1+1") === 2`；
 * 3. 不要连 `/json/list` 的 page target（`Page.enable` 静默无响应）⇒
 *    连 `/json/version` 的 browser 端点 + `Target.attachToTarget({flatten:true})`；
 * 4. WS 断开必须 reject 在途请求，否则 Node 静默 exit 0（看起来像成功）；
 * 5. 单条命令必须自带超时；渲染完成 / 状态切换的断言必须**轮询**。
 * 6. **必须传 `--no-sandbox`，且绝不能 `stdio:"ignore"`**。本机实测：缺 `--no-sandbox` 时
 *    chrome 会先打印 `DevTools listening on ws://...`（看起来已经起来了），随后 GPU 进程
 *    连崩 6 次并以 `FATAL:...GPU process isn't usable. Goodbye.` 自杀（exit=0x80000003）。
 *    表象是「端口连不上 / fetch failed」，与代理问题**完全同形**，极易误诊。
 *    因此 chrome 的 stdout/stderr 必须收进环形缓冲，启动失败时随错误一起抛出。
 * 7. **服务栈必须由本脚本自己拉起**，不能依赖「上一次命令启动的、看起来还在跑的服务」。
 *    实测：在受限执行环境里，被某次命令启动的 `--detach` 子进程会随该次命令结束而消失
 *    （后端日志停在 `GET /api/health 200`，没有任何 shutdown 行）。如果脚本假设服务还在，
 *    就会把「服务早没了」误报成「后端断开场景不成立」—— 又是一个检查器坏了冒充被测对象坏了。
 *
 * ⚠️ 另外三条本脚本专门防的假通过：
 * - **等待条件必须「只有目标态才成立」**。`document.querySelector("aside.sidebar") !== null`
 *   是**恒真**判据（AppShell 永远渲染 MainLayout/Sidebar，连登录页也有）。
 *   所以这里一律用复合条件（如「密码框消失 **且** .hero 出现」）。
 * - **负对照必须与目标路径同构**：这里只杀**后端**、保留前端，
 *   这样页面仍能加载，观察到的才是"应用如何面对后端不可用"，
 *   而不是"整个站点打不开"。
 * - **计数/次数参数必须显式断言**：`waitFor` 的 `tries` 若是字符串，
 *   循环体执行 0 次会把"没等"伪装成"不成立"（假红）。非法即抛。
 */

import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const [chromePath, pythonPath, projectRoot, backendPortArg, frontendPortArg, outFile] =
  process.argv.slice(2);

if (!chromePath || !pythonPath || !projectRoot || !backendPortArg || !frontendPortArg || !outFile) {
  console.error(
    "用法: node verify_auth_states_browser.mjs <chrome.exe> <python.exe> <projectRoot> <backendPort> <frontendPort> <outFile>",
  );
  process.exit(2);
}

const BACKEND_PORT = Number(backendPortArg);
const FRONTEND_PORT = Number(frontendPortArg);
const API_BASE = `http://127.0.0.1:${BACKEND_PORT}`;
const PAGE_URL = `http://localhost:${FRONTEND_PORT}/`;
const SESSION_KEY = "ecom.auth.session";
const RUN_ID = `p10_${Date.now().toString(36)}`;

const checks = [];
const notes = [];

function check(name, passed, detail = "") {
  checks.push({ name, passed: Boolean(passed), detail: String(detail).slice(0, 600) });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
  return Boolean(passed);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 轮询等待。tries 必须是正整数，否则显式抛错（铁律 46）。 */
async function waitFor(label, fn, { tries = 60, gapMs = 500 } = {}) {
  if (!Number.isInteger(tries) || tries <= 0) {
    throw new Error(`waitFor("${label}"): tries 非法 (${JSON.stringify(tries)})`);
  }
  if (!Number.isFinite(gapMs) || gapMs <= 0) {
    throw new Error(`waitFor("${label}"): gapMs 非法 (${JSON.stringify(gapMs)})`);
  }
  let last;
  for (let i = 0; i < tries; i += 1) {
    try {
      last = await fn();
      if (last) return last;
    } catch (err) {
      last = `error: ${err.message}`;
    }
    await sleep(gapMs);
  }
  throw new Error(`waitFor("${label}") 超时（实际轮询 ${tries} 次）：${last}`);
}

// ---------------------------------------------------------------------------
// CDP
// ---------------------------------------------------------------------------

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.network = [];
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject, timer } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        clearTimeout(timer);
        if (msg.error) reject(new Error(`${msg.error.message} (${JSON.stringify(msg.error.data ?? "")})`));
        else resolve(msg.result);
        return;
      }
      if (msg.method === "Network.responseReceived") {
        this.network.push({ url: msg.params.response.url, status: msg.params.response.status });
      }
      if (msg.method === "Network.loadingFailed") {
        this.network.push({ url: msg.params.requestId, failed: msg.params.errorText });
      }
    });
    ws.addEventListener("close", () => {
      // 坑 4：必须 reject 在途请求，否则 Node 静默 exit 0
      for (const { reject, timer } of this.pending.values()) {
        clearTimeout(timer);
        reject(new Error("WebSocket 已关闭，在途命令被拒绝"));
      }
      this.pending.clear();
    });
  }

  send(method, params = {}, sessionId, timeoutMs = 20000) {
    const id = this.nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} 超时（${timeoutMs}ms）`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.ws.send(JSON.stringify(payload));
    });
  }

  async evaluate(sessionId, expression, timeoutMs = 20000) {
    const result = await this.send(
      "Runtime.evaluate",
      { expression, returnByValue: true, awaitPromise: true },
      sessionId,
      timeoutMs,
    );
    if (result.exceptionDetails) {
      throw new Error(`页面脚本异常: ${result.exceptionDetails.text}`);
    }
    return result.result?.value;
  }

  close() {
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
  }
}

async function launchChrome(debugPort) {
  const profile = mkdtempSync(join(tmpdir(), "p10-chrome-"));
  const child = spawn(
    chromePath,
    [
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      // ⚠️ 本机必需。实测：缺了它 chrome 会先打印 "DevTools listening on ws://..."
      // （看起来已经起来了），然后 GPU 进程连续崩溃 6 次并以
      //   FATAL:gpu_data_manager_impl_private.cc:417] GPU process isn't usable. Goodbye.
      // 自杀退出（exit_code=2147483651 / 0x80000003）。
      // 现象是「端口连不上 + fetch failed」，极易被误判成代理或参数写错（铁律 46：
      // 检查器坏掉时会伪装成「被测对象不成立」）。`--disable-gpu` 单独用不够。
      "--no-sandbox",
      "--window-size=1440,1200",
      "about:blank",
    ],
    // 坑 6：绝不能 stdio:"ignore"。否则 chrome 启动即崩时只留一句 "fetch failed"，
    // 真正的 FATAL 行被吞掉 ⇒ 诊断成本从 1 分钟变成 1 小时。
    { stdio: ["ignore", "pipe", "pipe"] },
  );

  const chromeErr = [];
  child.stderr.on("data", (d) => {
    chromeErr.push(d.toString());
    if (chromeErr.length > 200) chromeErr.shift();
  });
  child.stdout.on("data", (d) => {
    chromeErr.push(d.toString());
    if (chromeErr.length > 200) chromeErr.shift();
  });

  const versionUrl = `http://127.0.0.1:${debugPort}/json/version`;
  let info;
  try {
    info = await waitFor(
      "chrome /json/version",
      async () => {
        if (child.exitCode !== null) {
          throw new Error(`chrome 已退出 exit_code=${child.exitCode}`);
        }
        const res = await fetch(versionUrl, { signal: AbortSignal.timeout(1500) });
        if (!res.ok) return null;
        const body = await res.json();
        return body.webSocketDebuggerUrl ? body : null;
      },
      { tries: 60, gapMs: 500 },
    );
  } catch (err) {
    const tail = chromeErr.join("").trim().split("\n").slice(-12).join("\n");
    try {
      child.kill();
    } catch {
      /* ignore */
    }
    throw new Error(
      `${err.message}\n  debugPort=${debugPort}\n  chrome 输出尾部：\n${tail || "(空)"}`,
    );
  }
  return { child, info, profile };
}

async function attach(info) {
  const ws = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("WS 连接超时")), 15000);
    ws.addEventListener("open", () => {
      clearTimeout(timer);
      resolve();
    });
    ws.addEventListener("error", () => {
      clearTimeout(timer);
      reject(new Error("WS 连接失败"));
    });
  });

  const cdp = new Cdp(ws);
  // 坑 2：必须证明渲染进程活着
  const alive = await cdp.send("Browser.getVersion").then(() => true).catch(() => false);
  if (!alive) throw new Error("浏览器命令通道不可用");

  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  await cdp.send("Page.enable", {}, sessionId);
  await cdp.send("Runtime.enable", {}, sessionId);
  await cdp.send("Network.enable", {}, sessionId);

  const liveness = await cdp.evaluate(sessionId, "1 + 1");
  if (liveness !== 2) throw new Error(`渲染进程不健康：1+1 = ${liveness}（坑 2）`);

  return { cdp, sessionId };
}

/** 导航并等待 document.readyState === "complete" */
async function goto(cdp, sessionId, url) {
  await cdp.send("Page.navigate", { url }, sessionId);
  await waitFor(
    `readyState @ ${url}`,
    async () => (await cdp.evaluate(sessionId, "document.readyState")) === "complete",
    { tries: 60, gapMs: 300 },
  );
}

// ---------------------------------------------------------------------------
// 页面状态判据（全部是复合条件：只有目标态才成立）
// ---------------------------------------------------------------------------

const PROBE = `(() => {
  const text = document.body ? document.body.innerText : "";
  const pwd = document.querySelectorAll('input[type="password"]').length;
  const hero = document.querySelectorAll(".hero").length;
  const unavailable = document.querySelectorAll('[data-testid="backend-unavailable"]').length;
  const kpiValues = Array.from(document.querySelectorAll(".kpi-card__value")).map(n => n.textContent.trim());
  const retryBtn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "重试");
  // 图表：ECharts 渲染进 canvas，读不到文字，但可以证明「真的画出来了」而不是空容器。
  // 判据 = 有尺寸 + 有非透明像素 + 有多个不同颜色（纯色块 / 全空白都不算图）。
  const charts = Array.from(document.querySelectorAll(".chart-card__body")).map(el => {
    const cv = el.querySelector("canvas");
    const w = cv ? cv.width : 0;
    const h = cv ? cv.height : 0;
    let painted = 0;
    const colors = new Set();
    if (cv && w > 0 && h > 0) {
      try {
        const ctx = cv.getContext("2d");
        const d = ctx.getImageData(0, 0, Math.min(w, 240), Math.min(h, 240)).data;
        for (let i = 0; i < d.length; i += 4) {
          if (d[i + 3] > 0) painted += 1;
          if (colors.size < 512) colors.add(d[i] + "," + d[i + 1] + "," + d[i + 2] + "," + d[i + 3]);
        }
      } catch (e) { painted = -1; }
    }
    return { label: el.getAttribute("aria-label") || "", w, h, painted, colors: colors.size };
  });
  // 图表副标题里带着接口真实值（"近 12 个月 · 数据截至 2026-09-12"），是可读 DOM 文本，
  // 用来把「图表喂的是真数据」钉死在 DOM 上。
  const subtitles = Array.from(document.querySelectorAll(".section-sub")).map(n => n.textContent.trim());
  let session = null;
  try { session = window.localStorage.getItem(${JSON.stringify(SESSION_KEY)}); } catch (e) { session = "ERR"; }
  return JSON.stringify({ text, pwd, hero, unavailable, kpiValues, hasRetry: Boolean(retryBtn), charts, subtitles, session });
})()`;

async function probe(cdp, sessionId) {
  const raw = await cdp.evaluate(sessionId, PROBE);
  return JSON.parse(raw);
}

/** 已认证：密码框消失 **且** Hero 出现（单独任一条都会在别的页面上成立） */
async function waitAuthenticated(cdp, sessionId, label) {
  return waitFor(label, async () => {
    const state = await probe(cdp, sessionId);
    return state.pwd === 0 && state.hero > 0 ? state : null;
  });
}

async function waitLoginPage(cdp, sessionId, label) {
  return waitFor(label, async () => {
    const state = await probe(cdp, sessionId);
    return state.pwd > 0 ? state : null;
  });
}

async function waitBackendUnavailable(cdp, sessionId, label) {
  return waitFor(label, async () => {
    const state = await probe(cdp, sessionId);
    return state.unavailable > 0 && state.hasRetry ? state : null;
  });
}

// ---------------------------------------------------------------------------
// 本地假数据指纹（值级，不扫描裸标记 —— 铁律 49）
// ---------------------------------------------------------------------------

const FAKE_FINGERPRINTS = [
  "7,662,921",
  "1,284",
  "352.6",
  "+12.4%",
  "-1.8%",
  "星耀",
  "极光",
  "轻云",
  "灵犀",
  "远航",
];

function fakeHits(text) {
  return FAKE_FINGERPRINTS.filter((token) => text.includes(token));
}

// ---------------------------------------------------------------------------
// HTTP 辅助（绕过代理，铁律 4）
// ---------------------------------------------------------------------------

async function api(path, { method = "GET", body, token, timeoutMs = 30000 } = {}) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  return { status: res.status, json: text ? JSON.parse(text) : null };
}

// ---------------------------------------------------------------------------
// 进程辅助
// ---------------------------------------------------------------------------

function listenerPid(port) {
  try {
    const out = execFileSync("netstat", ["-ano"], { encoding: "utf8", maxBuffer: 8 << 20 });
    for (const line of out.split(/\r?\n/)) {
      const parts = line.trim().split(/\s+/);
      if (parts.length >= 5 && parts[0].toUpperCase() === "TCP" && parts[3].toUpperCase() === "LISTENING") {
        if (parts[1].endsWith(`:${port}`)) return Number(parts[4]);
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}

/**
 * 杀掉一棵进程树，并**返回它到底杀了哪些 PID**。
 *
 * 为什么必须返回：这是「后端断开」场景的负对照（铁律 48：负对照必须与目标路径同构）。
 * 断言「前端仍在监听」如果只是事后看一眼端口，就无法区分下面两种情况：
 *   a) 我们确实只杀了后端，前端是被测对象的正常表现；
 *   b) 我们手滑把前端一起杀了，然后拿一个假绿当结论。
 * 所以这里把 taskkill 的 stdout 收下来，显式断言「被杀名单里没有前端的监听进程」。
 */
function killTree(pid) {
  let raw = "";
  try {
    raw = execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (err) {
    raw = String(err.stdout ?? "") + String(err.stderr ?? "") + `\n${err.message}`;
  }
  const killed = [];
  for (const m of raw.matchAll(/PID\s+(\d+)/g)) killed.push(Number(m[1]));
  killed.push(pid);
  return { killed: [...new Set(killed)].sort((a, b) => a - b), raw: raw.trim() };
}

function startDev(args) {
  const out = execFileSync(pythonPath, [join(projectRoot, "scripts", "start_dev.py"), ...args], {
    cwd: projectRoot,
    encoding: "utf8",
    timeout: 240000,
  });
  return out;
}

function stopDev() {
  try {
    return execFileSync(pythonPath, [join(projectRoot, "scripts", "stop_dev.py")], {
      cwd: projectRoot,
      encoding: "utf8",
      timeout: 120000,
    });
  } catch (err) {
    return `${err.stdout ?? ""}${err.stderr ?? ""}${err.message}`;
  }
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

async function main() {
  const startedAt = new Date().toISOString();
  const debugPort = 9200 + (process.pid % 300);
  let chrome;
  let cdp;
  let sessionId;

  const summary = { run_id: RUN_ID, started_at: startedAt, backend_port: BACKEND_PORT, frontend_port: FRONTEND_PORT };

  try {
    // ---------- 准备：真实注册一个本次运行专属的用户 ----------
    const username = RUN_ID;
    const password = "S3cret!pass";
    const reg = await api("/api/auth/register", {
      method: "POST",
      body: { username, email: `${username}@example.com`, password },
    });
    check("准备：注册本次运行专属用户（真实 POST /api/auth/register）", reg.status === 201, `HTTP ${reg.status}`);

    // 真实 API 侧的 ground truth（用于和 DOM 对账）
    const login = await api("/api/auth/login", { method: "POST", body: { username, password } });
    check("准备：真实登录拿到 access_token", login.status === 200 && !!login.json?.access_token, `HTTP ${login.status}`);
    const overview = await api("/api/insights/overview", { token: login.json.access_token });
    check("准备：真实 overview 聚合可用", overview.status === 200, `HTTP ${overview.status}`);
    const kpis = overview.json?.kpis ?? {};
    const trend = overview.json?.sales_trend ?? [];
    const categories = overview.json?.category_distribution ?? [];
    summary.api_ground_truth = {
      as_of: overview.json?.as_of,
      month_sales: kpis.month_sales?.value,
      month_orders: kpis.month_orders?.value,
      users_total: kpis.users_total?.value,
      avg_order_value: kpis.avg_order_value?.value,
      trend_len: trend.length,
      trend_first: trend[0]?.month,
      trend_last: trend[trend.length - 1]?.month,
      category_len: categories.length,
      top_product_name: overview.json?.top_products?.[0]?.product_name,
    };

    chrome = await launchChrome(debugPort);
    ({ cdp, sessionId } = await attach(chrome.info));

    // ---------- 场景 1：未登录 ----------
    await goto(cdp, sessionId, PAGE_URL);
    const anon = await waitLoginPage(cdp, sessionId, "未登录态：登录页出现");
    check("未登录：渲染登录页（真实密码输入框）", anon.pwd > 0, `pwd inputs=${anon.pwd}`);
    check("未登录：不渲染受保护内容（无 Hero / 无 KPI）", anon.hero === 0 && anon.kpiValues.length === 0, `hero=${anon.hero} kpi=${anon.kpiValues.length}`);
    check("未登录：无本地假数据指纹", fakeHits(anon.text).length === 0, fakeHits(anon.text).join(","));
    check("未登录：localStorage 无会话", !anon.session, String(anon.session));

    // ---------- 场景 2：正常（真实 UI 登录） ----------
    const creds = JSON.stringify({ username, password });
    const loginOutcome = await cdp.evaluate(
      sessionId,
      `(async () => {
        const inputs = document.querySelectorAll("input");
        const user = document.querySelector('input[type="text"]');
        const pwd = document.querySelector('input[type="password"]');
        if (!user || !pwd) return "missing-inputs";
        const setValue = (el, v) => {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
          setter.call(el, v);
          el.dispatchEvent(new Event("input", { bubbles: true }));
        };
        const { username, password } = ${creds};
        setValue(user, username);
        setValue(pwd, password);
        const form = pwd.closest("form");
        if (!form) return "missing-form";
        form.querySelector('button[type="submit"]').click();
        return "submitted:" + inputs.length;
      })()`,
    );
    check("正常：在真实 UI 上填表并提交登录", String(loginOutcome).startsWith("submitted:"), String(loginOutcome));

    const authed = await waitAuthenticated(cdp, sessionId, "登录成功后进入真实系统");
    check("正常：登录后进入真实系统（密码框消失 且 Hero 出现）", authed.pwd === 0 && authed.hero > 0, `pwd=${authed.pwd} hero=${authed.hero}`);
    check("正常：会话已写入 localStorage", Boolean(authed.session), "session present");

    // 首页真实 KPI 对账（值级：把 DOM 数字去掉分隔符后与 API 原值比对）
    const kpiDom = await waitFor(
      "首页 KPI 上屏",
      async () => {
        const state = await probe(cdp, sessionId);
        return state.kpiValues.length >= 4 ? state : null;
      },
      { tries: 60, gapMs: 500 },
    );
    const normalized = kpiDom.kpiValues.map((v) => v.replace(/[^0-9.]/g, ""));
    const expectSales = String(kpis.month_sales.value);
    const expectOrders = String(Math.round(kpis.month_orders.value));
    const expectUsers = String(Math.round(kpis.users_total.value));
    const expectAov = String(kpis.avg_order_value.value);
    summary.dom_kpi = kpiDom.kpiValues;
    check("正常：DOM KPI 含真实本月销售额", normalized.some((v) => v === expectSales || v === expectSales.replace(/\.00$/, "")), `${kpiDom.kpiValues.join(" | ")} vs API ${expectSales}`);
    check("正常：DOM KPI 含真实订单量", normalized.includes(expectOrders), `API ${expectOrders}`);
    check("正常：DOM KPI 含真实注册用户数", normalized.includes(expectUsers), `API ${expectUsers}`);
    check("正常：DOM KPI 含真实客单价", normalized.includes(expectAov), `API ${expectAov}`);
    const gt = summary.api_ground_truth;
    check("正常：页面无本地假数据指纹", fakeHits(kpiDom.text).length === 0, fakeHits(kpiDom.text).join(","));

    // ---- §十二「1 个真实图表」：Dashboard 上的图必须真画了，且喂的是接口真值 ----
    const chartCards = kpiDom.charts ?? [];
    summary.dashboard_charts = chartCards;
    summary.dashboard_subtitles = kpiDom.subtitles ?? [];
    check("图表：Dashboard 渲染出 ≥2 张图表卡片", chartCards.length >= 2, `cards=${chartCards.length}`);
    check(
      "图表：卡片标识为「销售趋势」「分类销售」",
      chartCards.some((c) => c.label === "销售趋势") && chartCards.some((c) => c.label === "分类销售"),
      chartCards.map((c) => c.label || "(无 aria-label)").join(" | "),
    );
    // 「真的画了」= 有尺寸 + 有非透明像素 + 有多种颜色；纯色块 / 空白容器都不算图
    const painted = chartCards.filter((c) => c.w > 0 && c.h > 0 && c.painted > 0 && c.colors > 2);
    check(
      "图表：每张图都实际绘制（有尺寸 / 有像素 / 多色，不是空容器）",
      chartCards.length >= 2 && painted.length === chartCards.length,
      chartCards.map((c) => `${c.label}:${c.w}x${c.h} px=${c.painted} colors=${c.colors}`).join(" | "),
    );
    // 副标题把「图表喂的是接口真值」钉在可读 DOM 文本上（不是 canvas 像素）
    check(
      "图表：副标题带出接口真实趋势长度（近 N 个月）",
      (kpiDom.subtitles ?? []).some((s) => s.includes(`近 ${gt.trend_len} 个月`)),
      `${(kpiDom.subtitles ?? []).join(" | ")} vs API trend_len=${gt.trend_len}`,
    );
    check(
      "图表：副标题带出接口真实数据截止日（as_of）",
      (kpiDom.subtitles ?? []).some((s) => s.includes(`数据截至 ${gt.as_of}`)),
      `vs API as_of=${gt.as_of}`,
    );
    check(
      "图表：副标题带出接口真实类目数（叶子类目 Top N）",
      (kpiDom.subtitles ?? []).some((s) => s.includes(`叶子类目 Top ${gt.category_len}`)),
      `vs API category_len=${gt.category_len}`,
    );

    // ---------- 场景 3：后端断开（同构负对照：只杀后端，保留前端） ----------
    const backendPid = listenerPid(BACKEND_PORT);
    const frontendPidBefore = listenerPid(FRONTEND_PORT);
    check("断开：定位到后端监听进程 PID", Number.isInteger(backendPid), `PID ${backendPid}`);
    check("断开：定位到前端监听进程 PID（负对照基准）", Number.isInteger(frontendPidBefore), `PID ${frontendPidBefore}`);
    let killInfo = { killed: [], raw: "" };
    if (backendPid) killInfo = killTree(backendPid);
    summary.backend_pid = backendPid;
    summary.frontend_pid_before = frontendPidBefore;
    summary.kill_tree_killed_pids = killInfo.killed;
    summary.kill_tree_raw = killInfo.raw;
    // 自证式负对照：被杀名单里绝不能出现前端的监听进程
    check(
      "断开：杀后端时未误伤前端监听进程（自证式负对照）",
      !killInfo.killed.includes(frontendPidBefore),
      `killed=[${killInfo.killed.join(",")}] frontend=${frontendPidBefore}`,
    );
    await waitFor(
      "后端端口释放",
      async () => listenerPid(BACKEND_PORT) === null,
      { tries: 30, gapMs: 500 },
    );
    check("断开：后端端口已释放", listenerPid(BACKEND_PORT) === null, `port ${BACKEND_PORT}`);
    const frontendPidAfter = listenerPid(FRONTEND_PORT);
    summary.frontend_pid_after = frontendPidAfter;
    check(
      "断开：前端仍在监听（负对照与目标路径同构）",
      frontendPidAfter !== null,
      `port ${FRONTEND_PORT} before=${frontendPidBefore} after=${frontendPidAfter}`,
    );
    check(
      "断开：前端进程未被替换（同一 PID，不是重启了一个新的）",
      frontendPidAfter !== null && frontendPidAfter === frontendPidBefore,
      `before=${frontendPidBefore} after=${frontendPidAfter}`,
    );

    cdp.network.length = 0;
    await goto(cdp, sessionId, PAGE_URL);
    const down = await waitBackendUnavailable(cdp, sessionId, "后端断开后显示不可用页");
    check("断开：显示「后端服务不可用」", down.text.includes("后端服务不可用"), down.text.slice(0, 80));
    check("断开：给出「请检查后端是否启动」", down.text.includes("请检查后端是否启动"), "");
    check("断开：提供重试按钮", down.hasRetry, "");
    check("断开：**不进入登录页**（无密码输入框）", down.pwd === 0, `pwd inputs=${down.pwd}`);
    check("断开：不渲染受保护内容（无 KPI）", down.kpiValues.length === 0, `kpi=${down.kpiValues.length}`);
    check("断开：不出现本地假数据指纹", fakeHits(down.text).length === 0, fakeHits(down.text).join(","));
    check("断开：会话被保留（未把「服务挂了」记成「用户登出」）", Boolean(down.session), String(down.session).slice(0, 40));

    const meFailures = cdp.network.filter((n) => n.failed);
    summary.network_failures_while_down = meFailures.slice(0, 6);
    check("断开：网络层确实观察到失败请求（不是渲染问题）", meFailures.length > 0, `failed=${meFailures.length}`);

    // ---------- 场景 4：恢复 ----------
    const restartOut = startDev(["--only", "backend", "--detach", "--backend-port", String(BACKEND_PORT)]);
    summary.restart_output_tail = restartOut.split("\n").slice(-6).join(" | ");
    check("恢复：后端通过正式脚本重启成功", restartOut.includes("Health  : OK"), "Health OK");
    const healthy = await api("/api/health");
    check("恢复：/api/health 返回 200", healthy.status === 200, `HTTP ${healthy.status}`);

    // 点「重试」而不是刷新：证明"无需重新登录"
    await cdp.evaluate(
      sessionId,
      `(() => {
        const btn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.trim() === "重试");
        if (!btn) return "no-retry";
        btn.click();
        return "clicked";
      })()`,
    );
    const recovered = await waitAuthenticated(cdp, sessionId, "点击重试后回到真实系统");
    check("恢复：点击「重试」后回到真实系统（未重新登录）", recovered.pwd === 0 && recovered.hero > 0, `pwd=${recovered.pwd} hero=${recovered.hero}`);
    const recoveredKpi = await waitFor(
      "恢复后 KPI 重新上屏",
      async () => {
        const state = await probe(cdp, sessionId);
        return state.kpiValues.length >= 4 ? state : null;
      },
      { tries: 60, gapMs: 500 },
    );
    const recoveredNormalized = recoveredKpi.kpiValues.map((v) => v.replace(/[^0-9.]/g, ""));
    check("恢复：KPI 重新显示真实值（未回退假数据）", recoveredNormalized.includes(expectOrders), `${recoveredKpi.kpiValues.join(" | ")}`);
    check("恢复：页面无本地假数据指纹", fakeHits(recoveredKpi.text).length === 0, fakeHits(recoveredKpi.text).join(","));

    // ---------- 场景 5：§十二 真实业务闭环（Agent → SQL → History） ----------
    // 这一轮走 API 层：Agent 图、SQL 生成、SQLite 执行、History 落库都是真实链路，
    // 用确定性最高的业务问题（注册用户总数）以便和 /api/insights/overview 三方对账。
    const QUESTION = "注册用户总数是多少？";
    const token = login.json.access_token;
    const analyze = await api("/api/agent/analyze", {
      method: "POST",
      token,
      body: { question: QUESTION },
      timeoutMs: 180000,
    });
    check("业务：POST /api/agent/analyze 返回 200", analyze.status === 200, `HTTP ${analyze.status}`);
    const ar = analyze.json?.result ?? {};
    summary.business = {
      question: QUESTION,
      generated_sql: ar.generated_sql ?? "",
      success: ar.success,
      row_count: ar.execution_result?.row_count ?? null,
      rows: ar.execution_result?.rows ?? [],
      total_time_ms: ar.total_time_ms ?? null,
      execute_count: ar.execute_count ?? null,
      trace_nodes: (ar.trace ?? []).map((t) => t.node),
      final_error: ar.final_error ?? "",
    };
    check(
      "业务：Agent 判定成功（success=true 且无 final_error）",
      analyze.json?.success === true && ar.success === true && !ar.final_error,
      `error=${analyze.json?.error ?? ""} final_error=${ar.final_error ?? ""}`,
    );
    check(
      "业务：生成了真实 SQL（命中 users 且是聚合查询）",
      /users/i.test(ar.generated_sql ?? "") && /count\s*\(\s*\*\s*\)/i.test(ar.generated_sql ?? ""),
      (ar.generated_sql ?? "").slice(0, 140),
    );
    check(
      "业务：SQL 真的在 SQLite 上执行并返回结果行",
      (ar.execution_result?.row_count ?? 0) > 0,
      `row_count=${ar.execution_result?.row_count} execute_count=${ar.execute_count}`,
    );
    const flatRows = (ar.execution_result?.rows ?? []).flat().map((v) => Number(v));
    check(
      "业务：查询结果与 /api/insights/overview 的用户总数一致（三方对账）",
      flatRows.includes(Number(gt.users_total)),
      `rows=${JSON.stringify(ar.execution_result?.rows ?? [])} vs API users_total=${gt.users_total}`,
    );
    check(
      "业务：Agent 走完了编排节点（trace 非空）",
      (ar.trace ?? []).length > 0,
      `nodes=${(ar.trace ?? []).map((t) => t.node).join(" → ")}`,
    );

    // History：同一 token 拉取，必须能看到刚才那一条
    const hist = await api("/api/history?page=1&page_size=20", { token });
    check("业务：GET /api/history 返回 200", hist.status === 200, `HTTP ${hist.status}`);
    const histItems = hist.json?.items ?? [];
    const mine = histItems.find((it) => it.question === QUESTION) ?? null;
    summary.business.history_total = hist.json?.total ?? null;
    summary.business.history_item = mine
      ? { id: mine.id, question: mine.question, sql: mine.sql, success: mine.success, row_count: mine.row_count, total_time_ms: mine.total_time_ms, created_at: mine.created_at }
      : null;
    check("业务：History 中出现刚才那次真实查询", mine !== null, `total=${hist.json?.total} 最近=${histItems[0]?.question ?? "(空)"}`);
    check(
      "业务：History 记录的 SQL 与本次生成的 SQL 逐字一致",
      mine !== null && String(mine.sql ?? "").trim() === String(ar.generated_sql ?? "").trim(),
      mine ? `id=${mine.id} sql=${String(mine.sql).slice(0, 100)}` : "(未找到)",
    );
    check(
      "业务：History 记录带真实耗时（> 0ms）",
      mine !== null && Number(mine.total_time_ms) > 0,
      `total_time_ms=${mine?.total_time_ms}`,
    );
    check(
      "业务：History 记录带真实行数",
      mine !== null && Number(mine.row_count) >= 1,
      `row_count=${mine?.row_count}`,
    );
  } catch (err) {
    check("执行过程中未抛异常", false, err.message);
    notes.push(`异常：${err.stack ?? err.message}`);
  } finally {
    cdp?.close();
    chrome?.child?.kill();
    // 服务栈是本脚本自己拉起来的，跑完自己收掉，不留孤儿进程
    BOOTSTRAP.stop_after = stopDev();
  }

  const passed = checks.filter((c) => c.passed).length;
  const result = {
    ...summary,
    bootstrap: BOOTSTRAP,
    finished_at: new Date().toISOString(),
    total: checks.length,
    passed,
    failed: checks.length - passed,
    verdict: checks.length > 0 && passed === checks.length ? "ALL_PASS" : "HAS_FAILURE",
    checks,
    notes,
  };

  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, JSON.stringify(result, null, 2), "utf8");
  console.log(`\n===== ${result.verdict}  ${passed}/${checks.length} =====`);
  console.log(`证据：${outFile}`);
  process.exit(result.verdict === "ALL_PASS" ? 0 : 1);
}

// ---------------------------------------------------------------------------
// 第 0 步：由本脚本**自己**拉起正式服务栈（见文件头「坑 7」）
//
// 放在 main() 之前而不是里面，是因为 main() 内部会 process.exit()；
// 这样启动阶段的检查同样进入 checks[]，和其余断言一起被计入 verdict。
// ---------------------------------------------------------------------------
const BOOTSTRAP = { stop_before: "", startup_output: "", stop_after: "" };

try {
  BOOTSTRAP.stop_before = stopDev();
  BOOTSTRAP.startup_output = startDev([
    "--detach",
    "--backend-port",
    String(BACKEND_PORT),
    "--frontend-port",
    String(FRONTEND_PORT),
  ]);
  const line = (needle) =>
    BOOTSTRAP.startup_output.split("\n").find((l) => l.includes(needle))?.trim() ?? "";
  check(
    "启动：正式脚本 start_dev.py 冷启动成功并自报 Health OK",
    BOOTSTRAP.startup_output.includes("Health  : OK"),
    line("Health"),
  );
  check(
    "启动：输出包含 Backend 访问地址",
    BOOTSTRAP.startup_output.includes(`http://127.0.0.1:${BACKEND_PORT}`),
    line("Backend :"),
  );
  check(
    "启动：输出包含 Frontend 访问地址",
    BOOTSTRAP.startup_output.includes(`http://localhost:${FRONTEND_PORT}`),
    line("Frontend:"),
  );
  const bootHealth = await api("/api/health");
  check("启动：/api/health 返回 200", bootHealth.status === 200, `HTTP ${bootHealth.status}`);
} catch (err) {
  check("启动：正式脚本 start_dev.py 冷启动成功并自报 Health OK", false, err.message);
}

await main();
