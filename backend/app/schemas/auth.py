"""认证 API 相关 Pydantic 模型（Task37-4 / P3）。

输入模型在 API 层完成清洗与校验（trim、非空、长度上限、基础 email 格式），
密码强度策略不在此处展开（哈希与长度守卫由 P2 security.py 承担）。
响应模型刻意不包含 password_hash / token_hash 等任何内部安全字段。
"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# username / email 上限：64 / 254 为常见通行约束（RFC 5321 邮箱上限 254）
USERNAME_MAX_LENGTH = 64
EMAIL_MAX_LENGTH = 254
# password 上限与 security.MAX_PASSWORD_LENGTH 对齐，防超长输入拖慢 KDF
PASSWORD_MAX_LENGTH = 1024

# 基础 email 格式：非空白@非空白.非空白（MVP 不做完整 RFC 校验）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    """POST /api/auth/register 请求体。"""

    username: str = Field(..., min_length=1, max_length=USERNAME_MAX_LENGTH)
    email: str = Field(..., min_length=3, max_length=EMAIL_MAX_LENGTH)
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("username 不能为空")
        return cleaned

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("email 不能为空")
        if _EMAIL_RE.fullmatch(cleaned) is None:
            raise ValueError("email 格式不正确")
        return cleaned

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        # password 不 trim（保留内部空格），但拒绝空串与纯空白
        if not value or not value.strip():
            raise ValueError("password 不能为空或纯空白")
        return value


class LoginRequest(BaseModel):
    """POST /api/auth/login 请求体。"""

    username: str = Field(..., min_length=1, max_length=USERNAME_MAX_LENGTH)
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("username 不能为空")
        return cleaned

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("password 不能为空或纯空白")
        return value


class UserPublic(BaseModel):
    """登录响应中的用户摘要（无任何安全字段）。"""

    id: int
    username: str
    email: str


class UserOut(UserPublic):
    """注册 / me 响应中的用户信息。"""

    is_active: bool


class LoginResponse(BaseModel):
    """POST /api/auth/login 响应体。

    access_token 是**原始令牌**，只出现在本响应中；数据库只保存
    hash_session_token(token) 的结果。
    """

    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: UserPublic
