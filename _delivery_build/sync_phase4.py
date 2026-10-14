# -*- coding: utf-8 -*-
"""Phase 4 收口：把 4 个修复涉及的源文件同步到交付包暂存区。
只同步 Phase 4 明确修改的文件，绝不触碰冻结资产。
"""
import shutil
from pathlib import Path

ROOT = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent")
PKG = ROOT / "_delivery_build" / "基于Text2SQL的电商智能数据分析Agent"

# Phase 4 实际修改的文件（相对项目根）
CHANGED = [
    # 问题3：Provider 错误分类（含评测 runner 的 provider 错误归类）
    "backend/app/llm/provider.py",
    "backend/app/llm/bailian.py",
    "backend/app/llm/fallback_router.py",
    "backend/app/api/routes/llm.py",
    "evaluation/runner.py",
    # 问题2：Runtime LLM 动态显示
    "backend/app/api/routes/health.py",
    "backend/app/schemas/health.py",
    "frontend/src/api/system.ts",
    "frontend/src/components/Header.tsx",
    # 问题2/3 前端展示链路
    "frontend/src/pages/AnalysisPage.tsx",
    # 问题4：History 计数竞态
    "frontend/src/pages/HistoryPage.tsx",
    # 测试（新增回归用例）
    "backend/tests/test_bailian_provider.py",
    "backend/tests/test_llm_api.py",
    "backend/tests/test_health.py",
    "frontend/src/pages/HistoryPage.test.tsx",
]


def main():
    for rel in CHANGED:
        src = ROOT / rel
        if not src.exists():
            raise FileNotFoundError(src)
        # 04_项目源码 完整快照
        dst4 = PKG / "04_项目源码" / rel
        dst4.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst4)
        print("synced 04:", rel)
        # 05_部署运行版（仅运行集合涉及的目录）
        p5 = None
        if rel.startswith("backend/app/"):
            p5 = PKG / "05_部署运行版" / rel
        elif rel.startswith("frontend/src/"):
            p5 = PKG / "05_部署运行版" / rel
        elif rel.startswith("evaluation/"):
            p5 = PKG / "05_部署运行版" / rel
        if p5 is not None:
            p5.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, p5)
            print("synced 05:", rel)
    print("SYNC DONE")


if __name__ == "__main__":
    main()
