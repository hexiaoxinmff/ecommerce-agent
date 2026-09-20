"""backend 测试公共配置。

将 backend 目录加入模块搜索路径，使测试可以直接 `import app.*`，
并将 TestClient 作为公共 fixture 供各测试模块使用。
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    """FastAPI 测试客户端。"""
    return TestClient(app)