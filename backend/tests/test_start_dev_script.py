"""启动脚本测试（第十阶段 P0-3）。

覆盖任务书 §十一 要求的启动场景：

    冷启动（预检） / 正常启动 / 端口冲突 / 环境缺失 / 后端失败

断言用**退出码**而不是中文文案 —— 文案会改，退出码是契约（见 start_dev.py 头部）。

⚠️ 为什么放在 `backend/tests/`：项目规定的标准测试命令是 `pytest backend/tests`，
放这里才能保证"改了启动脚本忘了改文档/测试"在默认命令下就会变红。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import start_dev  # noqa: E402
import stop_dev  # noqa: E402

VENV_PYTHON = sys.executable
START_SCRIPT = PROJECT_ROOT / "scripts" / "start_dev.py"


def free_port() -> int:
    """让操作系统分配一个当前空闲的端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_start(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        [VENV_PYTHON, str(START_SCRIPT), *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _no_proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------- 预检 / 冷启动 ----------


def test_preflight_passes_on_free_ports() -> None:
    """冷启动预检：全部检查通过，且**不启动任何进程**。"""
    result = run_start(
        "--check-only",
        "--backend-port",
        str(free_port()),
        "--frontend-port",
        str(free_port()),
    )
    assert result.returncode == start_dev.EXIT_OK, result.stdout + result.stderr
    assert "预检全部通过" in result.stdout
    # --check-only 不得启动任何进程
    assert "启动：" not in result.stdout


def test_port_conflict_returns_exit_7() -> None:
    """端口被占用 → 明确报错 + 退出码 7（不是静默换端口）。"""
    backend_port = free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", backend_port))
        listener.listen(1)

        result = run_start(
            "--check-only",
            "--backend-port",
            str(backend_port),
            "--frontend-port",
            str(free_port()),
        )

    assert result.returncode == start_dev.EXIT_PORT, result.stdout + result.stderr
    assert "端口被占用" in result.stdout
    assert str(backend_port) in result.stdout


def test_ipv6_only_listener_is_detected() -> None:
    """回归：只监听 `::1` 的进程也必须被判定为"端口被占用"。

    实测踩过：Vite dev server 绑的是 `[::1]:5173`，只探测 `127.0.0.1`
    会得出"端口空闲"，于是脚本再起一个前端，而用户访问 5173 看到的仍是旧服务。
    """
    ipv6_port = free_port()
    listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("::1", ipv6_port))
        listener.listen(1)
    except OSError:
        listener.close()
        pytest.skip("本机不支持 IPv6 回环，跳过")

    try:
        result = run_start(
            "--check-only",
            "--backend-port",
            str(ipv6_port),
            "--frontend-port",
            str(free_port()),
        )
    finally:
        listener.close()

    assert result.returncode == start_dev.EXIT_PORT, result.stdout + result.stderr
    assert "端口被占用" in result.stdout


# ---------- 环境缺失 ----------


def test_missing_env_returns_exit_6(tmp_path: Path, monkeypatch) -> None:
    """`.env` 缺失 → 退出码 6 + 给出复制命令。"""
    monkeypatch.setattr(start_dev, "PROJECT_ROOT", tmp_path)
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "ecommerce.db").write_bytes(b"")
    (tmp_path / "db" / "app.db").write_bytes(b"")

    code = start_dev.main(
        [
            "--check-only",
            "--env-file",
            ".env",
            "--backend-port",
            str(free_port()),
            "--frontend-port",
            str(free_port()),
        ]
    )
    assert code == start_dev.EXIT_ENV


def test_missing_data_files_returns_exit_8(tmp_path: Path, monkeypatch) -> None:
    """数据文件缺失 → 退出码 8（登录与业务查询都依赖它们）。"""
    monkeypatch.setattr(start_dev, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("LLM_PROVIDER=bailian\n", encoding="utf-8")

    code = start_dev.main(
        [
            "--check-only",
            "--backend-port",
            str(free_port()),
            "--frontend-port",
            str(free_port()),
        ]
    )
    assert code == start_dev.EXIT_DATA


def test_skip_env_check_downgrades_to_warning(tmp_path: Path, monkeypatch) -> None:
    """`--skip-env-check` 是有意的逃生口：警告但不中止。"""
    monkeypatch.setattr(start_dev, "PROJECT_ROOT", tmp_path)
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "ecommerce.db").write_bytes(b"")
    (tmp_path / "db" / "app.db").write_bytes(b"")

    code = start_dev.main(
        [
            "--check-only",
            "--skip-env-check",
            "--backend-port",
            str(free_port()),
            "--frontend-port",
            str(free_port()),
        ]
    )
    assert code == start_dev.EXIT_OK


# ---------- 后端启动失败 ----------


def test_unlaunchable_backend_returns_exit_9() -> None:
    """后端命令根本无法执行（可执行文件不存在）→ 退出码 9，而不是抛 traceback。"""
    result = run_start(
        "--backend-port",
        str(free_port()),
        "--frontend-port",
        str(free_port()),
        "--health-timeout",
        "5",
        "--backend-cmd",
        "definitely-not-a-real-binary-xyz",
    )
    assert result.returncode == start_dev.EXIT_BACKEND_FAILED, result.stdout + result.stderr
    assert "Backend 启动失败" in result.stdout


def test_backend_dying_immediately_returns_exit_9() -> None:
    """后端进程秒退 → 必须被识别为"启动失败"，并把它的输出打出来。"""
    result = run_start(
        "--backend-port",
        str(free_port()),
        "--frontend-port",
        str(free_port()),
        "--health-timeout",
        "10",
        "--backend-cmd",
        f'"{VENV_PYTHON}" -c "import sys; print(\'BOOM-MARKER\'); sys.exit(3)"',
        # 用无害的睡眠进程代替真实前端：本用例只关心后端失败的识别与可解释性
        "--frontend-cmd",
        f'"{VENV_PYTHON}" -c "import time; time.sleep(30)"',
    )
    assert result.returncode == start_dev.EXIT_BACKEND_FAILED, result.stdout + result.stderr
    assert "Backend 启动失败" in result.stdout
    # 失败必须可解释：要能看到子进程自己的输出，而不是只有一句"失败了"
    assert "BOOM-MARKER" in result.stdout


# ---------- 正常启动（集成，最慢的一条） ----------


def test_normal_startup_serves_backend_and_frontend() -> None:
    """正常启动：后端 /api/health 200 + 前端端口开始监听 + 地址块输出正确。"""
    backend_port = free_port()
    frontend_port = free_port()
    try:
        result = run_start(
            "--backend-port",
            str(backend_port),
            "--frontend-port",
            str(frontend_port),
            "--detach",
            "--health-timeout",
            "90",
            timeout=240,
        )
        assert result.returncode == start_dev.EXIT_OK, result.stdout + result.stderr
        assert f"Backend : http://127.0.0.1:{backend_port}" in result.stdout
        assert f"Frontend: http://localhost:{frontend_port}" in result.stdout
        assert "Health  : OK" in result.stdout

        # 后端真的在服务
        opener = _no_proxy_opener()
        with opener.open(f"http://127.0.0.1:{backend_port}/api/health", timeout=10) as response:
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["status"] == "ok"
        assert payload["database"]["status"] == "ok"

        # 前端真的在服务（Vite 冷启动可能稍慢，轮询等待）
        deadline = time.monotonic() + 30
        served = False
        while time.monotonic() < deadline and not served:
            try:
                with opener.open(f"http://localhost:{frontend_port}/", timeout=5) as response:
                    served = response.status == 200
            except (urllib.error.URLError, OSError, TimeoutError):
                time.sleep(0.5)
        assert served, "前端端口未在 30s 内开始响应"

        # PID 文件必须与实际端口持有者可交叉验证
        pid_file = PROJECT_ROOT / "logs" / "start_dev_pids.json"
        data = json.loads(pid_file.read_text(encoding="utf-8"))
        assert data["backend_port"] == backend_port
        assert data["frontend_port"] == frontend_port
        assert stop_dev._pids_listening_on(backend_port), "后端端口上找不到监听进程"
    finally:
        subprocess.run(
            [VENV_PYTHON, str(PROJECT_ROOT / "scripts" / "stop_dev.py")],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            errors="replace",
            check=False,
        )


# ---------- 停止脚本的 PID 复用防线 ----------


def test_stop_refuses_pid_that_is_not_python_or_node(monkeypatch) -> None:
    """PID 复用防线：记录到的 PID 若已属于别的程序，必须拒绝终止。

    用一个必然存在但不是 python/node 的进程来验证（本测试自身就是 python，
    所以拿一个已知的 shell 类镜像名做替身更稳妥 —— 这里直接伪造 _image_name）。
    """
    monkeypatch.setattr(stop_dev, "_image_name", lambda _pid: "explorer.exe")
    assert stop_dev._stop(123456) == "refused"


def test_stop_treats_unknown_pid_as_skipped(monkeypatch) -> None:
    monkeypatch.setattr(stop_dev, "_image_name", lambda _pid: None)
    assert stop_dev._stop(123456) == "skipped"


def test_pids_listening_on_finds_real_holder() -> None:
    """按端口反查持有者必须能命中（stop_dev 靠它兜住 npm→cmd→node 的间接链）。"""
    port = free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(1)
        import os

        pids = stop_dev._pids_listening_on(port)
        assert os.getpid() in pids, f"未找到本进程 PID；实际：{pids}"
