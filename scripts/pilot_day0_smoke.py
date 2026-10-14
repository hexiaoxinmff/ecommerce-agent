"""Phase 16 Business Pilot · Day-0 冒烟（试点运维工具，不属于 backend/tests）。

目的：真实用户开跑前，验证「注册 → 登录 → 真实 LLM 分析 → Dashboard 口径核对 →
History 落库」这条用户第一天就会走的完整链路在当前环境是通的。

用法：
    python scripts/pilot_day0_smoke.py                    # 每日开机检查：只查 /api/health（零 LLM 成本）
    python scripts/pilot_day0_smoke.py --full             # Day-0 全链路（消耗 1 次 LLM 调用）
    python scripts/pilot_day0_smoke.py --full --base-url http://127.0.0.1:8765
    python scripts/pilot_day0_smoke.py --full --keep      # 保留冒烟账号与历史（默认清理）

退出码：0 = 全部通过；1 = 任一步失败。

纪律：
- 输出绝不包含 password / access_token（与后端 API 纪律一致）；
- 冒烟账号默认清理（query_history → auth_session → auth_user，外键顺序删除），
  与 Phase 15 E2E 冒烟纪律一致；--keep 仅供现场排查；
- 本脚本只验证与记录，不修改任何产品代码、不触碰业务库 db/ecommerce.db（全程只读）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
ANALYZE_TIMEOUT_S = 90.0   # 真实 LLM 调用留足余量
HTTP_TIMEOUT_S = 15.0
SMOKE_QUESTION = "本月销售额是多少？"   # Phase 15 E2E 同题，已知正确口径与预期值
TOLERANCE = 0.01

_result: dict = {"steps": [], "ok": False}


def _step(name: str, ok: bool, detail: dict | str) -> bool:
    _result["steps"].append({"step": name, "ok": ok, "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)}")
    return ok


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = HTTP_TIMEOUT_S,
) -> tuple[int, dict]:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        method=method,
        headers={"Content-Type": "application/json"},
        data=json.dumps(body).encode("utf-8") if body is not None else None,
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _cleanup_user(app_db_path: Path, user_id: int) -> int:
    """外键顺序删除冒烟用户的全部痕迹，返回删除的 history 行数。"""
    conn = sqlite3.connect(app_db_path)
    try:
        deleted_history = conn.execute(
            "DELETE FROM query_history WHERE user_id = ?", (user_id,)
        ).rowcount
        conn.execute("DELETE FROM auth_session WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM auth_user WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return deleted_history


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 16 Pilot Day-0 smoke")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--full", action="store_true", help="全链路冒烟（消耗 1 次 LLM 调用）")
    parser.add_argument("--keep", action="store_true", help="保留冒烟账号（默认清理）")
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "reports" / "phase16" / "pilot_day0_smoke_result.json"),
    )
    args = parser.parse_args()
    base_url = args.base_url

    _result["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _result["base_url"] = base_url
    _result["mode"] = "full" if args.full else "health-only"

    # ---- 1. health（每日开机检查；provider/model 只读展示，不发起 LLM 调用）----
    try:
        status, health = _request(base_url, "GET", "/api/health")
        llm = health.get("llm") or {}
        _result["health"] = {
            "status": health.get("status"),
            "database": (health.get("database") or {}).get("status"),
            "llm_provider": llm.get("provider"),
            "llm_model": llm.get("model"),
        }
        ok = (
            status == 200
            and health.get("status") == "ok"
            and (health.get("database") or {}).get("status") == "ok"
        )
        if not _step("health", ok, _result["health"]):
            _finish(args.out)
            return 1
    except Exception as exc:  # noqa: BLE001 — 冒烟脚本需把任何异常收敛为 FAIL
        _step("health", False, f"{type(exc).__name__}: {exc}")
        _finish(args.out)
        return 1

    if not args.full:
        _result["ok"] = True
        _finish(args.out)
        print("\n health-only 冒烟通过（未消耗 LLM 调用；--full 走真实全链路）")
        return 0

    # ---- 2. 注册冒烟账号（时间戳 + 随机后缀，避免 409 冲突）----
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    username = f"pilot_smoke_{stamp}_{uuid.uuid4().hex[:6]}"
    password = f"Sm0ke-{uuid.uuid4().hex}!"   # 只存在于本进程内存，绝不输出
    try:
        status, user = _request(
            base_url,
            "POST",
            "/api/auth/register",
            body={"username": username, "email": f"{username}@example.com", "password": password},
        )
        user_id = user.get("id")
        if not _step("register", status == 201 and isinstance(user_id, int), {"status": status, "user_id": user_id}):
            _finish(args.out)
            return 1
    except urllib.error.HTTPError as exc:
        _step("register", False, f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}")
        _finish(args.out)
        return 1
    except Exception as exc:  # noqa: BLE001
        _step("register", False, f"{type(exc).__name__}: {exc}")
        _finish(args.out)
        return 1

    # ---- 3. 登录（拿到 Bearer token；token 不落盘不输出）----
    try:
        status, login = _request(
            base_url, "POST", "/api/auth/login",
            body={"username": username, "password": password},
        )
        token = login.get("access_token") or ""
        _step("login", status == 200 and bool(token), {"status": status, "token_type": login.get("token_type")})
    except Exception as exc:  # noqa: BLE001
        _step("login", False, f"{type(exc).__name__}: {exc}")
        _cleanup_user(_app_db_path(), user_id)
        _finish(args.out)
        return 1

    # ---- 4. 真实 LLM 分析（Phase 15 E2E 同题）----
    analyze_ok, agent_value, data_as_of = False, None, ""
    try:
        t0 = time.perf_counter()
        status, agent = _request(
            base_url, "POST", "/api/agent/analyze",
            token=token, body={"question": SMOKE_QUESTION}, timeout=ANALYZE_TIMEOUT_S,
        )
        wall_ms = round((time.perf_counter() - t0) * 1000)
        result = agent.get("result") or {}
        exec_res = result.get("execution_result") or {}
        rows = exec_res.get("rows") or []
        data_as_of = agent.get("data_as_of") or ""
        if rows and rows[0]:
            first = rows[0][0]
            agent_value = float(first) if isinstance(first, (int, float)) else None
        analyze_ok = (
            status == 200
            and agent.get("success") is True
            and result.get("success") is True
            and exec_res.get("row_count", 0) >= 1
            and bool(result.get("generated_sql"))
            and agent_value is not None
        )
        _step(
            "agent_analyze",
            analyze_ok,
            {
                "question": SMOKE_QUESTION,
                "wall_ms": wall_ms,
                "total_time_ms": result.get("total_time_ms"),
                "agent_value": agent_value,
                "data_as_of": data_as_of,
                "sql_head": (result.get("generated_sql") or "")[:120],
            },
        )
    except Exception as exc:  # noqa: BLE001
        _step("agent_analyze", False, f"{type(exc).__name__}: {exc}")

    # ---- 5. Dashboard 口径核对（Agent == Dashboard，试点最关键的一致性）----
    if analyze_ok:
        try:
            status, overview = _request(base_url, "GET", "/api/insights/overview", token=token)
            month_sales_kpi = (overview.get("kpis") or {}).get("month_sales") or {}
            dash_value = month_sales_kpi.get("value")
            consistent = (
                isinstance(dash_value, (int, float))
                and agent_value is not None
                and abs(float(dash_value) - float(agent_value)) <= TOLERANCE
            )
            _step(
                "dashboard_consistency",
                consistent,
                {"agent": agent_value, "dashboard": dash_value, "tolerance": TOLERANCE},
            )
        except Exception as exc:  # noqa: BLE001
            _step("dashboard_consistency", False, f"{type(exc).__name__}: {exc}")
            analyze_ok = False

    # ---- 6. History 落库核对（Trace 保留契约）----
    history_ok = False
    try:
        status, history = _request(
            base_url, "GET", "/api/history?page=1&page_size=5", token=token
        )
        items = history.get("items") or []
        hit = next((h for h in items if h.get("question") == SMOKE_QUESTION), None)
        history_ok = (
            status == 200
            and hit is not None
            and bool(hit.get("sql"))
            and hit.get("success") is True
            and hit.get("total_time_ms") is not None
        )
        _step(
            "history_persisted",
            history_ok,
            {
                "found": hit is not None,
                "has_sql": bool(hit and hit.get("sql")),
                "total_time_ms": hit.get("total_time_ms") if hit else None,
                "history_total": history.get("total"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        _step("history_persisted", False, f"{type(exc).__name__}: {exc}")

    # ---- 7. 清理冒烟账号（--keep 保留供排查）----
    if args.keep:
        _step("cleanup", True, f"SKIPPED (--keep)；冒烟账号保留: {username}")
    else:
        try:
            deleted = _cleanup_user(_app_db_path(), user_id)
            _step("cleanup", deleted >= 1, {"deleted_history_rows": deleted, "account_removed": username})
        except Exception as exc:  # noqa: BLE001
            _step("cleanup", False, f"{type(exc).__name__}: {exc}（请手工清理账号 {username}）")

    _result["ok"] = analyze_ok and history_ok
    _finish(args.out)
    print(f"\nDay-0 全链路冒烟：{'通过' if _result['ok'] else '未通过'}（详见 {args.out}）")
    return 0 if _result["ok"] else 1


def _app_db_path() -> Path:
    from app.core import config

    return Path(config.APP_DB_PATH)


def _finish(out_path: str) -> None:
    _result["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
