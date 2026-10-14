"""认证安全原语（Task37-3 / P2）。

纯函数层，不接 FastAPI 路由、不接 Agent、不写库：
- hash_password / verify_password：PBKDF2-HMAC-SHA256 口令哈希与恒时校验；
- generate_session_token / hash_session_token：会话令牌生成与哈希。

安全边界（硬约束）：
1. 明文 password 只允许作为函数参数短暂存在：本模块绝不 print、log、
   写文件、写 SQLite、写环境变量或任何缓存；
2. 会话令牌原始值只存在于内存（登录成功后可返回给调用方用于 Set-Cookie，
   属 P3 职责），数据库 auth_session.token_hash 只保存 hash_session_token()
   的结果，绝不保存原始令牌；
3. verify_password 对一切异常输入（格式非法、迭代数越界、字段解码失败、
   长度异常、参数类型错误）一律返回 False，绝不"看起来验证通过"；
   正常程序错误（如编码错误）不被吞掉、照常抛出。

存储格式（auth_user.password_hash）：
    pbkdf2_sha256$<iterations>$<salt_b64url>$<derived_b64url>
其中 salt / derived 使用 base64.urlsafe_b64encode 的 ASCII 文本，可稳定解析。

零第三方依赖：仅使用标准库 hashlib / hmac / secrets / base64 / re。
"""

import base64
import binascii
import hashlib
import hmac
import re
import secrets

__all__ = [
    "DKLEN",
    "MAX_PBKDF2_ITERATIONS",
    "MAX_PASSWORD_LENGTH",
    "MIN_PBKDF2_ITERATIONS",
    "PBKDF2_ITERATIONS",
    "SALT_BYTES",
    "TOKEN_ENTROPY_BYTES",
    "generate_session_token",
    "hash_password",
    "hash_session_token",
    "verify_password",
]

# ---------- 口令哈希参数 ----------

# 存储格式中的算法标签；换算法时换标签，旧哈希校验自然失败（拒绝而非误判）
_ALGO_LABEL = "pbkdf2_sha256"
_HASH_NAME = "sha256"

# OWASP 建议 PBKDF2-HMAC-SHA256 ≥ 600,000 次；写入与校验共用此下限，
# 低于下限的存量哈希视为不安全，verify 直接拒绝。
PBKDF2_ITERATIONS = 600_000
MIN_PBKDF2_ITERATIONS = 600_000
# 上限防 DoS：登录流程若接受攻击者构造的"天文数字迭代数"哈希会烧满 CPU
MAX_PBKDF2_ITERATIONS = 2_000_000

SALT_BYTES = 16   # ≥ 16 bytes，每次 hash_password 由 secrets 现场生成
DKLEN = 32        # 派生长度 = SHA-256 输出宽度
MAX_PASSWORD_LENGTH = 1024  # 防超长输入拖慢 KDF（远超任何真实口令长度）

# base64url 字段（不含内嵌空白/非法字符；'=' 填充只允许出现在末尾，最多 2 个）
_B64URL_RE = re.compile(r"[A-Za-z0-9_\-]+={0,2}")
# 迭代数字段：仅 ASCII 数字，杜绝 int() 接受的下划线/全角数字等歧义
_ITERATIONS_RE = re.compile(r"[0-9]+")


# ---------- password hash / verify ----------


def hash_password(password: str) -> str:
    """对明文口令做 PBKDF2-HMAC-SHA256 哈希，返回可持久化的编码串。

    盐由 secrets.token_bytes 现场随机生成，因此同一口令两次调用结果必然
    不同（盐不同）。结果格式：pbkdf2_sha256$<iterations>$<salt>$<derived>。

    Raises:
        TypeError: password 不是 str。
        ValueError: password 为空 / 纯空白 / 超过 MAX_PASSWORD_LENGTH。
    """
    if not isinstance(password, str):
        raise TypeError("password 必须是 str")
    if not password.strip():
        raise ValueError("password 不能为空或纯空白")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"password 长度超过上限 {MAX_PASSWORD_LENGTH}")

    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        _HASH_NAME, password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=DKLEN
    )
    return "$".join(
        (
            _ALGO_LABEL,
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """校验明文口令是否与存储的编码哈希匹配。

    使用 hmac.compare_digest 恒时比较；malformed / 越界 / 解码失败等
    异常输入一律返回 False，不抛异常、不静默通过。
    """
    if not isinstance(password, str) or not isinstance(encoded_hash, str):
        return False
    if not password.strip():
        return False

    parts = encoded_hash.split("$")
    if len(parts) != 4:
        return False
    algo, iterations_field, salt_field, hash_field = parts

    if algo != _ALGO_LABEL:
        return False
    if _ITERATIONS_RE.fullmatch(iterations_field) is None:
        return False
    iterations = int(iterations_field)
    if not (MIN_PBKDF2_ITERATIONS <= iterations <= MAX_PBKDF2_ITERATIONS):
        return False

    try:
        salt = _decode_b64url(salt_field)
        expected = _decode_b64url(hash_field)
    except (ValueError, binascii.Error):  # binascii.Error 是 ValueError 子类，显式列出以示意图
        return False

    # 盐必须达到安全下限；派生值必须与本实现的输出宽度一致
    if len(salt) < SALT_BYTES or len(expected) != DKLEN:
        return False

    derived = hashlib.pbkdf2_hmac(
        _HASH_NAME, password.encode("utf-8"), salt, iterations, dklen=DKLEN
    )
    return hmac.compare_digest(derived, expected)


def _decode_b64url(field: str) -> bytes:
    """解码 base64url 字段；字符集非法时抛 ValueError（由调用方转 False）。"""
    if _B64URL_RE.fullmatch(field) is None:
        raise ValueError("非法 base64url 字段")
    return base64.urlsafe_b64decode(field.encode("ascii"))


# ---------- session token ----------

# 32 bytes 熵 = 256 bit；token_urlsafe 输出约 43 字符 URL 安全文本
TOKEN_ENTROPY_BYTES = 32


def generate_session_token() -> str:
    """生成不可预测的会话令牌（secrets.token_urlsafe，32 bytes 熵）。

    每次调用产生不同令牌；原始令牌只存在于内存，入库前必须先做
    hash_session_token()。
    """
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_session_token(token: str) -> str:
    """会话令牌哈希：SHA-256 十六进制（64 字符小写），稳定可索引。

    同一令牌两次调用结果相同；数据库只保存本函数输出，不保存原始令牌。

    Raises:
        TypeError: token 不是 str。
        ValueError: token 为空。
    """
    if not isinstance(token, str):
        raise TypeError("token 必须是 str")
    if not token:
        raise ValueError("token 不能为空")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
