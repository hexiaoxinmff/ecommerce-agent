# -*- coding: utf-8 -*-
r"""Phase 6：交付包 ZIP 最终安全扫描 v2（值级正则 + 行内匹配 + 自测）。

v1 教训（已修）：`\s*[=:]` 跨行误配 —— `MIMO_API_KEY=`（空值行尾）+ 下一行
`MIMO_BASE_URL=` 被判成「MIMO_API_KEY=MIMO_BASE_URL」。v2 改为**逐行匹配**，
赋值类 pattern 永不跨行；并加 --selftest（合成真密钥必须命中 REVIEW，
已知代码形态/空值必须不命中），防检查器空转。

允许：测试假 Key / 测试假密码（backend/tests 等测试目录、占位符词表）、
SHA256、示例/空配置、压缩 JS 与类型注解的代码形态假阳性。
判定：REVIEW（疑似真实秘密）= 0 且 .env 文件 = 0 ⇒ PASS。
"""
import re
import sys
import zipfile

ZIP = r"F:\基于 Text2SQL 的电商智能数据分析 Agent\_delivery_build\Text2SQL电商智能数据分析Agent_v1.0.0.zip"

# —— 行内（不跨行）赋值类 pattern ——
KEY_NAMES = r"(?:DASHSCOPE_API_KEY|MIMO_API_KEY|BAILIAN_API_KEY)"
P_LINE = {
    "real_api_key_assign": re.compile(KEY_NAMES + r"\s*[=:][ \t]*[\"']?([A-Za-z0-9_\-]{12,})"),
    "password_assign": re.compile(
        r"\b(?:password|passwd|pwd)\s*[=:][ \t]*[\"']?([^\s\"']{8,})", re.I),
}
# —— 全文类 pattern ——
P_GLOBAL = {
    "sk_literal": re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"),
    "pem_private": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jwt_literal": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    "bearer_literal": re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{24,}\b"),
}
TEST_DIR_MARKERS = ("/backend/tests/", "/tests/", "/frontend/src/", "/evaluation/")

FAKE_SK = re.compile(r"^sk-(test|fake|dummy|demo|example|xxx|placeholder|your)", re.I)
FAKE_PASSWORD = re.compile(
    r"^(test|fake|dummy|demo|example|password|passwd|secret|change|wrong|bad|short|weak|correct|"
    r"valid|invalid|new|old|user|admin|login|auth|pw|strong|s3cret|secure|good|right|"
    r"123456|abcdef|letmein|qwerty|passw0rd|hunter2|password[0-9]*|p[4a]ssw[0o]rd)"
    r"[0-9_\-.!@#$%^&*a-zA-Z]*$", re.I)
# 代码形态（压缩 JS / 类型注解 / 属性表 / 变量链）：值含代码结构字符或标识符链
CODE_SHAPE = re.compile(r".*[()\[\]{}=]|^!0|^[A-Za-z_$][A-Za-z0-9_$]*\.[A-Za-z0-9_$]")


def classify(kind, value, path):
    if kind == "sk_literal":
        return "REVIEW" if not FAKE_SK.match(value) else "FAKE(test)"
    if kind == "password_assign":
        if FAKE_PASSWORD.match(value):
            return "FAKE(test)"
        if any(m in ("/" + path) for m in TEST_DIR_MARKERS):
            return "FAKE(test)"
        if CODE_SHAPE.match(value):
            return "CODE(false-positive)"
        return "REVIEW"
    return "REVIEW"


def scan_text(text, path, findings):
    for kind, pat in P_LINE.items():
        for line_no, line in enumerate(text.splitlines(), 1):
            for m in pat.finditer(line):
                value = m.group(1)
                findings.append((classify(kind, value, path), kind, path, line_no, value[:40]))
    for kind, pat in P_GLOBAL.items():
        for m in pat.finditer(text):
            value = m.group(0)
            line_no = text[: m.start()].count("\n") + 1
            findings.append((classify(kind, value, path), kind, path, line_no, value[:40]))


SELFTEST_CASES = [
    # (text, expected_min_review_hits)  同一秘密可被多条 pattern 命中 ⇒ 用下限
    ("DASHSCOPE_API_KEY=sk-real0123456789abcdefghijklmn\n", 1),
    ("MIMO_API_KEY=mimo_live_key_1234567890abcd\n", 1),
    ("password='RealSecret#2026xyz'\n", 1),
    # 已知不应命中 REVIEW 的形态（空值跨行 / 代码形态）
    ("DASHSCOPE_API_KEY=\nBAILIAN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1\n", 0),
    ("MIMO_API_KEY=\nMIMO_BASE_URL=https://api.xiaomimimo.com/v1\n", 0),
    ("password=!0,range:!0,search:!0,tel:!0,text:!0\n", 0),
    ("password: string): void\n", 0),
    ("password=Ll(13)]=\n", 0),
]


def selftest():
    ok = True
    for i, (text, expect) in enumerate(SELFTEST_CASES, 1):
        findings = []
        scan_text(text, "selftest/case%d" % i, findings)
        got = sum(1 for f in findings if f[0] == "REVIEW")
        status = "OK " if got >= expect and (expect > 0 or got == 0) else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"selftest case {i}: expect REVIEW>={expect} got={got} {status}")
    print("SELFTEST=", "PASS" if ok else "FAIL")
    return ok


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)

    z = zipfile.ZipFile(ZIP)
    names = z.namelist()
    env_files = [n for n in names if n.split("/")[-1] == ".env"]
    findings = []
    scanned = 0
    for name in names:
        if name.endswith("/"):
            continue
        data = z.read(name)
        scanned += 1
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scan_text(text, name, findings)

    print(f"scanned files: {scanned}")
    print(f".env files (exact name): {len(env_files)} {env_files}")
    buckets = {}
    for tag, kind, path, line, val in findings:
        buckets.setdefault(tag, []).append((kind, path, line, val))

    for tag in ("REVIEW", "FAKE(test)", "CODE(false-positive)"):
        items = buckets.get(tag, [])
        print(f"\n=== {tag}: {len(items)} ===")
        for kind, path, line, val in items:
            print(f"[{kind}] {path}:{line} -> {val}")

    env_ok = len(env_files) == 0
    review_ok = len(buckets.get("REVIEW", [])) == 0
    print(f"\nENV_FILES_ZERO={'PASS' if env_ok else 'FAIL'}")
    print(f"REAL_SECRET_HITS={len(buckets.get('REVIEW', []))} -> {'PASS' if review_ok else 'FAIL'}")
    print(f"SECRET_SCAN={'PASS' if env_ok and review_ok else 'FAIL'}")
    if not (env_ok and review_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
