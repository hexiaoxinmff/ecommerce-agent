/**
 * `uiCopy.ts` 的结构性约束测试（第九阶段 Phase G）。
 *
 * 目的不是测「文案写得对不对」，而是**把一条硬约束变成会响的警报**：
 * 本模块只允许放界面用语，**不得出现任何业务数值**。
 *
 * 为什么必须有它：Phase G 删掉 `data/demo.ts` 的根本理由是
 * 「假数据不能被无声地请回来」。只要有人往 `uiCopy.ts` 里塞一句
 * `"¥7,662,921"`，本次删除的成果就被抵消 —— 而这个文件名叫 `uiCopy`，
 * 看起来完全"安全"，比 `demo.ts` 更容易让人放松警惕。
 *
 * 按铁律 20/28：**否定式断言必须配反向自查**。最后一条用例注入一个
 * 必然违规的样本，证明扫描器真的会响（否则「未命中」可能只是正则写错了）。
 */

import { describe, expect, it } from "vitest";

import * as uiCopy from "./uiCopy";

/** 把本模块所有导出摊平成一维字符串数组 */
function allStrings(): string[] {
  const out: string[] = [];
  for (const value of Object.values(uiCopy)) {
    if (typeof value === "string") {
      out.push(value);
    } else if (Array.isArray(value)) {
      for (const item of value) {
        out.push(typeof item === "string" ? item : JSON.stringify(item));
      }
    } else {
      out.push(JSON.stringify(value));
    }
  }
  return out;
}

/** 业务数值的形态：货币 / 千分位 / 百分比 / 小数 */
const BUSINESS_NUMBER_PATTERNS: Array<[string, RegExp]> = [
  ["货币符号 + 数字", /[¥￥]\s*\d/],
  ["千分位数字", /\d{1,3}(?:,\d{3})+/],
  ["百分比", /\d+(?:\.\d+)?\s*%/],
  ["小数", /\b\d+\.\d+\b/],
];

/** demo.ts 时代的具体假值（纵深防御：即使形态变了也不许出现） */
const BANNED_LITERALS = [
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
  "Demo",
  "演示数据",
];

describe("uiCopy.ts 结构性约束：不得含业务数值", () => {
  const strings = allStrings();

  it("导出非空，且全部是字符串 / 字符串数组", () => {
    expect(strings.length).toBeGreaterThan(0);
    expect(Object.keys(uiCopy).sort()).toEqual([
      "agentStages",
      "analysisExamples",
      "exampleQuestions",
    ]);
  });

  for (const [label, pattern] of BUSINESS_NUMBER_PATTERNS) {
    it(`不含${label}`, () => {
      const hits = strings.filter((s) => pattern.test(s));
      expect(hits, `命中：${JSON.stringify(hits)}`).toEqual([]);
    });
  }

  it("不含 demo.ts 时代的具体假值", () => {
    const joined = strings.join("\n");
    const hit = BANNED_LITERALS.filter((b) => joined.includes(b));
    expect(hit, `命中：${JSON.stringify(hit)}`).toEqual([]);
  });

  it("反向自查：扫描器真的会响（变异测试）", () => {
    // 用一个必然违规的样本证明正则有效 —— 若正则写错，上面几条会「假通过」。
    const injected = ["本月销售额是多少？", "¥7,662,921", "环比 +12.4%", "客单价 352.6"];
    const caught = injected.filter((s) =>
      BUSINESS_NUMBER_PATTERNS.some(([, p]) => p.test(s)),
    );
    // 「¥7,662,921」「+12.4%」「352.6」三条必须被抓到，只有正常文案放行
    expect(caught).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// Phase G 结构性约束：`data/demo.ts` 不得复活
// ---------------------------------------------------------------------------

/**
 * 删除一个文件不等于消灭它：只要有人再建一个同名文件、或把假数据搬到别处
 * 再 `import` 回来，Phase G 的成果就归零，而且**没有任何测试会变红**。
 * ⇒ 用源文件级的断言把「demo 模块不存在 / 无人 import」变成可执行的契约。
 *
 * ⚠️ 为什么用 `import.meta.glob` 而不是 `node:fs`：
 * `tsconfig.app.json` 把 `types` 锁成 `["vite/client"]`，这是**有意的边界**
 * —— 让 `src/` 下的浏览器代码在类型层面就够不到 `process` / `Buffer` / `fs`。
 * 为了几条断言方便就把 `"node"` 加进 `types`，等于为了好写检查器而拆掉它
 * 本该守住的墙。`import.meta.glob` 已被 `vite/client` 类型覆盖，且天然不引入
 * Node 全局，是本场景的正确工具。
 */
const SOURCE_MODULES = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** 去掉块注释与整行/行尾行注释（够用即可，不求完备的 JS 词法分析） */
function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/[^\n]*/g, "$1");
}

/** 指向 demo 模块的 import 边（含 `../data/demo`、`./demo`） */
const IMPORT_DEMO_RE = /from\s*["'][^"']*\/demo["']/;

/**
 * ⚠️ 反向自查的样本必须**拼装**出来，不能写成完整字面量。
 *
 * 原因（铁律 21：「用标记子串扫描必然自指假阳性」）：本文件自身就在
 * `SOURCE_MODULES` 的扫描范围内。若这里直接写下 `from "./demo"` 这样的文本，
 * 「没有任何文件 import demo」那条用例会把**扫描器自己**判成违规者 —— 一个
 * 永远修不掉的假红。
 *
 * 拼装后：**源码文本**里不存在完整的 import 形态（所以不会自指），
 * **运行期**拼出来的字符串仍是货真价实的样本（所以变异测试依然有效）。
 */
const KEYWORD_FROM = "from";
const SPEC_LOCAL_DEMO = "./demo";
const SPEC_DATA_DEMO = "../data/demo";

describe("Phase G：data/demo.ts 不得复活", () => {
  it("frontend/src/data/demo.ts 已不存在", () => {
    // glob 不到 = 文件不存在（同一机制，无需 fs）
    expect(Object.keys(SOURCE_MODULES)).not.toContain("./demo.ts");
    expect(Object.keys(SOURCE_MODULES)).not.toContain("./data/demo.ts");
  });

  it("src 下没有任何文件 import demo 模块", () => {
    const offenders = Object.entries(SOURCE_MODULES)
      .filter(([, code]) => IMPORT_DEMO_RE.test(stripComments(code)))
      .map(([file]) => file.replace(/^\.\.\//, ""));
    expect(offenders, `仍 import demo：${JSON.stringify(offenders)}`).toEqual([]);
  });

  it("反向自查：扫描器真的能认出 import（变异测试）", () => {
    // 若 IMPORT_DEMO_RE 或注释剔除写错，上一条会「假通过」。
    const planted = [
      `import { kpiData } ${KEYWORD_FROM} "${SPEC_DATA_DEMO}";`,
      // 多行 import：`from` 不在行首，行首锚定的写法会漏掉它
      `import {\n  salesTrend,\n} ${KEYWORD_FROM} "${SPEC_LOCAL_DEMO}";`,
    ];
    for (const code of planted) {
      expect(IMPORT_DEMO_RE.test(stripComments(code)), code).toBe(true);
    }
    // 而注释里的描述**不得**被算成 import（这正是 charts.ts 的情形）
    const commented = ` * 原先直接 \`import { salesTrend } ${KEYWORD_FROM} "${SPEC_LOCAL_DEMO}"\`，数据是编的。`;
    expect(IMPORT_DEMO_RE.test(stripComments(`/*\n${commented}\n */`))).toBe(false);
  });
});
