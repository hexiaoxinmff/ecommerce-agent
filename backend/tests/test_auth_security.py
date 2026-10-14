"""认证安全原语测试（Task37-3 / P2）。

覆盖任务 §九 要求的 14 类行为：哈希非明文、同密码双哈希不同、
verify 正确/错误/malformed/低迭代/短盐、token 唯一性与熵、token hash
稳定性/区分度/非明文、空口令与非字符串参数拒绝。
另含与 P1 appdb 的端到端往返（真实哈希经 SQLite 存取后 verify 通过）。
"""

import base64
import re

import pytest

from app.auth.security import (
    DKLEN,
    MAX_PBKDF2_ITERATIONS,
    MIN_PBKDF2_ITERATIONS,
    PBKDF2_ITERATIONS,
    SALT_BYTES,
    TOKEN_ENTROPY_BYTES,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

# ---------- 构造工具 ----------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _make_encoded(
    *,
    algo: str = "pbkdf2_sha256",
    iterations: int | str = PBKDF2_ITERATIONS,
    salt: bytes | None = None,
    derived: bytes | None = None,
) -> str:
    """按存储格式拼装编码哈希（默认字段合法，可逐项注入异常）。"""
    salt_b64 = _b64(salt if salt is not None else b"x" * SALT_BYTES)
    derived_b64 = _b64(derived if derived is not None else b"y" * DKLEN)
    return f"{algo}${iterations}${salt_b64}${derived_b64}"


# ---------- 口令哈希 ----------


def test_hash_password_returns_encoded_not_plaintext() -> None:
    encoded = hash_password("S3cret!口令")
    assert encoded != "S3cret!口令"
    parts = encoded.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert parts[1] == str(PBKDF2_ITERATIONS)
    # salt / derived 均为 base64url 文本
    assert re.fullmatch(r"[A-Za-z0-9_\-]+={0,2}", parts[2])
    assert re.fullmatch(r"[A-Za-z0-9_\-]+={0,2}", parts[3])


def test_same_password_hashes_differ() -> None:
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2  # 盐随机，两次必然不同
    assert verify_password("same-password", h1) is True
    assert verify_password("same-password", h2) is True


def test_verify_correct_password_true() -> None:
    encoded = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", encoded) is True


def test_verify_wrong_password_false() -> None:
    encoded = hash_password("correct-horse-battery")
    assert verify_password("wrong-password", encoded) is False


def test_verify_unicode_password_roundtrip() -> None:
    encoded = hash_password("中文密码！123")
    assert verify_password("中文密码！123", encoded) is True
    assert verify_password("中文密码！124", encoded) is False


@pytest.mark.parametrize(
    "bad_hash",
    [
        "",
        "not-a-hash",
        "a$b$c",  # 字段数不足
        "a$b$c$d$e",  # 字段数过多
        "pbkdf2_sha512$600000$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb",  # 算法标签不符
        "pbkdf2_sha256$abc$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb",  # 迭代数非数字
        "pbkdf2_sha256$600000.0$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb",  # 迭代数是浮点
        "pbkdf2_sha256$ 600000$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb",  # 迭代数带空白
        "pbkdf2_sha256$-600000$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb",  # 负数
        "pbkdf2_sha256$$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb",  # 迭代数为空
        "pbkdf2_sha256$600000$$bbbbbbbbbbbbbbbb",  # 盐为空
        "pbkdf2_sha256$600000$aaaaaaaaaaaaaaaa$",  # 派生值为空
        "pbkdf2_sha256$600000$@@@@@@@@@@@@@@@@$bbbbbbbbbbbbbbbb",  # 盐非法 base64url
        "pbkdf2_sha256$600000$aaaaaaaaaaaaaaaa$@@@@@@@@@@@@@@@@",  # 派生值非法 base64url
        "pbkdf2_sha256$600000$aaaaaaaaaaaaaaaa$bbbbbbbbbbbbbbbb$extra",  # 尾部注入
    ],
)
def test_verify_malformed_encoded_hash_false(bad_hash: str) -> None:
    assert verify_password("any-password", bad_hash) is False


def test_verify_rejects_iterations_below_minimum() -> None:
    # 599,999 次迭代：差一次也不行（安全下限硬拒绝）
    encoded = _make_encoded(iterations=MIN_PBKDF2_ITERATIONS - 1)
    assert verify_password("any-password", encoded) is False


def test_verify_rejects_iterations_above_maximum() -> None:
    # 天文数字迭代数：防 DoS，直接拒绝
    encoded = _make_encoded(iterations=MAX_PBKDF2_ITERATIONS + 1)
    assert verify_password("any-password", encoded) is False


def test_verify_rejects_short_salt() -> None:
    encoded = _make_encoded(salt=b"short-salt")  # 10 bytes < 16
    assert verify_password("any-password", encoded) is False


def test_verify_rejects_wrong_derived_length() -> None:
    encoded = _make_encoded(derived=b"0" * 16)  # 16 bytes != 32
    assert verify_password("any-password", encoded) is False


def test_password_length_and_type_guards() -> None:
    with pytest.raises(ValueError):
        hash_password("")  # 空
    with pytest.raises(ValueError):
        hash_password("   ")  # 纯空白
    with pytest.raises(ValueError):
        hash_password("x" * 1025)  # 超长
    with pytest.raises(TypeError):
        hash_password(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hash_password(12345)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hash_password(b"bytes-password")  # type: ignore[arg-type]

    # verify 侧：异常输入一律 False（含非字符串），绝不抛出"验证通过"
    encoded = hash_password("valid-password")
    assert verify_password("", encoded) is False
    assert verify_password("   ", encoded) is False
    assert verify_password(None, encoded) is False  # type: ignore[arg-type]
    assert verify_password(12345, encoded) is False  # type: ignore[arg-type]
    assert verify_password("valid-password", None) is False  # type: ignore[arg-type]
    assert verify_password("valid-password", 123) is False  # type: ignore[arg-type]


# ---------- session token ----------


def test_generate_session_token_unique() -> None:
    tokens = {generate_session_token() for _ in range(100)}
    assert len(tokens) == 100


def test_session_token_entropy_meets_requirement() -> None:
    token = generate_session_token()
    # 32 bytes 熵 → 43 字符 URL 安全文本（无填充）
    assert len(token) >= TOKEN_ENTROPY_BYTES * 8 // 6
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    assert len(decoded) == TOKEN_ENTROPY_BYTES


def test_hash_session_token_stable_and_distinct() -> None:
    token = generate_session_token()
    assert hash_session_token(token) == hash_session_token(token)  # 稳定
    other = generate_session_token()
    assert hash_session_token(token) != hash_session_token(other)  # 区分度


def test_session_token_hash_is_not_plaintext() -> None:
    token = generate_session_token()
    digest = hash_session_token(token)
    assert digest != token
    assert re.fullmatch(r"[0-9a-f]{64}", digest)  # SHA-256 固定 64 位小写 hex


def test_session_token_hash_input_guards() -> None:
    with pytest.raises(TypeError):
        hash_session_token(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        hash_session_token(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        hash_session_token("")


# ---------- 与 P1 appdb 的端到端往返 ----------


def test_password_hash_roundtrip_through_appdb(tmp_path, monkeypatch) -> None:
    """真实哈希经 appdb 存取后仍可 verify（不改 appdb 签名，只用其现有函数）。"""
    from app.core import config
    from app.db import appdb

    monkeypatch.setattr(config, "APP_DB_PATH", tmp_path / "roundtrip" / "app.db")
    appdb.init_app_db()

    appdb.create_user("roundtrip-user", "rt@example.com", hash_password("db-roundtrip"))
    row = appdb.get_user_by_username("roundtrip-user")
    assert row is not None
    assert row["password_hash"] != "db-roundtrip"  # 库中无明文
    assert verify_password("db-roundtrip", row["password_hash"]) is True
    assert verify_password("wrong", row["password_hash"]) is False
