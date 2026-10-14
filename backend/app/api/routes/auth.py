"""认证路由（Task37-4 / P3）。

- POST /api/auth/register  注册（201；username/email 冲突 409）
- POST /api/auth/login     登录（200；签发 Bearer access_token，库中只存 token_hash）
- GET  /api/auth/me        当前用户（200；Bearer 认证）
- POST /api/auth/logout    登出（204；删除服务端会话）

错误状态码约定：
- 认证失败（用户不存在 / 密码错误 / inactive / 会话缺失或过期 /
  header 缺失或非法）一律 401 {"detail": "Invalid credentials"}，
  统一文案抑制用户枚举（依赖见 app.auth.dependencies）；
- 注册 username / email 冲突 409；
- 请求体校验失败 422（pydantic）。

安全：明文 password 只在请求处理瞬间存在于内存，绝不 log；
access_token 原始值只出现在登录响应里，数据库只保存 token_hash；
任何响应不包含 password_hash / token_hash。
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import (
    INVALID_CREDENTIALS,
    get_current_session,
    get_current_user,
    session_expiry_iso,
)
from app.auth.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.db import appdb
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserOut,
    UserPublic,
)

router = APIRouter(tags=["auth"])

_CONFLICT_409 = status.HTTP_409_CONFLICT


def _user_out(row) -> UserOut:
    """sqlite3.Row -> UserOut（Row 不支持属性访问，显式按下标构造）。"""
    return UserOut(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        is_active=bool(row["is_active"]),
    )


@router.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册新用户（username/email 冲突返回 409）",
)
def register(request: RegisterRequest) -> UserOut:
    if appdb.get_user_by_username(request.username) is not None:
        raise HTTPException(status_code=_CONFLICT_409, detail="Username already registered")
    if appdb.get_user_by_email(request.email) is not None:
        raise HTTPException(status_code=_CONFLICT_409, detail="Email already registered")

    password_hash = hash_password(request.password)
    try:
        user_id = appdb.create_user(request.username, request.email, password_hash)
    except sqlite3.IntegrityError as exc:
        # 并发注册撞 UNIQUE 约束：转为与显式检查一致的 409，不泄漏 SQL 信息
        raise HTTPException(
            status_code=_CONFLICT_409, detail="Username or email already registered"
        ) from exc

    row = appdb.get_user_by_id(user_id)
    if row is None:  # 理论不可达（刚插入成功），防御性处理
        raise HTTPException(status_code=500, detail="User registration failed")
    return _user_out(row)


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="登录并签发 Bearer access_token（会话只存 token_hash）",
)
def login(request: LoginRequest) -> LoginResponse:
    user = appdb.get_user_by_username(request.username)
    # 用户不存在 / inactive / 密码错误 → 同一 401 文案，抑制用户枚举
    if user is None or not user["is_active"]:
        raise INVALID_CREDENTIALS
    if not verify_password(request.password, user["password_hash"]):
        raise INVALID_CREDENTIALS

    token = generate_session_token()
    token_hash = hash_session_token(token)
    expires_at = session_expiry_iso()
    appdb.create_session(user["id"], token_hash, expires_at)

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
        user=UserPublic(id=user["id"], username=user["username"], email=user["email"]),
    )


@router.get(
    "/auth/me",
    response_model=UserOut,
    summary="当前登录用户（Bearer 认证）",
)
def me(user=Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="登出（删除当前 token 对应的服务端会话）",
)
def logout(session_and_user=Depends(get_current_session)) -> None:
    # 只删除当前 token 对应的那条会话（用户在其他端的会话不受影响）；
    # 未认证 / 无效 token 由依赖统一 401，不向客户端区分删除细节。
    session, _user = session_and_user
    appdb.delete_session(session["token_hash"])
