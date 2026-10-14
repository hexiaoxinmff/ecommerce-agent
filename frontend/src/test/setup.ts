/**
 * Vitest 全局 setup：jest-dom 断言、RTL 清理、storage/fetch 复位。
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom 无 ResizeObserver（ChartCard/ECharts 需要）：直接挂 globalThis，
// 不用 vi.stubGlobal（避免 afterEach unstubAllGlobals 清掉）。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
if (typeof globalThis.ResizeObserver === "undefined") {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
