"""停止 `scripts/start_dev.py --detach` 拉起的服务（第十阶段 P0-3）。

    python scripts/stop_dev.py

读取 `logs/start_dev_pids.json`，终止后端与前端进程树。可安全重复执行。

⚠️ 三个实测踩过的坑（都写在这里，免得下次再踩）：

1. **记录的 PID 不是持有端口的那个进程。**
   `npm run dev` 的实际链路是 `npm(node) → cmd.exe → vite(node)`，
   而 `.venv\\Scripts\\python.exe` 起的 uvicorn 还会再套一层解释器。
   实测：PID 文件记 23432（cmd.exe），真正监听 5175 的是 22148（node.exe）。
   ⇒ 只按记录的 PID 杀会留下"端口还占着"的幽灵。
   所以本脚本**同时**按端口反查真实持有者（`netstat -ano`）。

2. **不要靠 tasklist 的 message 文本判断"进程不存在"。**
   中文 Windows 下 "信息: 没有运行的任务匹配指定标准。" 会因编码不同而乱码，
   `startswith("INFO")` 之类的判据会静默失效。⇒ 判据改为**结构**：
   CSV 记录必然 5 个字段且镜像名以 `.exe` 结尾。

3. **PID 复用**：PID 文件放久了，那个号可能已属于别的进程。
   ⇒ 只终止镜像名为 python / node 的进程，其余一律拒绝。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PID_FILE = PROJECT_ROOT / "logs" / "start_dev_pids.json"

# 只允许终止这两类进程（PID 复用防线）。cmd.exe 不在列：
# 它是 npm 的包装壳，真正的服务是它下面的 node.exe。
ALLOWED_IMAGES = ("python", "node")


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, errors="replace", check=False)
    return result.stdout or ""


def _image_name(pid: int) -> str | None:
    """返回该 PID 的镜像名（小写）；不存在 / 无法判定返回 None。"""
    text = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]).strip()
    if not text:
        return None
    fields = [field.strip().strip('"') for field in text.splitlines()[0].split(",")]
    if len(fields) < 5:
        return None  # "信息: ..." / "INFO: ..." 之类，不是 CSV 记录
    name = fields[0].lower()
    return name if name.endswith(".exe") else None


def _pids_listening_on(port: int) -> list[int]:
    """按端口反查真实持有者（与 PID 文件互为交叉验证）。"""
    pids: set[int] = set()
    for line in _run(["netstat", "-ano"]).splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].rsplit(":", 1)[-1] == str(port):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    continue
    return sorted(pids)


def _stop(pid: int) -> str:
    """返回 'stopped' / 'skipped' / 'refused'。"""
    if os.name != "nt":
        try:
            os.kill(pid, 15)
        except OSError:
            return "skipped"
        return "stopped"

    image = _image_name(pid)
    if image is None:
        return "skipped"
    if not any(allowed in image for allowed in ALLOWED_IMAGES):
        return "refused"
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        errors="replace",
        check=False,
    )
    return "stopped"


def main() -> int:
    if not PID_FILE.is_file():
        print(f"没有找到 {PID_FILE}：没有本脚本拉起的服务需要停止。")
        return 0

    data = json.loads(PID_FILE.read_text(encoding="utf-8"))
    backend_port = int(data.get("backend_port", 0))
    frontend_port = int(data.get("frontend_port", 0))

    # 记录在案的 PID + 端口上的真实持有者（去重）
    targets: dict[int, str] = {}
    for name, key in (("backend", "backend_pid"), ("frontend", "frontend_pid")):
        pid = int(data.get(key, 0))
        if pid > 0:
            targets[pid] = name
    for name, port in (("backend", backend_port), ("frontend", frontend_port)):
        if port <= 0:
            continue
        for pid in _pids_listening_on(port):
            targets.setdefault(pid, name)

    if not targets:
        print("PID 文件里没有可用的 PID。")
    for pid, name in sorted(targets.items()):
        outcome = _stop(pid)
        if outcome == "stopped":
            print(f"  [STOP] {name} (PID {pid})")
        elif outcome == "refused":
            print(f"  [SKIP] {name} (PID {pid}) 不是 python/node，拒绝终止")
        else:
            print(f"  [SKIP] {name} (PID {pid}) 已不在运行")

    PID_FILE.unlink(missing_ok=True)
    print("已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
