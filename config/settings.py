"""
全局配置：从环境变量 / .env 读取。
支持 qwen / deepseek / doubao(豆包) / xiaomi(小米 MiMo) 四种 OpenAI 兼容大模型，
以及“无 Key 兜底模式”（本地 hash 向量 + 模板生成，零成本可演示）。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（config 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ---- 提供方选择 ----
LLM_PROVIDER = _get("LLM_PROVIDER", "qwen").lower()
API_KEY = _get("API_KEY", "")

# ---- 各 provider 的默认 endpoint 与模型（可被 .env 同名变量覆盖）----
_PROVIDER_DEFAULTS = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "chat_model": "deepseek-chat",
    },
    "doubao": {  # 字节跳动 火山方舟 Ark
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "chat_model": "doubao-seed-1-8-251228",
    },
    "xiaomi": {  # 小米 MiMo
        "base_url": "https://api.xiaomimimo.com/v1",
        "chat_model": "mimo-v2.5-pro",
    },
}

# 每个 provider 对应的 .env 变量名，优先级：专属变量 > 硬编码默认
_PROVIDER_ENV = {
    "qwen": ("QWEN_BASE_URL", "QWEN_CHAT_MODEL"),
    "deepseek": ("DEEPSEEK_BASE_URL", "DEEPSEEK_CHAT_MODEL"),
    "doubao": ("DOUBAO_BASE_URL", "DOUBAO_CHAT_MODEL"),
    "xiaomi": ("XIAOMI_BASE_URL", "XIAOMI_CHAT_MODEL"),
}


def _provider_base_url(p: str) -> str:
    env_key, _ = _PROVIDER_ENV.get(p, ("QWEN_BASE_URL", "QWEN_CHAT_MODEL"))
    return _get(env_key, _PROVIDER_DEFAULTS.get(p, _PROVIDER_DEFAULTS["qwen"])["base_url"])


def _provider_chat_model(p: str) -> str:
    _, env_key = _PROVIDER_ENV.get(p, ("QWEN_BASE_URL", "QWEN_CHAT_MODEL"))
    return _get(env_key, _PROVIDER_DEFAULTS.get(p, _PROVIDER_DEFAULTS["qwen"])["chat_model"])


# 通用覆盖（最高优先级）：直接指定 base_url / model 可接任意 OpenAI 兼容模型
LLM_BASE_URL = _get("LLM_BASE_URL", _provider_base_url(LLM_PROVIDER)).rstrip("/")
LLM_CHAT_MODEL = _get("LLM_CHAT_MODEL", _provider_chat_model(LLM_PROVIDER))

# 兼容旧变量（若仍在 .env 中使用，仍生效）
QWEN_BASE_URL = _provider_base_url("qwen").rstrip("/")
QWEN_CHAT_MODEL = _provider_chat_model("qwen")
DEEPSEEK_BASE_URL = _provider_base_url("deepseek").rstrip("/")
DEEPSEEK_CHAT_MODEL = _provider_chat_model("deepseek")

# ---- 嵌入层 ----
# 豆包文本 Embedding 已下线、小米无公开文本 Embedding，故默认：
#   - LLM 用 qwen 时，embedding 默认也用 qwen（真实语义向量）
#   - LLM 用 doubao/xiaomi/deepseek 时，embedding 默认走本地 hash 兜底
# 用户可显式设置 EMBEDDING_PROVIDER=qwen 并填 EMBED_API_KEY（通义 Key）来升级语义检索，
# 或用 EMBED_BASE_URL / EMBED_MODEL / EMBED_API_KEY 接任意 OpenAI 兼容 embedding 服务。
EMBEDDING_PROVIDER = _get("EMBEDDING_PROVIDER", "").lower()
if not EMBEDDING_PROVIDER:
    EMBEDDING_PROVIDER = "qwen" if LLM_PROVIDER == "qwen" else "mock"

EMBED_BASE_URL = _get("EMBED_BASE_URL", "").rstrip("/")
EMBED_MODEL = _get("EMBED_MODEL", "")
EMBED_API_KEY = _get("EMBED_API_KEY", API_KEY)

# 通义千问 embedding 相关（真实语义向量来源）
QWEN_EMBED_BASE_URL = _get("QWEN_EMBED_BASE_URL", QWEN_BASE_URL).rstrip("/")
QWEN_EMBED_MODEL = _get("QWEN_EMBED_MODEL", "text-embedding-v3")

# 无 API Key 时启用本地 hash 兜底（保证零成本可演示）
MOCK_MODE = (API_KEY == "")

# 是否启用真实 embedding：有 key 且 (显式指定嵌入服务 或 选了 qwen 嵌入)
USE_REAL_EMBED = (not MOCK_MODE) and (
    EMBEDDING_PROVIDER == "qwen" or bool(EMBED_BASE_URL)
)

# 嵌入向量维度（qwen text-embedding-v3 默认 1024；兜底模式用 256）
EMBED_DIM = 1024 if USE_REAL_EMBED else 256

# ---- 检索参数 ----
RETRIEVE_TOP_K = int(_get("RETRIEVE_TOP_K", "4"))
CHUNK_SIZE = int(_get("CHUNK_SIZE", "400"))
CHUNK_OVERLAP = int(_get("CHUNK_OVERLAP", "80"))

# ---- 重排序（Reranker）参数 ----
# 先从向量库多召回一批候选，再由 Reranker 语义重排精选，提升送入生成的片段质量。
RERANK_CANDIDATES = int(_get("RERANK_CANDIDATES", "8"))  # 向量检索召回的候选数
RERANK_TOP_N = int(_get("RERANK_TOP_N", "4"))  # 重排后用于生成的片段数

# ---- 路径 ----
DATA_DIR = BASE_DIR / "data"
KB_DIR = DATA_DIR / "kb"
INDEX_DIR = DATA_DIR / "index"
LOGS_DIR = DATA_DIR / "logs"
INDEX_FILE = INDEX_DIR / "kb.index"
META_FILE = INDEX_DIR / "meta.pkl"
LOG_FILE = LOGS_DIR / "conversations.jsonl"

# 确保目录存在
for d in (INDEX_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)
