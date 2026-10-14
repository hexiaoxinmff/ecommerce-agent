import pptxgen from "pptxgenjs";
import { addSingleLineToken } from "./pptx-text-guards.mjs";
import { writeFileSync } from "node:fs";

/* =========================== Design tokens =========================== */
const W = 13.333, H = 7.5;
const ML = 0.95, MR = 0.95;             // page margins
const CW = W - ML - MR;                  // content width
const BG     = "F7F3EA";                 // warm milky white
const CARD   = "FBF9F1";                 // surface card
const CARD2  = "F1EBDD";                 // slightly deeper band / highlight
const INK    = "3A352F";                 // primary deep warm gray
const MUTED  = "8C8373";                 // secondary gray
const ACCENT = "74543A";                 // single low-sat deep walnut brown
const ACCENT_D = "573E26";              // darker accent for emphasis
const HAIR   = "DDD3C2";                 // hairlines
const CN     = "Microsoft YaHei";        // Chinese font
const LAT    = "Aptos";                  // Latin/numeric font

const pp = new pptxgen();
pp.defineLayout({ name: "FINAL", width: W, height: H });
pp.layout = "FINAL";

const deckName = "基于 Text2SQL 的电商智能数据分析 Agent";

const OUT_DIR = "F:/task36_final_presentation";
const OUT_PPTX = `${OUT_DIR}/基于Text2SQL的电商智能数据分析Agent_项目汇报.pptx`;

/* =========================== Primitives =========================== */
function bg(slide, pageNo) {
  slide.background = { color: BG };
  slide.addShape("line", {
    x: ML, y: H - 0.52, w: CW, h: 0, line: { color: HAIR, width: 0.75 },
  });
  slide.addText(deckName, {
    x: ML, y: H - 0.48, w: 8.0, h: 0.3,
    fontFace: CN, fontSize: 8.5, color: MUTED, align: "left", valign: "middle",
  });
  addSingleLineToken(slide, `${String(pageNo).padStart(2, "0")} / 12`, {
    x: W - MR - 1.2, y: H - 0.48, w: 1.0, h: 0.3,
    fontFace: CN, fontSize: 8.5, color: MUTED, align: "right",
  });
}

function titleBlock(slide, t, sub) {
  slide.addText(t, {
    x: ML, y: 0.52, w: CW, h: 0.62,
    fontFace: CN, fontSize: 27, bold: true, color: INK, align: "left", valign: "middle",
  });
  if (sub) {
    slide.addText(sub, {
      x: ML, y: 1.16, w: CW, h: 0.34,
      fontFace: CN, fontSize: 13.5, color: MUTED, align: "left", valign: "middle",
    });
  }
  slide.addShape("line", { x: ML, y: 1.62, w: 0.55, h: 0, line: { color: ACCENT, width: 2 } });
}

function card(slide, x, y, w, h, fill = CARD, lineColor = HAIR) {
  slide.addShape("roundRect", {
    x, y, w, h, fill: { color: fill },
    rectRadius: 0.05,
    line: { color: lineColor, width: 0.75 },
  });
}

function token(slide, value, x, y, w, h, opts) {
  return addSingleLineToken(slide, value, {
    x, y, w, h,
    fontFace: opts.fontFace || LAT,
    fontSize: opts.size ?? 30,
    bold: opts.bold ?? true,
    color: opts.color || INK,
    align: opts.align || "center",
    valign: "middle",
    margin: 0, wrap: false,
  });
}

function label(slide, text, x, y, w, h, opts = {}) {
  slide.addText(text, {
    x, y, w, h,
    fontFace: CN, fontSize: opts.size ?? 13,
    color: opts.color ?? MUTED,
    bold: opts.bold ?? false,
    align: opts.align ?? "left",
    valign: opts.valign ?? "middle",
    margin: 0, breakLine: false,
  });
}

function body(slide, arr, x, y, w, h) {
  slide.addText(arr, {
    x, y, w, h,
    fontFace: CN, fontSize: 12, color: INK, valign: "top", lineSpacingMultiple: 1.15,
    breakLine: false,
  });
}

function footnote(slide, text, y = H - 0.86) {
  slide.addText(text, {
    x: ML, y, w: CW, h: 0.3,
    fontFace: CN, fontSize: 9, color: MUTED, align: "left", valign: "middle",
  });
}

function flowRow(slide, boxes, x, y, w, h, opt = {}) {
  const n = boxes.length;
  const gap = opt.gap ?? 0.40;
  const bw = (w - gap * (n - 1)) / n;
  const arrowColor = opt.arrowColor ?? "C9BCA5";
  for (let i = 0; i < n; i++) {
    const bx = x + i * (bw + gap);
    const isAccent = opt.accentIndex != null && i === opt.accentIndex;
    card(slide, bx, y, bw, h, isAccent ? CARD2 : CARD, HAIR);
    slide.addText(boxes[i].k, {
      x: bx, y: y + 0.08, w: bw, h: 0.5,
      fontFace: CN, fontSize: opt.keySize ?? 12.5, bold: true,
      color: isAccent ? ACCENT_D : INK, align: "center", valign: "middle", margin: 0, breakLine: false,
    });
    slide.addText(boxes[i].label, {
      x: bx, y: y + 0.56, w: bw, h: h - 0.7,
      fontFace: CN, fontSize: opt.labelSize ?? 10.5, color: MUTED,
      align: "center", valign: "top", margin: 0, breakLine: false,
    });
    if (i < n - 1) {
      const ax = bx + bw + gap / 2;
      slide.addShape("line", {
        x: ax - gap / 4, y: y + h / 2, w: gap / 2, h: 0,
        line: { color: arrowColor, width: 1.6 },
      });
      slide.addShape("chevron", {
        x: ax - 0.06, y: y + h / 2 - 0.09, w: 0.16, h: 0.18,
        fill: { color: arrowColor }, line: { type: "none" },
      });
    }
  }
}

/* =========================== Slide 1 · Cover =========================== */
function s1() {
  const s = pp.addSlide();
  bg(s, 1);
  label(s, "项目答辩汇报 · DATA INTELLIGENCE", ML, 1.05, CW, 0.3,
    { size: 11, color: ACCENT, bold: true, align: "center" });
  s.addText("基于 Text2SQL 的电商智能数据分析 Agent", {
    x: ML, y: 2.15, w: CW, h: 0.9,
    fontFace: CN, fontSize: 33, bold: true, color: INK, align: "center", valign: "middle",
  });
  s.addText("自然语言驱动的数据查询与分析", {
    x: ML + 0.6, y: 3.15, w: CW - 1.2, h: 0.42,
    fontFace: CN, fontSize: 17, color: MUTED, align: "center", valign: "middle",
  });
  s.addShape("line", { x: W / 2 - 0.5, y: 3.78, w: 1.0, h: 0, line: { color: ACCENT, width: 2 } });
  body(s, [
    { text: "面向结构化电商库的只读自然语言查询 → Schema 理解 → SQL 生成 → 安全执行 → 图表与结论", options: { color: INK, fontSize: 13 } },
  ], ML + 0.6, 4.15, CW - 1.2, 0.4);
  label(s, "学生 · 专业 · 学校（信息以实际填写为准）", ML + 0.6, 4.75, CW - 1.2, 0.3,
    { size: 10.5, color: MUTED, align: "center" });
}

/* =========================== Slide 2 · 从问题到洞察 =========================== */
function s2() {
  const s = pp.addSlide();
  bg(s, 2);
  titleBlock(s, "从问题到洞察", "一条完整的端到端链路");
  flowRow(s, [
    { k: "自然语言", label: "问题输入" },
    { k: "Schema 理解", label: "结构映射" },
    { k: "SQL 生成", label: "草稿生成" },
    { k: "安全校验", label: "只读护栏" },
    { k: "执行 / 自修复", label: "结果验证" },
    { k: "图表与结论", label: "分析输出" },
  ], ML, 2.15, CW, 1.6, { keySize: 13.5, labelSize: 10 });
  body(s, [
    { text: "一个自然语言问题，经过理解、生成、校验与自修复后，输出可执行的分析结果。", options: { color: INK, fontSize: 13.5, bold: true } },
  ], ML, 4.7, CW, 0.4);
  footnote(s, "数据来源：Task35 确定的系统流程叙事。");
}

/* =========================== Slide 3 · Agent 核心架构 =========================== */
function s3() {
  const s = pp.addSlide();
  bg(s, 3);
  titleBlock(s, "Agent 核心架构", "分层组件 · 单点职责");
  const mods = [
    { k: "Schema Linking", lab: "结构理解" },
    { k: "Few-shot", lab: "示例检索" },
    { k: "SQL Generation", lab: "草稿生成" },
    { k: "SQL Safety", lab: "安全护栏" },
    { k: "SQL Execute", lab: "只读执行" },
    { k: "Repair", lab: "受控修复" },
    { k: "Result", lab: "结果输出" },
  ];
  const gap = 0.28, n = mods.length;
  const bw = (CW - gap * (n - 1)) / n;
  const y = 2.2, h = 1.9;
  mods.forEach((m, i) => {
    const bx = ML + i * (bw + gap);
    card(s, bx, y, bw, h, i === 5 ? CARD2 : CARD, HAIR);
    s.addText(m.lab, {
      x: bx, y: y + 0.25, w: bw, h: 0.4,
      fontFace: CN, fontSize: 10.5, color: MUTED, align: "center", valign: "middle", margin: 0, breakLine: false,
    });
    s.addText(m.k, {
      x: bx, y: y + 0.7, w: bw, h: 0.7, fontFace: CN, fontSize: 11.5, bold: true,
      color: i === 5 ? ACCENT_D : INK, align: "center", valign: "middle", margin: 0, breakLine: false,
    });
  });
  body(s, [
    { text: "模块间分层解耦，业务规则以常量注入，不改写整条链路。", options: { color: INK, fontSize: 13.5, bold: true } },
  ], ML, 4.9, CW, 0.4);
  footnote(s, "数据来源：Task35 核心架构叙事。");
}

/* =========================== Slide 4 · Text2SQL 核心链路 =========================== */
function s4() {
  const s = pp.addSlide();
  bg(s, 4);
  titleBlock(s, "Text2SQL 核心链路", "从解析到受控自修复");
  flowRow(s, [
    { k: "问题解析", label: "意图提取" },
    { k: "Schema Link", label: "列 · 表 · 聚合" },
    { k: "SQL Generate", label: "草稿生成" },
    { k: "Safety", label: "只读校验" },
    { k: "Execute", label: "结果执行" },
    { k: "Repair", label: "受控修复" },
  ], ML, 2.2, CW, 1.5, { keySize: 13, labelSize: 10.5 });
  card(s, ML, 4.35, CW, 1.0, CARD, ACCENT);
  body(s, [
    { text: "错误不是直接失败，而是进入受控修复链路。", options: { color: ACCENT_D, fontSize: 15, bold: true } },
  ], ML + 0.35, 4.35, CW - 0.7, 1.0);
  footnote(s, "数据来源：Task35 确定的 Text2SQL 链路叙事。");
}

/* =========================== Slide 5 · 安全与可靠性 =========================== */
function s5() {
  const s = pp.addSlide();
  bg(s, 5);
  titleBlock(s, "安全与可靠性", "只读执行 · 越界拦截 · 受控修复");
  const rows = [
    { t: "SELECT / WITH only", d: "仅允许只读查询语句" },
    { t: "Read-only", d: "数据库连接强制只读" },
    { t: "Multi-statement blocked", d: "阻断多语句注入" },
    { t: "PRAGMA blocked", d: "禁止系统级指令外联" },
    { t: "Result limit", d: "限制返回结果规模" },
    { t: "Repair ≤ 1", d: "修复限定受控次数" },
  ];
  const gap = 0.35, n = rows.length;
  const bw = (CW - gap) / 2;
  rows.forEach((r, i) => {
    const cx = i % 2, cy = Math.floor(i / 2);
    const x = ML + cx * (bw + gap);
    const y = 2.1 + cy * 1.15;
    const accent = r.t.startsWith("Repair");
    card(s, x, y, bw, 1.0, accent ? CARD2 : CARD, HAIR);
    s.addText(r.t, {
      x: x + 0.28, y: y + 0.12, w: bw - 0.56, h: 0.4,
      fontFace: LAT, fontSize: 14, bold: true, color: accent ? ACCENT_D : INK,
      align: "left", valign: "middle", margin: 0, breakLine: false,
    });
    s.addText(r.d, {
      x: x + 0.28, y: y + 0.54, w: bw - 0.56, h: 0.4,
      fontFace: CN, fontSize: 11, color: MUTED, align: "left", valign: "middle", margin: 0, breakLine: false,
    });
  });
  label(s, "安全边界", W - MR - 2.6, 6.0, 2.2, 0.3, { size: 11, color: ACCENT, bold: true, align: "right" });
  body(s, [
    { text: "所有执行均受只读与结果边界约束，异常进入受控修复路径。", options: { color: INK, fontSize: 13.5, bold: true } },
  ], ML, 5.75, CW - 2.6, 0.4);
  footnote(s, "数据来源：Task35 安全护栏清单。");
}

/* =========================== Slide 6 · 正式 100Q 评测 =========================== */
function s6() {
  const s = pp.addSlide();
  bg(s, 6);
  titleBlock(s, "正式 100Q 评测", "两组测量有效的正式运行");
  token(s, "100Q", W / 2 - 2.0, 1.95, 4.0, 1.1, { size: 54, color: INK });
  label(s, "正式评测 · 唯一权威 EX 语义等价判定", W / 2 - 2.0, 2.95, 4.0, 0.3,
    { size: 11.5, color: MUTED, align: "center" });
  const cardW = 4.6, cardGap = 0.9;
  const x0 = W / 2 - (cardW * 2 + cardGap) / 2;
  const cy = 3.75;
  card(s, x0, cy, cardW, 1.7);
  label(s, "Frozen Baseline", x0 + 0.3, cy + 0.18, cardW - 0.6, 0.3,
    { size: 11.5, color: MUTED, align: "left" });
  token(s, "90.00%", x0 + 0.3, cy + 0.5, cardW - 0.6, 0.75, { size: 40, color: ACCENT });
  card(s, x0 + cardW + cardGap, cy, cardW, 1.7);
  label(s, "Task58", x0 + cardW + cardGap + 0.3, cy + 0.18, cardW - 0.6, 0.3,
    { size: 11.5, color: MUTED, align: "left" });
  token(s, "81.00%", x0 + cardW + cardGap + 0.3, cy + 0.5, cardW - 0.6, 0.75, { size: 40, color: ACCENT });
  label(s, "原始结果并列展示，不做优劣判断", W / 2 - 2.0, 5.7, 4.0, 0.3,
    { size: 11, color: MUTED, align: "center" });
  footnote(s, "Raw EX，原始评测结果。数据来源：Task35 正式 100Q。");
}

/* =========================== Slide 7 · 原始结果与可评价口径 =========================== */
function s7() {
  const s = pp.addSlide();
  bg(s, 7);
  titleBlock(s, "正式评测：原始结果与可评价口径", "Raw 与 Adjusted 双口径并列");
  const cardW = 5.6, gap = 0.55;
  const x0 = W / 2 - (cardW * 2 + gap) / 2;
  const yy = 2.1, hh = 3.4;
  function cardBlock(x, name, raw, adj) {
    card(s, x, yy, cardW, hh);
    label(s, name, x + 0.35, yy + 0.25, cardW - 0.7, 0.35, { size: 14, color: INK, bold: true });
    label(s, "Raw EX", x + 0.35, yy + 0.85, cardW - 0.7, 0.3, { size: 10.5, color: MUTED });
    s.addText(raw, {
      x: x + 0.35, y: yy + 1.15, w: cardW - 0.7, h: 0.6, fontFace: LAT, fontSize: 30,
      bold: true, color: ACCENT, align: "left", valign: "middle", margin: 0,
    });
    label(s, "Adjusted Accounting", x + 0.35, yy + 2.0, cardW - 0.7, 0.3, { size: 10.5, color: MUTED });
    s.addText(adj, {
      x: x + 0.35, y: yy + 2.3, w: cardW - 0.7, h: 0.55, fontFace: LAT, fontSize: 26,
      bold: true, color: INK, align: "left", valign: "middle", margin: 0,
    });
  }
  cardBlock(x0, "Frozen Baseline", "90/100", "90/96");
  cardBlock(x0 + cardW + gap, "Task58", "81/100", "81/98");
  footnote(s,
    "Adjusted Accounting 用于剔除已确认 Gold / Benchmark validity issue，不替代历史 Raw Score。数据来源：Task35。",
    H - 1.25);
}

/* =========================== Slide 8 · Benchmark 口径审计 =========================== */
function s8() {
  const s = pp.addSlide();
  bg(s, 8);
  titleBlock(s, "Benchmark 口径审计", "已确认的 Gold / Business Rule 不一致");
  const gap8 = 0.6;
  const colW = (CW - gap8) / 2;
  const yy = 2.15, hh = 2.5;
  card(s, ML, yy, colW, hh, CARD2);
  label(s, "Gold ↔ Business Rule conflict", ML + 0.35, yy + 0.28, colW - 0.7, 0.35,
    { size: 13.5, color: INK, bold: true });
  token(s, "E-0096", ML + 0.35, yy + 0.85, colW - 0.7, 0.6, { size: 24, color: ACCENT, align: "left" });
  token(s, "E-0100", ML + 0.35, yy + 1.5, colW - 0.7, 0.6, { size: 24, color: ACCENT, align: "left" });
  const xr = ML + colW + gap8;
  card(s, xr, yy, colW, hh);
  label(s, "Gold extra column", xr + 0.35, yy + 0.28, colW - 0.7, 0.35,
    { size: 13.5, color: INK, bold: true });
  token(s, "E-0082", xr + 0.35, yy + 0.85, colW - 0.7, 0.6, { size: 24, color: ACCENT, align: "left" });
  token(s, "E-0083", xr + 0.35, yy + 1.5, colW - 0.7, 0.6, { size: 24, color: ACCENT, align: "left" });
  s.addShape("roundRect", {
    x: ML, y: 5.15, w: CW, h: 0.85, fill: { color: CARD }, line: { color: ACCENT, width: 1 },
    rectRadius: 0.05,
  });
  body(s, [
    { text: "部分失败来自评测口径，而非模型能力。", options: { color: ACCENT_D, fontSize: 14.5, bold: true } },
  ], ML + 0.35, 5.15, CW - 0.7, 0.85);
  footnote(s, "已确认存在局部 Gold / Business Rule 不一致。数据来源：Task35 Gold validity 审计。");
}

/* =========================== Slide 9 · 专项 Contract 验证 =========================== */
function s9() {
  const s = pp.addSlide();
  bg(s, 9);
  titleBlock(s, "专项 Contract 验证", "定向契约验证，不外推整体");
  const cardW = 5.6, gap = 0.55;
  const x0 = W / 2 - (cardW * 2 + gap) / 2;
  const yy = 2.2, hh = 2.6;
  function cCard(x, name, ids, val, note) {
    card(s, x, yy, cardW, hh);
    label(s, name, x + 0.35, yy + 0.25, cardW - 0.7, 0.35, { size: 14, color: INK, bold: true });
    label(s, ids, x + 0.35, yy + 0.62, cardW - 0.7, 0.3, { size: 10.5, color: MUTED });
    s.addText(val, {
      x: x + 0.35, y: yy + 1.0, w: cardW - 0.7, h: 0.8, fontFace: LAT, fontSize: 40,
      bold: true, color: ACCENT, align: "left", valign: "middle", margin: 0,
    });
    label(s, note, x + 0.35, yy + 1.95, cardW - 0.7, 0.4, { size: 10.5, color: MUTED });
  }
  cCard(x0, "CONTRACT_A / CONTRACT_B", "aggregation · output shape · Task26", "10 / 12", "专项契约验证（aggregation / output shape）");
  cCard(x0 + cardW + gap, "CONTRACT_C", "measure selection · Task27", "12 / 12", "专项契约验证（measure selection）");
  footnote(s, "专项验证结果，不外推为整体模型准确率。数据来源：Task35。", H - 1.15);
}

/* =========================== Slide 10 · Blind Evaluation =========================== */
function s10() {
  const s = pp.addSlide();
  bg(s, 10);
  titleBlock(s, "Blind Evaluation", "独立盲测子集，不作总体分数");
  const n = 3, gap = 0.55;
  const cw = (CW - gap * (n - 1)) / n;
  const yy = 2.2, hh = 3.1;
  const cards = [
    { name: "Blind 10Q", val: "8 / 10", pct: "80%", note: "独立盲测·可行性验证", src: "样本用途：盲测可行性" },
    { name: "Blind 25Q", val: "21 / 25", pct: "84%", note: "独立盲测子集", src: "样本用途：独立盲测子集" },
    { name: "Task29", val: "34 / 36", pct: "94.4%", note: "特定 36Q 盲测剩余子集", src: "样本用途：特定盲测剩余子集" },
  ];
  cards.forEach((c, i) => {
    const x = ML + i * (cw + gap);
    card(s, x, yy, cw, hh);
    label(s, c.name, x + 0.3, yy + 0.22, cw - 0.6, 0.3, { size: 13, color: INK, bold: true });
    s.addText(c.val, {
      x: x + 0.3, y: yy + 0.55, w: cw - 0.6, h: 0.8, fontFace: LAT, fontSize: 34,
      bold: true, color: ACCENT, align: "left", valign: "middle", margin: 0,
    });
    label(s, c.note, x + 0.3, yy + 1.45, cw - 0.6, 0.6, { size: 10.5, color: MUTED });
    label(s, c.src, x + 0.3, yy + 2.0, cw - 0.6, 0.6, { size: 9.5, color: MUTED });
    label(s, c.pct, x + 0.3, yy + hh - 0.65, cw - 0.6, 0.4, { size: 15, color: ACCENT_D, bold: true });
  });
  footnote(s, "这些是独立盲测子集，不是总体 benchmark 分数。数据来源：Task35。");
}

/* =========================== Slide 11 · Provider 与评测有效性 =========================== */
function s11() {
  const s = pp.addSlide();
  bg(s, 11);
  titleBlock(s, "Provider 与评测有效性", "一次测量无效的生产环境运行");
  const cardW = 5.6, gap = 0.55;
  const x0 = W / 2 - (cardW * 2 + gap) / 2;
  const yy = 2.25, hh = 2.6;
  const xr = x0 + cardW + gap;
  card(s, x0, yy, cardW, hh);
  label(s, "Provider failures", x0 + 0.35, yy + 0.28, cardW - 0.7, 0.3, { size: 12.5, color: MUTED });
  s.addText("69 / 100", {
    x: x0 + 0.35, y: yy + 0.62, w: cardW - 0.7, h: 0.8, fontFace: LAT, fontSize: 38,
    bold: true, color: ACCENT, align: "left", valign: "middle", margin: 0,
  });
  label(s, "Provider 层失败记录", x0 + 0.35, yy + 1.55, cardW - 0.7, 0.4, { size: 11, color: MUTED });
  card(s, xr, yy, cardW, hh);
  label(s, "Valid model runs", xr + 0.35, yy + 0.28, cardW - 0.7, 0.3, { size: 12.5, color: MUTED });
  s.addText("31", {
    x: xr + 0.35, y: yy + 0.62, w: cardW - 0.7, h: 0.8, fontFace: LAT, fontSize: 38,
    bold: true, color: ACCENT, align: "left", valign: "middle", margin: 0,
  });
  label(s, "有效模型运行次数", xr + 0.35, yy + 1.55, cardW - 0.7, 0.4, { size: 11, color: MUTED });
  s.addShape("roundRect", {
    x: W / 2 - 3.4, y: 5.05, w: 6.8, h: 0.62, fill: { color: CARD2 }, line: { color: ACCENT, width: 1 },
    rectRadius: 0.08,
  });
  s.addText("INVALID_FOR_CAPABILITY_ESTIMATE", {
    x: W / 2 - 3.4, y: 5.05, w: 6.8, h: 0.62, fontFace: LAT, fontSize: 13, bold: true,
    color: ACCENT_D, align: "center", valign: "middle", margin: 0, breakLine: false,
  });
  body(s, [
    { text: "该实验用于说明真实运行环境中的 provider 稳定性与失败传播，不用于模型能力趋势比较。", options: { color: INK, fontSize: 12.5 } },
  ], ML, 5.95, CW, 0.6);
  footnote(s, "数据来源：Task35 · Task81。");
}

/* =========================== Slide 12 · 项目结论 =========================== */
function s12() {
  const s = pp.addSlide();
  bg(s, 12);
  titleBlock(s, "项目结论", "事实 · 数据 · 限定条件");
  const concls = [
    { n: "01", t: "完成自然语言 → SQL → 执行 → 结果分析的 Agent 链路" },
    { n: "02", t: "正式 100Q、专项 Contract、Blind Evaluation 已形成分层验证体系" },
    { n: "03", t: "Benchmark Gold validity 已完成独立审计，后续实验按 Raw 与 Adjusted Accounting 双口径记录" },
  ];
  let y = 2.1;
  concls.forEach((c) => {
    card(s, ML, y, CW, 0.95, CARD, HAIR);
    token(s, c.n, ML + 0.35, y + 0.17, 0.8, 0.6, { size: 24, color: ACCENT, align: "left" });
    s.addText(c.t, {
      x: ML + 1.15, y, w: CW - 1.6, h: 0.95, fontFace: CN, fontSize: 14,
      color: INK, valign: "middle", align: "left", margin: 0, breakLine: false,
    });
    y += 1.15;
  });
  s.addText("谢谢", {
    x: 0, y: 5.85, w: W, h: 0.7, fontFace: CN, fontSize: 26, bold: true,
    color: ACCENT, align: "center", valign: "middle",
  });
  footnote(s, "数据来源：Task35。");
}

/* =========================== Build =========================== */
[s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12].forEach(fn => fn());

await pp.writeFile({ fileName: OUT_PPTX });

const names = ["封面","从问题到洞察","Agent 核心架构","Text2SQL 核心链路","安全与可靠性","正式 100Q 评测","原始结果与可评价口径","Benchmark 口径审计","专项 Contract 验证","Blind Evaluation","Provider 与评测有效性","项目结论"];
writeFileSync(`${OUT_DIR}/slide_registry.json`, JSON.stringify({ slides: names.map((_n, i) => ({ slide: i + 1, name: names[i] })) }, null, 2));
console.log("Generated:", OUT_PPTX);
console.log("Slide count:", 12);