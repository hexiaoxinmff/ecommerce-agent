"""正式启动入口（第十阶段 P0-3）：一条命令把 Backend + Frontend 拉起来。

    python scripts/start_dev.py

在此之前，"怎么启动"只散落在文档里（`cd backend && uvicorn app.main:app` +
`cd frontend && npm run dev`），依赖人工在两个终端里各敲一次，并且：

- 端口被占用时，Vite 会**静默**换到 5174 —— 用户访问 5173 看到别人的服务；
- 后端挂掉时窗口一闪而过，只剩一句看不懂的 traceback；
- 依赖没装、`.env` 没配、库没初始化，都要等跑到一半才发现。

本脚本把上面这些变成启动前的**预检**与失败后的**明确文案**，并给出固定的地址输出：

    Backend : http://127.0.0.1:8000
    Frontend: http://localhost:5173
    Health  : OK

退出码（供自动化断言，不用去 grep 中文文案）：

    0  成功
    2  Python 版本过低
    3  后端依赖缺失
    4  Node / npm 缺失
    5  前端依赖缺失
    6  .env 缺失
    7  端口被占用
    8  数据文件缺失（业务库 / 应用库）
    9  后端启动失败
    10 前端启动失败

注意：本脚本**不创建第二套启动体系**，它调用的就是文档里那两条命令
（`uvicorn app.main:app` / `npm run dev`），只是把它们编排起来。
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
LOGS_DIR = PROJECT_ROOT / "logs"
PID_FILE = LOGS_DIR / "start_dev_pids.json"

MIN_PYTHON = (3, 12)

EXIT_OK = 0
EXIT_PYTHON = 2
EXIT_BACKEND_DEPS = 3
EXIT_NODE = 4
EXIT_FRONTEND_DEPS = 5
EXIT_ENV = 6
EXIT_PORT = 7
EXIT_DATA = 8
EXIT_BACKEND_FAILED = 9
EXIT_FRONTEND_FAILED = 10

# 后端最小依赖（与 requirements.txt 对齐；只检查"能否 import"）
BACKEND_MODULES = ("fastapi", "uvicorn", "dotenv", "pydantic", "langgraph", "sqlglot", "openai")

TAIL_LINES = 25


class StartupError(RuntimeError):
    """预检失败：带退出码与面向用户的明确文案。"""

    def __init__(self, code: int, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass
class Process:
    name: str
    popen: subprocess.Popen
    tail: deque = field(default_factory=deque)

    def tail_text(self) -> str:
        return "\n".join(self.tail)


# ---------- 输出 ----------


def say(message: str = "") -> None:
    print(message, flush=True)


def ok(label: str, detail: str = "") -> None:
    say(f"  [OK]   {label}{('  ' + detail) if detail else ''}")


def warn(label: str, detail: str = "") -> None:
    say(f"  [WARN] {label}{('  ' + detail) if detail else ''}")


def fail(label: str, detail: str = "") -> None:
    say(f"  [FAIL] {label}{('  ' + detail) if detail else ''}")


# ---------- 预检 ----------


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise StartupError(
            EXIT_PYTHON,
            f"Python 版本过低：当前 {sys.version.split()[0]}，需要 "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
            "请安装 Python 3.12+ 后，用该解释器重新执行本脚本。",
        )
    ok("Python", sys.version.split()[0])


def check_backend_deps() -> None:
    import importlib.util

    missing = [name for name in BACKEND_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        raise StartupError(
            EXIT_BACKEND_DEPS,
            f"后端依赖缺失：{', '.join(missing)}",
            "请在项目根目录执行：python -m venv .venv && "
            ".venv\\Scripts\\activate && pip install -r requirements.txt",
        )
    ok("后端依赖", f"{len(BACKEND_MODULES)} 个模块可导入")


def check_node() -> str:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        missing = "node" if node is None else "npm"
        raise StartupError(
            EXIT_NODE,
            f"未找到 {missing}（PATH 中不存在）",
            "请安装 Node.js 18+（https://nodejs.org），安装后重开终端再试。",
        )
    version = subprocess.run(
        [node, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    ok("Node", version)
    return npm


def check_frontend_deps() -> None:
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.is_dir() or not any(node_modules.iterdir()):
        raise StartupError(
            EXIT_FRONTEND_DEPS,
            "前端依赖未安装（frontend/node_modules 不存在或为空）",
            "请执行：cd frontend && npm install",
        )
    ok("前端依赖", "frontend/node_modules 已就绪")


def check_env(env_file: Path) -> None:
    if env_file.is_file():
        ok(".env", str(env_file.relative_to(PROJECT_ROOT)))
        return
    raise StartupError(
        EXIT_ENV,
        f".env 缺失：{env_file}",
        "请执行：copy .env.example .env（Windows）后填写 DASHSCOPE_API_KEY。"
        "如确需跳过本检查，加 --skip-env-check。",
    )


def check_data_files() -> None:
    required = {
        PROJECT_ROOT / "db" / "ecommerce.db": "python scripts/init_db.py",
        PROJECT_ROOT / "db" / "app.db": "python scripts/init_auth_db.py",
    }
    missing = [(path, cmd) for path, cmd in required.items() if not path.is_file()]
    if missing:
        detail = "；".join(f"{p.name}（执行 {c}）" for p, c in missing)
        raise StartupError(
            EXIT_DATA,
            f"数据文件缺失：{detail}",
            "登录与业务查询都依赖这两个库；请先执行上面的初始化脚本。",
        )
    ok("数据文件", "db/ecommerce.db + db/app.db")


def port_in_use(port: int) -> bool:
    """IPv4 与 IPv6 **都要查**。

    实测（本机，2026-09-28）：Vite dev server 监听的是 `[::1]:5173`（IPv6），
    只探测 `127.0.0.1` 会得出"端口空闲"的结论，于是脚本会启动第二个前端，
    而用户访问 5173 看到的仍是旧服务 —— 一个比报错更难查的失败。
    """
    targets = (
        (socket.AF_INET, ("127.0.0.1", port)),
        (socket.AF_INET6, ("::1", port)),
    )
    for family, address in targets:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex(address) == 0:
                    return True
        except OSError:
            continue
    return False


def check_ports(backend_port: int, frontend_port: int) -> None:
    """端口占用预检。端口传 0 表示"本次不启动该服务"，跳过检查。"""
    busy: list[str] = []
    if backend_port and port_in_use(backend_port):
        busy.append(
            f"后端端口 {backend_port} 已被占用（--backend-port {backend_port + 1} 可换端口）"
        )
    if frontend_port and port_in_use(frontend_port):
        busy.append(
            f"前端端口 {frontend_port} 已被占用（--frontend-port {frontend_port + 1} 可换端口）"
        )
    if busy:
        raise StartupError(
            EXIT_PORT,
            "端口被占用：\n         - " + "\n         - ".join(busy),
            "请先停掉占用进程（Windows: netstat -ano | findstr :8000），或换端口重试。",
        )
    checked = " / ".join(str(p) for p in (backend_port, frontend_port) if p)
    ok("端口", f"{checked} 均空闲")


# ---------- 启动 ----------


def _pump(name: str, stream, process: Process, echo: bool) -> None:
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", errors="replace").rstrip()
        process.tail.append(line)
        if echo:
            say(f"[{name}] {line}")
    stream.close()


def spawn(
    name: str,
    cmd: list[str],
    cwd: Path,
    *,
    echo: bool,
    log_file: Path | None = None,
) -> Process:
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_file, "wb")
        popen = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=_detached_flags(),
        )
        return Process(name=name, popen=popen)

    popen = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=_new_group_flag(),
    )
    process = Process(name=name, popen=popen)
    assert popen.stdout is not None
    threading.Thread(
        target=_pump, args=(name, popen.stdout, process, echo), daemon=True
    ).start()
    return process


def split_command(text: str) -> list[str]:
    """拆分 `--backend-cmd` / `--frontend-cmd`。

    ⚠️ 不能直接用 `shlex.split`：POSIX 模式下反斜杠是转义符，会把
    `F:\\基于 Text2SQL ...\\python.exe` 拆成 `F:基于`（实测）。
    Windows 上用非 POSIX 模式（反斜杠原样保留、引号保留）再手工去掉引号；
    含空格的路径需要自己加引号。
    """
    if os.name == "nt":
        return [token.strip('"') for token in shlex.split(text, posix=False)]
    return shlex.split(text)


def _new_group_flag() -> int:
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0


def _detached_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )


def wait_healthy(url: str, timeout: float, backend: Process) -> bool:
    """轮询 /api/health；后端进程若先退出，立刻判定启动失败。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过代理
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if backend.popen.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def wait_port(port: int, timeout: float, process: Process) -> bool:
    """等前端端口真正开始监听（Vite 冷启动需要几秒）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.popen.poll() is not None:
            return False
        if port_in_use(port):
            return True
        time.sleep(0.3)
    return False


def address_block(
    backend_port: int | None, frontend_port: int | None, health: str
) -> str:
    lines = ["", "=" * 62]
    lines.append(
        f"Backend : http://127.0.0.1:{backend_port}" if backend_port else "Backend : （未启动）"
    )
    lines.append(
        f"Frontend: http://localhost:{frontend_port}" if frontend_port else "Frontend: （未启动）"
    )
    lines.append(f"Health  : {health}")
    if backend_port:
        lines.append(f"API 文档: http://127.0.0.1:{backend_port}/docs")
    lines.append("=" * 62)
    return "\n".join(lines)


# ---------- 主流程 ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="正式启动入口：预检 → 启动 Backend 8000 + Frontend 5173 → 健康检查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--env-file", default=".env", help="相对项目根目录的 .env 路径")
    parser.add_argument("--health-timeout", type=float, default=60.0, help="健康检查等待秒数")
    parser.add_argument("--check-only", action="store_true", help="只做预检，不启动任何进程")
    parser.add_argument("--detach", action="store_true", help="后台启动并写 PID 文件后退出")
    parser.add_argument(
        "--only",
        choices=("all", "backend", "frontend"),
        default="all",
        help="只启动其中一个服务（默认 all）。用于「只重启后端」这类场景。",
    )
    parser.add_argument("--skip-env-check", action="store_true", help="跳过 .env 存在性检查")
    parser.add_argument("--skip-data-check", action="store_true", help="跳过数据文件存在性检查")
    parser.add_argument(
        "--backend-cmd",
        default="",
        help="覆盖后端启动命令（高级 / 测试用；含空格的路径请加引号）",
    )
    parser.add_argument(
        "--frontend-cmd",
        default="",
        help="覆盖前端启动命令（高级 / 测试用；含空格的路径请加引号）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    want_backend = args.only in ("all", "backend")
    want_frontend = args.only in ("all", "frontend")

    npm: str | None = None
    try:
        say("=" * 62)
        say("Text2SQL 电商智能数据分析 Agent — 正式启动")
        say("=" * 62)
        check_python()
        if want_backend:
            check_backend_deps()
        if want_frontend:
            npm = check_node()
            check_frontend_deps()
        if args.skip_env_check:
            warn(".env", "已跳过检查（--skip-env-check）")
        else:
            check_env(PROJECT_ROOT / args.env_file)
        if args.skip_data_check:
            warn("数据文件", "已跳过检查（--skip-data-check）")
        else:
            check_data_files()
        check_ports(
            args.backend_port if want_backend else 0,
            args.frontend_port if want_frontend else 0,
        )
    except StartupError as err:
        say("")
        fail(err.message)
        if err.hint:
            say(f"         提示：{err.hint}")
        say("")
        say("启动已中止：以上问题修复后请重新执行本脚本。")
        return err.code

    if args.check_only:
        say("")
        say("预检全部通过（--check-only：未启动任何进程）。")
        return EXIT_OK

    backend_cmd = (
        split_command(args.backend_cmd)
        if args.backend_cmd
        else [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.backend_port),
        ]
    )
    # --strictPort：端口被占用时**报错退出**，绝不静默换到 5174
    # （否则用户访问 5173 会看到别人的服务，且毫无提示）
    frontend_cmd = (
        split_command(args.frontend_cmd)
        if args.frontend_cmd
        else [npm or "npm", "run", "dev", "--", "--port", str(args.frontend_port), "--strictPort"]
    )

    say("")
    say("启动：")
    backend: Process | None = None
    frontend: Process | None = None

    if want_backend:
        try:
            backend = spawn(
                "backend",
                backend_cmd,
                BACKEND_DIR,
                echo=not args.detach,
                log_file=(LOGS_DIR / "backend.log") if args.detach else None,
            )
        except OSError as err:
            fail(f"Backend 启动失败：无法执行 {backend_cmd[0]}（{err.strerror or err}）")
            return EXIT_BACKEND_FAILED
        ok("Backend", f"PID {backend.popen.pid} → 127.0.0.1:{args.backend_port}")
    else:
        warn("Backend", "已跳过（--only frontend）")

    if want_frontend:
        try:
            frontend = spawn(
                "frontend",
                frontend_cmd,
                FRONTEND_DIR,
                echo=not args.detach,
                log_file=(LOGS_DIR / "frontend.log") if args.detach else None,
            )
        except OSError as err:
            fail(f"Frontend 启动失败：无法执行 {frontend_cmd[0]}（{err.strerror or err}）")
            _terminate(backend)
            return EXIT_FRONTEND_FAILED
        ok("Frontend", f"PID {frontend.popen.pid} → localhost:{args.frontend_port}")
    else:
        warn("Frontend", "已跳过（--only backend）")

    if backend is not None:
        health_url = f"http://127.0.0.1:{args.backend_port}/api/health"
        say("")
        say(f"健康检查：{health_url}（最多等待 {args.health_timeout:.0f}s）")
        if not wait_healthy(health_url, args.health_timeout, backend):
            say("")
            if backend.popen.poll() is not None:
                fail(f"Backend 启动失败（进程已退出，退出码 {backend.popen.returncode}）")
            else:
                fail("Backend 健康检查超时（进程仍在运行但 /api/health 未返回 200）")
            if backend.tail_text():
                say("        后端最后输出：")
                for line in list(backend.tail)[-TAIL_LINES:]:
                    say(f"          {line}")
            _terminate(backend)
            _terminate(frontend)
            return EXIT_BACKEND_FAILED

    if frontend is not None:
        if frontend.popen.poll() is not None:
            say("")
            fail(f"Frontend 启动失败（进程已退出，退出码 {frontend.popen.returncode}）")
            if frontend.tail_text():
                say("        前端最后输出：")
                for line in list(frontend.tail)[-TAIL_LINES:]:
                    say(f"          {line}")
            _terminate(backend)
            return EXIT_FRONTEND_FAILED

        say(f"等待前端监听 {args.frontend_port}…")
        if not wait_port(args.frontend_port, min(30.0, args.health_timeout), frontend):
            say("")
            fail(f"Frontend 启动失败：{args.frontend_port} 一直未开始监听")
            if frontend.tail_text():
                say("        前端最后输出：")
                for line in list(frontend.tail)[-TAIL_LINES:]:
                    say(f"          {line}")
            _terminate(backend)
            _terminate(frontend)
            return EXIT_FRONTEND_FAILED

    say(
        address_block(
            args.backend_port if backend is not None else None,
            args.frontend_port if frontend is not None else None,
            "OK" if backend is not None else "SKIPPED（--only backend 未启动后端）",
        )
    )

    if args.detach:
        _write_pid_file(backend, frontend, args)
        say(f"已后台启动；PID 写入 {PID_FILE.relative_to(PROJECT_ROOT)}")
        say("停止：python scripts/stop_dev.py")
        return EXIT_OK

    say("按 Ctrl+C 停止服务。")
    running = [p for p in (backend, frontend) if p is not None]
    try:
        while True:
            time.sleep(0.5)
            for process in running:
                if process.popen.poll() is not None:
                    fail(f"{process.name} 已退出（退出码 {process.popen.returncode}）")
                    for line in list(process.tail)[-TAIL_LINES:]:
                        say(f"          {line}")
                    _terminate(backend)
                    _terminate(frontend)
                    return (
                        EXIT_BACKEND_FAILED
                        if process.name == "backend"
                        else EXIT_FRONTEND_FAILED
                    )
    except KeyboardInterrupt:
        say("")
        say("收到 Ctrl+C，正在停止服务…")
        _terminate(backend)
        _terminate(frontend)
        say("已停止。")
        return EXIT_OK


def _write_pid_file(backend: Process | None, frontend: Process | None, args) -> None:
    """写 PID 文件；`--only` 模式下与已有记录**合并**，不丢掉另一个服务的 PID。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if PID_FILE.is_file():
        try:
            data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if backend is not None:
        data["backend_pid"] = backend.popen.pid
        data["backend_port"] = args.backend_port
    if frontend is not None:
        data["frontend_pid"] = frontend.popen.pid
        data["frontend_port"] = args.frontend_port
    PID_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _terminate(process: Process | None) -> None:
    """终止进程**树**。

    只用 `Popen.terminate()` 会留下孤儿：前端的实际链路是
    `npm(node) → cmd.exe → vite(node)`，杀掉 npm 那一层，vite 会继续占着 5173。
    """
    if process is None or process.popen.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.popen.pid), "/T", "/F"],
            capture_output=True,
            errors="replace",
            check=False,
        )
    else:
        process.popen.terminate()
    try:
        process.popen.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.popen.kill()


if __name__ == "__main__":
    raise SystemExit(main())
