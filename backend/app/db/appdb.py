"""应用库（app.db）可写访问层。

承载认证与会话相关持久化：auth_user / auth_session / query_history 三表，
与业务库 db/ecommerce.db（强制只读，见 app/db/sqlite.py）物理隔离：

1. 业务库只读设计不变，本层绝不打开、读取或修改 ecommerce.db；
2. 本层是应用数据的唯一写入入口；所有 SQL 一律参数化（占位符 + 参数元组），
   禁止拼接用户输入；
3. query_history 的读取与删除一律强制 ``user_id = ?`` 条件：user_id 以
   服务端登录态为准（后续任务接入 get_current_user），绝不信任前端参数；
4. 不保存明文密码与明文会话令牌：password_hash 与 token_hash 字段只接收
   调用方传入的哈希字符串，本层不做任何明文落库（哈希算法属 P2 任务）。

时间统一 ISO 8601 UTC（``now_iso()``），例如 ``2026-09-25T12:34:56+00:00``。

初始化：``python scripts/init_auth_db.py``（幂等，可重复执行）。
当前阶段（Task37-2 / P1）仅提供数据访问函数，不接 FastAPI 路由。
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.core import config

# 三张应用表（与 Task37-1 审计 §9.3 设计一致，无多余字段）
APP_TABLE_NAMES: tuple[str, ...] = (
    "auth_user",
    "auth_session",
    "query_history",
)

APP_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS auth_user (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS auth_session (
    id         INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_user(id)
);

CREATE TABLE IF NOT EXISTS query_history (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL,
    session_id     INTEGER,
    question       TEXT NOT NULL,
    sql            TEXT NOT NULL DEFAULT '',
    success        INTEGER NOT NULL,
    error_message  TEXT NOT NULL DEFAULT '',
    result_summary TEXT NOT NULL DEFAULT '',
    row_count      INTEGER,
    total_time_ms  REAL,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_user(id),
    FOREIGN KEY (session_id) REFERENCES auth_session(id)
);

CREATE INDEX IF NOT EXISTS idx_auth_session_user_id ON auth_session(user_id);
CREATE INDEX IF NOT EXISTS idx_query_history_user_id ON query_history(user_id);
CREATE INDEX IF NOT EXISTS idx_query_history_created_at ON query_history(created_at);
"""


class AppDbError(Exception):
    """应用库访问层异常基类。"""


class AppDbNotFoundError(AppDbError):
    """应用库文件不存在（尚未运行 scripts/init_auth_db.py）。"""


def now_iso() -> str:
    """当前时刻，ISO 8601 UTC（秒级），例如 2026-09-25T12:34:56+00:00。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    """获取一条独立的可写连接，调用方负责关闭。

    Raises:
        AppDbNotFoundError: 应用库文件不存在（应先运行 scripts/init_auth_db.py）。
    """
    db_path = Path(config.APP_DB_PATH)
    if not db_path.is_file():
        raise AppDbNotFoundError(
            f"应用库不存在: {db_path}（请先运行 scripts/init_auth_db.py）"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_app_db() -> Path:
    """幂等初始化应用库：自动创建目录与三张表，重复执行不报错、不丢数据。

    Returns:
        应用库文件路径（config.APP_DB_PATH）。
    """
    db_path = Path(config.APP_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(APP_SCHEMA_DDL)
        conn.commit()
    finally:
        conn.close()
    return db_path


# ---------- auth_user ----------


def create_user(username: str, email: str, password_hash: str) -> int:
    """创建应用账号，返回新用户 id。

    username / email 冲突时由 UNIQUE 约束抛出 sqlite3.IntegrityError。
    password_hash 必须是调用方生成的哈希字符串（本层不接收明文密码）。
    """
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO auth_user (username, email, password_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, email, password_hash, now_iso()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_user_by_username(username: str) -> sqlite3.Row | None:
    """按用户名精确查找应用账号（参数化查询）。"""
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM auth_user WHERE username = ?", (username,)
        ).fetchone()


def get_user_by_email(email: str) -> sqlite3.Row | None:
    """按邮箱精确查找应用账号（参数化查询）。"""
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM auth_user WHERE email = ?", (email,)
        ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    """按 id 查找应用账号。"""
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM auth_user WHERE id = ?", (user_id,)
        ).fetchone()


# ---------- auth_session ----------


def create_session(user_id: int, token_hash: str, expires_at: str) -> int:
    """写入一条服务端会话（token 只存哈希），返回会话 id。

    token_hash 由调用方生成（P2 任务提供令牌与哈希原语）；expires_at 为
    ISO 8601 UTC 字符串。user_id 不存在时由外键约束抛出 IntegrityError。
    """
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO auth_session (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now_iso(), expires_at),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_session(token_hash: str) -> sqlite3.Row | None:
    """按令牌哈希查找会话（不校验过期，过期判定属登录态逻辑，后续任务接入）。"""
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM auth_session WHERE token_hash = ?", (token_hash,)
        ).fetchone()


def delete_session(token_hash: str) -> bool:
    """按令牌哈希删除会话（logout），返回是否确实删除了行。

    删除前先在同一事务内把该会话在 query_history.session_id 上的引用
    置 NULL（历史记录本身全部保留），否则外键约束会使有查询历史的
    用户登出失败（Task38 G7）。任一步失败整体回滚，不产生半完成状态。
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT id FROM auth_session WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if row is None:
            return False
        try:
            conn.execute(
                "UPDATE query_history SET session_id = NULL WHERE session_id = ?",
                (row["id"],),
            )
            cursor = conn.execute(
                "DELETE FROM auth_session WHERE token_hash = ?", (token_hash,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return cursor.rowcount > 0


# ---------- query_history ----------


def create_query_history(
    user_id: int,
    question: str,
    *,
    session_id: int | None = None,
    sql: str = "",
    success: bool = False,
    error_message: str = "",
    result_summary: str = "",
    row_count: int | None = None,
    total_time_ms: float | None = None,
) -> int:
    """写入一条查询历史，返回历史 id。

    user_id 必须来自服务端登录态；user_id / session_id 不存在时由外键约束
    抛出 IntegrityError。result_summary 只存轻量摘要，禁止塞入结果全集。
    """
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "INSERT INTO query_history ("
            "user_id, session_id, question, sql, success, error_message, "
            "result_summary, row_count, total_time_ms, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                session_id,
                question,
                sql,
                int(bool(success)),
                error_message,
                result_summary,
                row_count,
                total_time_ms,
                now_iso(),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_query_history(
    user_id: int, *, limit: int = 50, offset: int = 0
) -> list[sqlite3.Row]:
    """按创建时间倒序列出指定用户的历史（强制 user_id 隔离 + 分页）。"""
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT * FROM query_history WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()


def count_query_history(user_id: int) -> int:
    """统计指定用户的历史总数（强制 user_id 条件，供历史分页 total 使用）。"""
    with closing(get_connection()) as conn:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM query_history WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(count)


def delete_query_history(user_id: int, history_id: int) -> bool:
    """删除指定用户的一条历史；跨用户删除（id 不属于该用户）返回 False。"""
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "DELETE FROM query_history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
