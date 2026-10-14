"""`/api/health` 的职责边界（第十阶段 P0-4 / §十）。

任务书 §十 的要求是：`/api/health` 只表达 **Backend / Database / Runtime 配置**，
**不得**让 `llm = configured` 被 UI 翻译成 `LLM = available`；
真实 LLM 可用性只能由 `/api/agent/analyze` 的实际请求结果体现。

"不得"必须可执行，否则只是文档里的一句话。这里把两条变成会响的断言：

1. **健康检查不得发起任何外部网络请求** —— 用 socket 层护栏证明，
   而不是相信 docstring 里写的"不产生任何网络请求"；
2. **响应体里不得出现"可用性"字段/措辞** —— 只允许 provider / model 这类配置信息。

两条都配了反向自查（否则护栏可能只是"没生效"而不是"没违规"）。
"""

from __future__ import annotations

import json
import socket

from fastapi.testclient import TestClient

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


def _install_egress_guard(monkeypatch) -> list[str]:
    """拦截所有非本地 connect，记录被尝试的地址。"""
    real_connect = socket.socket.connect
    attempts: list[str] = []

    def guarded_connect(self, address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in LOCAL_HOSTS:
            attempts.append(f"{host}:{address[1] if isinstance(address, tuple) else '?'}")
            raise AssertionError(f"/api/health 尝试对外连接：{attempts[-1]}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return attempts


def test_health_makes_no_outbound_network_call(client: TestClient, monkeypatch) -> None:
    """健康检查只读本地库 + 本地配置，绝不打上游。"""
    attempts = _install_egress_guard(monkeypatch)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert attempts == [], f"健康检查发起了外部连接：{attempts}"


def test_egress_guard_actually_blocks(monkeypatch) -> None:
    """反向自查：护栏必须真的拦得住，否则上一条是"假绿"。"""
    _install_egress_guard(monkeypatch)

    try:
        socket.create_connection(("example.com", 443), timeout=1)
    except AssertionError as err:
        assert "尝试对外连接" in str(err)
    else:
        raise AssertionError("护栏未生效：对外连接居然成功了")


def test_health_llm_field_is_configuration_only(client: TestClient) -> None:
    """`llm` 字段只允许承载「配置」，不得承载「可用性」。"""
    body = client.get("/api/health").json()

    llm = body.get("llm")
    if llm is not None:
        assert set(llm.keys()) <= {"provider", "model"}, (
            f"llm 字段出现了配置以外的键：{sorted(set(llm.keys()) - {'provider', 'model'})}"
        )

    # 整份响应里不得出现"可用 / available / reachable"这类承诺
    text = json.dumps(body, ensure_ascii=False).lower()
    for forbidden in ("available", "reachable", "可用"):
        assert forbidden not in text, f"健康检查响应体出现了可用性措辞：{forbidden}"


def test_health_status_word_refers_to_service_and_database_only(client: TestClient) -> None:
    """`status: ok` 的语义边界：只承诺"服务在 + 库可读"，不承诺 LLM。"""
    body = client.get("/api/health").json()

    assert body["status"] in {"ok", "degraded"}
    assert body["database"]["status"] in {"ok", "error"}
    # llm 为 null 时 status 仍可以是 ok —— 这正是"配置缺失 ≠ 服务不可用"
    assert "llm" in body
