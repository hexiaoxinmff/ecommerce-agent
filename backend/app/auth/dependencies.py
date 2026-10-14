"""Bearer Token 认证依赖（Task37-4 / P3）。

统一职责链（get_current_session）：Bearer token → hash_session_token
→ auth_session 查询 → 过期检查 → auth_user 查询 → is_active 检查。

- get_current_session：返回 (session, user)，logout 需要"删除当前 token
  对应的那条会话"（不影响该用户在其他端登录的会话）；
- get_current_user：仅返回 user，P4 起 Agent API 直接
  ``user = Depends(get_current_user)`` 复用，不在各路由重复认证逻辑。

所有失败（无 header / 非 Bearer / token 不存在 / 会话过期 / 用户缺失 /
用户 inactive）对外统一 401 {"detail": "Invalid credentials"}，
不区分具体原因，抑制用户枚举。

本模块不记录任何 Authorization header 内容，不记录原始 token。
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import hash_session_token
from app.core import config
from app.db import appdb

# auto_error=False：header 缺失 / 非 Bearer 时返回 None，由本模块
# 统一转成 401（避免 fastapi 默认 403 及差异化文案）。
_bearer_scheme = HTTPBearer(auto_error=False)

# 统一认证失败响应：带 WWW-Authenticate 提示 Bearer 方案
INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def _session_expired(expires_at: str) -> bool:
    """解析 expires_at（ISO 8601）并与当前 UTC 时刻比较。

    解析失败视为过期（异常数据宁可拒绝，不可放行）。
    """
    try:
        expires = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
):
    """FastAPI 依赖：校验 Bearer token，返回 (session_row, user_row)。

    Raises:
        HTTPException: 401（统一文案 "Invalid credentials"，见模块 docstring）。
    """
    if credentials is None:
        raise INVALID_CREDENTIALS
    token = credentials.credentials
    if not token:
        raise INVALID_CREDENTIALS

    session = appdb.get_session(hash_session_token(token))
    if session is None:
        raise INVALID_CREDENTIALS
    if _session_expired(session["expires_at"]):
        raise INVALID_CREDENTIALS

    user = appdb.get_user_by_id(session["user_id"])
    if user is None or not user["is_active"]:
        raise INVALID_CREDENTIALS
    return session, user


def get_current_user(
    session_and_user=Depends(get_current_session),
):
    """FastAPI 依赖：仅返回当前用户行（供 P4 Agent API 等复用）。"""
    _, user = session_and_user
    return user


def session_expiry_iso() -> str:
    """按 AUTH_SESSION_TTL_SECONDS 计算新会话的过期时刻（ISO 8601 UTC）。"""
    return (
        datetime.now(timezone.utc)
        + timedelta(seconds=config.AUTH_SESSION_TTL_SECONDS)
    ).isoformat(timespec="seconds")
