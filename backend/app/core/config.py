"""后端全局配置。

环境加载顺序：
1. 尝试加载项目根目录 .env（如存在，通过 python-dotenv；外部环境变量优先）；
2. 各配置项从环境变量读取，未设置时使用默认值。

数据库路径解析优先级：
1. 环境变量 ECOMMERCE_DB_PATH（可以是绝对或相对路径）；
2. 未设置时使用项目默认路径 db/ecommerce.db（相对项目根目录，
   由本文件位置向上推导，不依赖进程工作目录）。

LLM Provider 配置（mimo / bailian 两种实现）：
- LLM_PROVIDER：Provider 名称，默认 mimo；
- MIMO_API_KEY：只从环境变量读取，绝不写死在代码中；
- MIMO_BASE_URL / MIMO_MODEL / MIMO_TIMEOUT：均可配置；
- DASHSCOPE_API_KEY：百炼（Bailian）唯一 Key 来源，同样只从环境变量读取，
  不引入 BAILIAN_API_KEY（避免双 Key 来源）；
- BAILIAN_API_BASE / BAILIAN_MODEL / BAILIAN_TIMEOUT：百炼配置，均有默认值
  （默认模型 qwen3.7-flash-2026-07-15）。
  注意：**没有** thinking 开关 —— thinking 在 BailianProvider 里物理锁死为 False。

Task66 免费模型池配置（全部有安全默认值，不配即保持单模型行为）：
- BAILIAN_PRIMARY_MODEL：主模型，默认回落 BAILIAN_MODEL；
- BAILIAN_FALLBACK_MODELS：备用模型池（逗号分隔、显式有序），默认空；
- LLM_MODEL_LOCK：默认 **true** —— 正式评测固定单模型，禁止自动切换；
- BAILIAN_FREE_TIER_ONLY：默认 **true** —— 只允许调用显式配置的免费优先模型，
  绝不自动转付费。

CORS 允许来源可通过环境变量 CORS_ORIGINS（逗号分隔）覆盖，
默认仅允许前端本地开发地址 http://localhost:5173。
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv 缺失时静默跳过，仅依赖真实环境变量
    load_dotenv = None

# backend/app/core/config.py -> 向上 3 级即项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]

if load_dotenv is not None:
    # 加载项目根 .env（如存在）；已存在的外部环境变量优先
    load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "ecommerce.db"

_raw_db_path = os.getenv("ECOMMERCE_DB_PATH")
DB_PATH = Path(_raw_db_path).resolve() if _raw_db_path else DEFAULT_DB_PATH.resolve()

# ---------- 应用库（认证 / 会话 / 查询历史） ----------

# 与业务库 ecommerce.db（只读，见 app/db/sqlite.py）物理隔离的独立 SQLite 文件。
# 环境变量 APP_DB_PATH 可覆盖；默认 db/app.db。
# 本库是唯一的认证持久化位置：业务库连接层保持只读设计，绝不写入。
_raw_app_db_path = os.getenv("APP_DB_PATH")
APP_DB_PATH = (
    Path(_raw_app_db_path).resolve()
    if _raw_app_db_path
    else (PROJECT_ROOT / "db" / "app.db").resolve()
)

SERVICE_NAME = "ecommerce-analysis-agent"

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

# ---------- LLM Provider ----------

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mimo").strip().lower()

# API Key 只从环境变量读取；未配置时保持空字符串，
# 服务照常启动，LLM 接口返回明确的"未配置"错误。
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "").strip()
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "").strip() or None
MIMO_MODEL = os.getenv("MIMO_MODEL", "").strip()


def _env_positive_float(name: str, default: float) -> float:
    """读取正浮点环境变量；未设置、非法或非正值时回退默认值。"""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# 超时必设：默认 30 秒，不允许 None（由 _env_positive_float 保证）
MIMO_TIMEOUT = _env_positive_float("MIMO_TIMEOUT", 30.0)

# ---------- 应用库会话有效期 ----------

# 会话 TTL（秒）。默认 7 天（604800）；环境变量 AUTH_SESSION_TTL_SECONDS 可覆盖。
# 登录时据此计算 auth_session.expires_at；认证依赖据此校验会话是否过期。
AUTH_SESSION_TTL_SECONDS = int(
    _env_positive_float("AUTH_SESSION_TTL_SECONDS", 7 * 24 * 3600)
)

# ---------- Alibaba Cloud Bailian（DashScope OpenAI 兼容模式）----------

# API Key 唯一来源：DASHSCOPE_API_KEY（刻意不提供 BAILIAN_API_KEY 别名，
# 避免同一个 Secret 出现两条读取路径）。
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()

# base_url / model 给真实默认值（与 Mimo 的「空则 None」不同）：
# 百炼端点与低消费默认模型是稳定常量，未配置时应可直接可用。
BAILIAN_BASE_URL = (
    os.getenv("BAILIAN_API_BASE", "").strip()
    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
BAILIAN_MODEL = (
    os.getenv("BAILIAN_MODEL", "").strip() or "qwen3.7-flash-2026-07-15"
)

# 刻意没有 BAILIAN_ENABLE_THINKING：thinking 在
# BailianProvider._call_model() 里物理锁死为 False（字面量，非配置），
# 不留任何可被环境变量覆盖的旋钮 —— 低消费是本项目的硬约束。

BAILIAN_TIMEOUT = _env_positive_float("BAILIAN_TIMEOUT", 30.0)

# ---------- Task66: 百炼免费模型池 / 自动 Fallback ----------


def _env_flag(name: str, default: bool) -> bool:
    """读取布尔环境变量；未设置或无法识别时回退默认值。

    ⚠️ 刻意不命名为 ``_env_bool``：既有护栏测试
    （``backend/tests/test_bailian_provider.py``）对 ``app/`` 全目录做 AST 扫描，
    禁止出现 ``_env_bool`` 属性引用 —— 那是「thinking 不得有配置旋钮」
    这条硬约束的守卫。新增开关不应削弱既有守卫，故另起名字。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# 主模型：未显式配置时回落到既有 BAILIAN_MODEL，
# 保证「只配了单模型」的既有部署行为逐项不变（Task66 §29 向后兼容）。
BAILIAN_PRIMARY_MODEL = os.getenv("BAILIAN_PRIMARY_MODEL", "").strip() or BAILIAN_MODEL

# 备用模型池（显式有序，逗号分隔）。默认为空 => 不启用 fallback，
# 等价于当前单模型模式。
# ⚠️ 这里只保存「已显式配置的候选」，绝不写死任何「当前免费」的模型名单：
# 百炼不同模型 / 不同快照的免费额度相互独立且随周期变化，属运行时状态
# （Task66 §34）。空字符串项被丢弃，顺序即优先级（§20）。
BAILIAN_FALLBACK_MODELS: tuple[str, ...] = tuple(
    m.strip() for m in os.getenv("BAILIAN_FALLBACK_MODELS", "").split(",") if m.strip()
)

# 正式评测默认 true：一次 run 必须固定单模型，禁止中途自动切换，
# 否则一个 run 内混入多个 model，无法与 Frozen Baseline 做干净比较
# （Task66 §13 / §15 / §28 / §36）。
LLM_MODEL_LOCK = _env_flag("LLM_MODEL_LOCK", True)

# 默认 true：只允许调用显式配置的免费优先模型。
# 绝不自动关闭 free-tier-only、绝不自动转付费 / 充值 / 购买资源包
# （Task66 §4 / §30）。
BAILIAN_FREE_TIER_ONLY = _env_flag("BAILIAN_FREE_TIER_ONLY", True)

# ---------- Few-shot Dataset ----------

# 环境变量 FEWSHOT_DATASET_PATH 可覆盖；默认 data/fewshot/ecommerce_examples.json
_raw_fewshot_path = os.getenv("FEWSHOT_DATASET_PATH")
DEFAULT_FEWSHOT_DATASET_PATH = PROJECT_ROOT / "data" / "fewshot" / "ecommerce_examples.json"
FEWSHOT_DATASET_PATH = (
    Path(_raw_fewshot_path).resolve() if _raw_fewshot_path else DEFAULT_FEWSHOT_DATASET_PATH
)