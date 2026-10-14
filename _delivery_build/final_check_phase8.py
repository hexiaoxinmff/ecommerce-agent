# -*- coding: utf-8 -*-
"""Phase 8：最终终检（文本审计 + 冻结复验 + 安全扫描 + ZIP 打包后终检）。

只读检查工具；仅打包动作会写 ZIP。用法：
  python final_check_phase8.py audit      # 第三步 文本审计 + 第四步 冻结复验 + 第五步 安全扫描
  python final_check_phase8.py zipcheck   # 第八~十步 ZIP 终检 + 口径抽检（从 ZIP 直读）
"""
import hashlib
import io
import os
import re
import sys
import zipfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"F:\基于 Text2SQL 的电商智能数据分析 Agent\_delivery_build")
PKG = ROOT / "基于Text2SQL的电商智能数据分析Agent"
ZIP_PATH = ROOT / "Text2SQL电商智能数据分析Agent_v1.0.0.zip"

FROZEN = [
    ("02_数据与评测/01_电商数据库/ecommerce.db", "65E5D8B2727CFA064174F9A08AA7D4B08209E0EDD1EBA81F3155698F1A4491D9"),
    ("02_数据与评测/02_Benchmark/ecommerce_eval_v1.json", "DBA277CC0BE7CC282DF67C86DD7EABFEA1337458612A86885F6DAEF0C6829F1A"),
    ("02_数据与评测/03_Gold与Prompt/ecommerce_examples.json", "EE12FCC994C6AFEC42A94F4E327109961AC2022466673BC4A37485638F7D4CEE"),
    ("02_数据与评测/03_Gold与Prompt/sql_generator_v1.3.txt", "2AF938BE9866A62A97FDC3F1B0C7DC43B0785A7FF75AD420109B1D18ED39DC4C"),
    ("02_数据与评测/04_正式评测结果/clean_baseline_v1_1/clean_baseline_v1_1.md", "6A6A137D7757BC863A310005281341A90D8F8A0EDA4384CD8D5C70DBA55237E0"),
    ("02_数据与评测/04_正式评测结果/clean_baseline_v1_1/eval_clean_baseline_v1_1.json", "39404FEDEF84B338CC7B48ED2972DB98C7C574CD8CFCA196CA02F7843E42F66E"),
    ("02_数据与评测/04_正式评测结果/clean_baseline_v1_1/experiment_config.json", "5C83C64E642652D37A92311331956AB5CB1B5FD3E437DC3FB810593773302DB0"),
    ("02_数据与评测/04_正式评测结果/E3_实验冻结/E3_FINAL_FREEZE.md", "7B9627FA80479FE9665755DF27662A8F8E59CCDC83687F6E1D1488B3E2DAF585"),
    ("02_数据与评测/04_正式评测结果/E3_实验冻结/task22_freeeze_hash_baseline.json", "77BDC83CB5B1D9C56FD8E46706964B4BE4E48BA1FD9C735825AFDBE5FDB2C2CB"),
    ("02_数据与评测/04_正式评测结果/E2E_验证/task23_final_acceptance/e2e_smoke.json", "C6DAFDEC6671B0A01C6BF86C7FCCABCD28D76804184A4E5A3DEF8681D12090D9"),
    ("02_数据与评测/04_正式评测结果/FINAL_EXPERIMENT_MATRIX.md", "6A36AED8FC33496F6EEF693481B2E4FAD7A23DFA3168F0D39783EE30DFAB21C6"),
    ("02_数据与评测/04_正式评测结果/FINAL_BAD_CASE_CATALOG.md", "2B214A5BD5530B50A4FF32836AD7C42B30C9847D62F755ACC251385DA37172C0"),
    ("02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_MANIFEST.md", "10554C3184B3955F0D3AFDBE9BCBB6460F0BFE30623711043771A15E67336DFD"),
    ("02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_MANIFEST.json", "5FD02CC90B51AC4075D7E26CE5DDCDC852281EFF9BE3AF6D29B7913384AB541A"),
    ("02_数据与评测/04_正式评测结果/发布基线冻结/RELEASE_BASELINE_20260920.md", "6662718FA884DAEDBF81B483A8A04569069E001E133D2B86A32F5540C888C86A"),
    ("02_数据与评测/04_正式评测结果/发布基线冻结/CANDIDATE_A_PROMOTION_MANIFEST.md", "1D64006ECF8FC5C7191E79CE3AB03A57E4E8D5078FC243633FC7C705AB77356B"),
    ("02_数据与评测/04_正式评测结果/发布基线冻结/CANDIDATE_A_PROMOTION_REVIEW.md", "8C8D686E3D5231DD0000FB02DF65667855D64C3415A2F0C66D6AD22107715B0A"),
    ("01_项目文档与说明/04_测试与验收/FINAL_ACCEPTANCE_REPORT.md", "B1C69A7EAD23857FB899198A9AE4C5FD74AE5CE1E891B3C03CCD5D26F2AB9045"),
    ("01_项目文档与说明/04_测试与验收/FINAL_REQUIREMENTS_CHECKLIST.md", "4F32A190BC71CAAADCCF5E6262293123050CB31BC390BE8491508FD6C0A898F1"),
    ("01_项目文档与说明/04_测试与验收/TEST_REPORT.md", "FE1C55DCDC8083F205719BFE9FF22B25BDC9917224DD0163C8C99ACCFA248557"),
    ("03_答辩与演示/答辩PPT.pptx", "E9D8D061D1D91495AD5AB1BC608E7C582ED9407569784D6553E42C8019853BF6"),
]

SECRET_PATTERNS = None  # 复用第六阶段 v2 逐行扫描器（security_scan_phase6.scan_text/classify）
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ttf", ".db", ".zip",
            ".ico", ".svg", ".pdf", ".pptx", ".mp4"}


def read_pkg(rel):
    return (PKG / rel).read_text(encoding="utf-8")


def audit():
    print("=" * 8, "第三步：第七阶段修订文本审计", "=" * 8)
    demos = read_pkg("03_答辩与演示/Demo演示脚本.md")
    checklist = read_pkg("03_答辩与演示/答辩检查清单.md")
    qa = read_pkg("03_答辩与演示/答辩QA预案.md")
    record = read_pkg("03_答辩与演示/PPT文字记录.md")
    params = read_pkg("【项目参数】Text2SQL电商智能数据分析Agent_v1.0.0.md")
    handover = read_pkg("00_交付导读/项目交接说明.md")
    apidoc = read_pkg("01_项目文档与说明/03_API与部署/API.md")
    dep = read_pkg("05_部署运行版/README.md")

    checks = []

    def chk(name, cond):
        checks.append((name, bool(cond)))

    # 1 认证
    chk("认证:脚本含注册/登录步骤(已有账号直接登录)", "注册 / 登录" in demos and "已有账号直接登录" in demos)
    chk("认证:PBKDF2+Bearer session 口径在QA", "PBKDF2" in qa and "Bearer session" in qa)
    chk("认证:限制三条(refresh token/验证码/限流)在脚本", all(k in demos for k in ("refresh token", "验证码", "限流")))
    chk("认证:清单红线不含『用户登录未实现/没有用户登录』", "用户登录未实现" not in checklist and "没有用户登录" not in checklist)
    # 2 测试数量
    chk("测试:QA=967 passed / 1 skipped", "967 passed / 1 skipped" in qa)
    chk("测试:项目参数=967 passed / 1 skipped", "967 passed / 1 skipped" in params)
    chk("测试:交接说明=967 passed / 1 skipped", "967 passed / 1 skipped" in handover)
    # 3 API
    chk("API:项目参数=17 端点 / 17 条真实路由", "17 端点" in params and "17 条真实路由" in params)
    chk("API:项目参数含 GET /api/system/schema", "GET /api/system/schema" in params)
    chk("API:API.md 含 2.1 Schema 节 + 路由", "### 2.1 数据库 Schema 元数据（只读）" in apidoc and "/api/system/schema" in apidoc)
    chk("API:部署 README=17 条真实路由", "17 条真实路由" in dep)
    # 4 Runtime
    chk("Runtime:脚本 正式=Mimo V2.5 Pro + EX 90.0%(90/100)", "Mimo V2.5 Pro" in demos and "EX 90.0%（90/100）" in demos)
    chk("Runtime:脚本 Demo=bailian/qwen3.7-flash", "bailian" in demos.lower() and "qwen3.7-flash" in demos)
    chk("Runtime:脚本与清单均含『不计入』正式成绩", "不计入" in demos and "不计入" in checklist)
    # 5 成绩
    chk("成绩:QA 唯一正式成绩口径", "EX 90.0%" in qa and "不是正式成绩" in qa)
    chk("成绩:清单 Smoke 非正式成绩", "非正式成绩" in checklist)
    # 6 三 Demo 证据对象
    chk("三Demo:脚本含 5 条 / 5/5 / 10/10 三对象", "5 条" in demos and "5/5" in demos and "10/10" in demos)
    chk("三Demo:交接注明无逐问结构化日志", "完整逐问结构化日志未随包保存" in handover)
    # 7 246 口径
    oral = "这里的 246 是查询结果值，不是结果行数；实际结果返回 1 行"
    chk("246:脚本统一话术", oral in demos)
    chk("246:清单同口径", ("246 是查询结果值" in checklist) or ("246` 是 `user_count` 字段值" in checklist))
    chk("246:文字记录口径提示", "口径提示（2026-09-27）" in record and "246" in record)
    # 8 禁用词（当前有效材料）
    all_cur = demos + checklist + qa + record + params + handover + apidoc
    chk("禁用:『用户登录未实现/没有用户登录』清零", "用户登录未实现" not in all_cur and "没有用户登录" not in all_cur)
    chk("禁用:『16 条真实路由/16 端点』清零", "16 条真实路由" not in all_cur and "16 端点" not in all_cur)
    chk("禁用:『正式评测 100%』仅作否定句出现", "不得表述为" in demos and "正式评测 100%" not in (checklist + qa))

    npass = 0
    for name, ok in checks:
        print(("PASS" if ok else "FAIL"), "|", name)
        npass += 1 if ok else 0
    print(f"TEXT_AUDIT: {npass}/{len(checks)}")

    print("=" * 8, "第四步：21 项冻结资产复验（目录）", "=" * 8)
    ok = 0
    for rel, expect in FROZEN:
        h = hashlib.sha256((PKG / rel).read_bytes()).hexdigest().upper()
        if h == expect:
            ok += 1
        else:
            print("CHANGED:", rel)
    print(f"FROZEN_DIR: {ok}/{len(FROZEN)}")

    print("=" * 8, "第五步：最终安全扫描（目录，复用第六阶段 v2 逐行扫描器）", "=" * 8)
    sys.path.insert(0, str(ROOT))
    import security_scan_phase6 as s6

    if not s6.selftest():
        print("SECRET_SCAN: FAIL (scanner selftest)")
        return

    env_files = [str(p.relative_to(PKG)).replace("\\", "/") for p in PKG.rglob("*")
                 if p.is_file() and p.name in (".env", ".env.local")]
    print(".env files:", len(env_files), env_files)
    findings = []
    scanned = 0
    for p in PKG.rglob("*"):
        if not p.is_file() or p.suffix.lower() in SKIP_EXT or p.name == ".env":
            continue
        rel = str(p.relative_to(PKG)).replace("\\", "/")
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        scanned += 1
        s6.scan_text(text, rel, findings)
    print("scanned text files:", scanned)
    buckets = {}
    for tag, kind, path, line, val in findings:
        buckets.setdefault(tag, []).append((kind, path, line, val))
    for tag in ("REVIEW", "FAKE(test)", "CODE(false-positive)"):
        items = buckets.get(tag, [])
        print(f"{tag}: {len(items)}")
        for kind, path, line, val in items:
            print("   ", f"[{kind}] {path}:{line} -> {val}")
    review_ok = len(buckets.get("REVIEW", [])) == 0
    print("SECRET_SCAN:", "PASS" if (len(env_files) == 0 and review_ok) else "FAIL")


def zipcheck():
    print("=" * 8, "第八~十步：最终 ZIP 终检", "=" * 8)
    z = zipfile.ZipFile(ZIP_PATH)
    names = [n for n in z.namelist() if not n.endswith("/")]
    print("ZIP file count:", len(names))
    print("ZIP size bytes:", ZIP_PATH.stat().st_size)
    print("ZIP SHA256:", hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest().upper())
    print("testzip:", "PASS" if z.testzip() is None else "CORRUPT")

    prefix = "基于Text2SQL的电商智能数据分析Agent/"
    dir_files = sorted(p.relative_to(PKG).as_posix() for p in PKG.rglob("*") if p.is_file())
    zip_rel = sorted(n[len(prefix):] for n in names if n.startswith(prefix))
    print("ZIP↔DIR set equal:", set(zip_rel) == set(dir_files),
          "| missing:", len(set(dir_files) - set(zip_rel)), "| extra:", len(set(zip_rel) - set(dir_files)))

    mismatch = 0
    for n in names:
        if not n.startswith(prefix):
            mismatch += 1
            print("OUTSIDE-PREFIX:", n)
            continue
        rel = n[len(prefix):]
        if hashlib.sha256(z.read(n)).hexdigest() != hashlib.sha256((PKG / rel).read_bytes()).hexdigest():
            mismatch += 1
            print("MISMATCH:", rel)
    print("byte-level mismatch:", mismatch)

    ok = 0
    for rel, expect in FROZEN:
        h = hashlib.sha256(z.read(prefix + rel)).hexdigest().upper()
        if h == expect:
            ok += 1
        else:
            print("FROZEN-ZIP CHANGED:", rel)
    print(f"FROZEN_ZIP_DIRECT_READ: {ok}/{len(FROZEN)}")

    print("=" * 8, "第九步：关键资产在场（ZIP 内）", "=" * 8)
    required = [
        "00_交付导读/项目交接说明.md", "00_交付导读/交付说明.md", "00_交付导读/正式资产清单.md",
        "03_答辩与演示/答辩PPT.pptx", "03_答辩与演示/PPT文字记录.md", "03_答辩与演示/Demo演示脚本.md",
        "03_答辩与演示/答辩QA预案.md", "03_答辩与演示/答辩检查清单.md",
        "02_数据与评测/04_正式评测结果/clean_baseline_v1_1/clean_baseline_v1_1.md",
        "02_数据与评测/02_Benchmark/ecommerce_eval_v1.json",
        "02_数据与评测/04_正式评测结果/E2E_验证/task23_final_acceptance/e2e_smoke.json",
        "04_项目源码/reports/eval/eval_20260927_28404.md",
        "01_项目文档与说明/03_API与部署/API.md", "05_部署运行版/README.md",
        "05_部署运行版/.env.example", "05_部署运行版/启动说明.md",
        "【项目参数】Text2SQL电商智能数据分析Agent_v1.0.0.md",
    ]
    tops = ["00_交付导读/", "01_项目文档与说明/", "02_数据与评测/", "03_答辩与演示/",
            "04_项目源码/", "05_部署运行版/", "06_历史归档/"]
    for t in tops:
        print("top dir:", t, "PASS" if any(n.startswith(prefix + t) for n in names) else "FAIL")
    miss = 0
    for rel in required:
        hit = (prefix + rel) in set(names)
        miss += 0 if hit else 1
        if not hit:
            print("MISSING:", rel)
    print(f"KEY_ASSETS: {len(required) - miss}/{len(required)}")

    print("=" * 8, "第十步：最终答辩口径抽检（ZIP 直读）", "=" * 8)
    def zread(rel):
        return z.read(prefix + rel).decode("utf-8", "ignore")

    demos = zread("03_答辩与演示/Demo演示脚本.md")
    checklist = zread("03_答辩与演示/答辩检查清单.md")
    qa = zread("03_答辩与演示/答辩QA预案.md")
    params = zread("【项目参数】Text2SQL电商智能数据分析Agent_v1.0.0.md")
    apidoc = zread("01_项目文档与说明/03_API与部署/API.md")
    handover = zread("00_交付导读/项目交接说明.md")

    facts = [
        ("登录", "注册 / 登录" in demos and "已有账号直接登录" in demos and "用户登录未实现" not in checklist),
        ("测试数", "967 passed / 1 skipped" in qa and "967 passed / 1 skipped" in params),
        ("17路由", "17 条真实路由" in params and "17 端点" in params),
        ("Schema路由", "GET /api/system/schema" in params and "/api/system/schema" in apidoc),
        ("FormalMimo", "Mimo V2.5 Pro" in demos and "EX 90.0%（90/100）" in demos and "mimo-v2.5-pro" in handover),
        ("DemoBailian", "bailian" in demos.lower() and "qwen3.7-flash" in demos),
        ("Smoke非正式", "非正式成绩" in checklist and "不是正式成绩" in qa and "10/10" in demos),
        ("246口径", "这里的 246 是查询结果值，不是结果行数；实际结果返回 1 行" in demos),
    ]
    npass = 0
    for name, ok2 in facts:
        print(("PASS" if ok2 else "FAIL"), "|", name)
        npass += 1 if ok2 else 0
    print(f"DEFENSE_SPOTCHECK: {npass}/{len(facts)}")

    print("=" * 8, "第十一步：ZIP 内容边界", "=" * 8)
    env_in_zip = [n for n in names if n.rsplit("/", 1)[-1] in (".env", ".env.local")]
    print("ZIP 内 .env 文件:", len(env_in_zip), env_in_zip)
    fake_logs = [n for n in names if "demo" in n.lower() and n.endswith((".json", ".log"))]
    print("ZIP 内疑似 demo 运行日志文件(应仅历史 e2e/eval,无 2026-09-27 UI 逐问日志):", fake_logs)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audit"
    if mode == "audit":
        audit()
    elif mode == "zipcheck":
        zipcheck()
    else:
        print("usage: audit | zipcheck")
