/**
 * 连接状态推导的边界测试（第十阶段 P0-4 / §十）。
 *
 * 把"`llm = configured` 不得被 UI 翻译成 `LLM = available`"变成会响的断言。
 *
 * 背景（第九阶段 Phase E 的实测）：`Header` 与 `AnalysisPage` 曾经**硬编码**
 * "已连接" —— 数据库挂掉时绿徽标依然是绿的。根因是同一个事实有两个推导源。
 * 这里守住 `utils/connection.ts` 是唯一推导源，并锁死两件事：
 *
 * 1. `unknown` 绝不允许降级显示成"已连接"（不知道就说不知道）；
 * 2. LLM 文案只说"已配置"，绝不出现"可用 / available"。
 */

import { describe, expect, it } from "vitest";

import {
  DB_CONNECTION_BADGE,
  DB_CONNECTION_WORD,
  LLM_CONFIG_TITLE,
  toDbConnectionTone,
  toLlmConfigLabel,
  type DbConnectionTone,
} from "./connection";

const ALL_TONES: DbConnectionTone[] = ["loading", "ok", "error", "unknown"];

describe("toDbConnectionTone：四态互斥", () => {
  it("请求中 → loading（还不知道，但不是'已连接'）", () => {
    expect(toDbConnectionTone("loading", null)).toBe("loading");
  });

  it("请求失败 → unknown（拿不到证据 ≠ 不可用）", () => {
    expect(toDbConnectionTone("error", null)).toBe("unknown");
  });

  it("响应明确 database.status=ok → ok", () => {
    expect(
      toDbConnectionTone("success", {
        status: "ok",
        service: "s",
        database: { status: "ok", type: "sqlite", name: "ecommerce.db" },
      }),
    ).toBe("ok");
  });

  it("响应明确 database.status=error → error", () => {
    expect(
      toDbConnectionTone("success", {
        status: "degraded",
        service: "s",
        database: { status: "error", type: "sqlite", name: "ecommerce.db" },
      }),
    ).toBe("error");
  });

  it("字段缺失 → unknown（绝不猜成已连接）", () => {
    expect(
      toDbConnectionTone("success", { status: "ok", service: "s" } as never),
    ).toBe("unknown");
  });
});

describe("状态词：只有 ok 才允许出现「已连接」", () => {
  it("四态各有独立文案，互不重叠", () => {
    const words = ALL_TONES.map((tone) => DB_CONNECTION_WORD[tone]);
    expect(new Set(words).size).toBe(words.length);
  });

  it("「已连接」只出现在 ok 一态", () => {
    const withConnected = ALL_TONES.filter((tone) =>
      DB_CONNECTION_WORD[tone].includes("已连接"),
    );
    expect(withConnected).toEqual(["ok"]);
  });

  it("四态各有徽标样式类", () => {
    for (const tone of ALL_TONES) {
      expect(DB_CONNECTION_BADGE[tone]).toMatch(/^badge-/);
    }
  });
});

describe("LLM 标签：只说「已配置」，绝不说「可用」", () => {
  it("有配置 → 「已配置 · provider · model」", () => {
    expect(toLlmConfigLabel({ provider: "bailian", model: "qwen3.7-flash" })).toBe(
      "已配置 · bailian · qwen3.7-flash",
    );
  });

  it("取不到配置 → 中性占位，不回退到硬编码模型名", () => {
    expect(toLlmConfigLabel(null)).toBe("—");
    expect(toLlmConfigLabel(undefined)).toBe("—");
    expect(toLlmConfigLabel({ provider: null, model: null })).toBe("—");
  });

  it("标签文案不得断言可用性", () => {
    // ⚠️ 只扫**正向标签**。`LLM_CONFIG_TITLE` 里刻意写了
    //    「不代表上游可达或可用」—— 那是**否定句**，是我们要的护栏，
    //    不是违规。把否定句当命中就是典型的假阳性（铁律 49），
    //    正确的做法是收窄检查范围，而不是把产品文案里的"可用"删掉。
    const labels = [
      toLlmConfigLabel({ provider: "bailian", model: "qwen3.7-flash" }),
      toLlmConfigLabel({ provider: "mimo", model: "mimo-v2.5-pro" }),
      toLlmConfigLabel(null),
    ];
    for (const label of labels) {
      expect(label).not.toMatch(/可用|available|reachable/i);
    }
  });

  it("悬停说明必须显式**否认**可用性（否定句是护栏本身）", () => {
    expect(LLM_CONFIG_TITLE).toContain("不代表");
    expect(LLM_CONFIG_TITLE).toMatch(/不代表[^。]*可用/);
  });
});
