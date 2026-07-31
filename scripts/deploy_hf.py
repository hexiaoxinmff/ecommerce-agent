"""一键部署到 Hugging Face Spaces（Docker SDK）。

前置：
  - 设置环境变量 HF_TOKEN（write 权限的 Access Token）
  - 可选：SPACE_NAME（默认 ecommerce-agent-customer-service）

行为：
  1. 用 token 解析 username（whoami）
  2. 创建 / 复用 Docker 类型的 Space
  3. 把本地 git 仓库推送到 HF（.env 已被 .dockerignore 排除，绝不进镜像/仓库）
  4. 设置 Space 环境变量 LLM_PROVIDER=xiaomi 与 API_KEY（来自 .env，绝不打印）

安全说明：
  - token 仅来自环境变量，不写文件、不打印。
  - 小米 API Key 从本地 .env 读取后通过 HF Secret API 注入，不落盘到仓库。
"""
import os
import subprocess
import sys

from huggingface_hub import HfApi, whoami

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SPACE_NAME = os.environ.get("SPACE_NAME", "ecommerce-agent-customer-service")
HF_TOKEN = os.environ.get("HF_TOKEN")
if not HF_TOKEN:
    sys.exit("ERROR: 请先设置环境变量 HF_TOKEN（HF 账号 Access Token，需 write 权限）")


def _load_local_env() -> dict:
    env = {}
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, "r", encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    api = HfApi(token=HF_TOKEN)
    info = whoami(token=HF_TOKEN)
    username = info["name"]
    repo_id = f"{username}/{SPACE_NAME}"
    print(f"==> 登录用户：{username}")
    print(f"==> 目标 Space：{repo_id}")

    # 1. 创建 / 复用 Docker Space
    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="docker",
        exist_ok=True,
        token=HF_TOKEN,
    )
    print("==> Space 仓库已就绪")

    # 2. 添加 remote 并推送（用 token 作为凭证，不写入文件）
    remote_url = f"https://{username}:{HF_TOKEN}@huggingface.co/spaces/{repo_id}"
    subprocess.run(["git", "-C", ROOT, "remote", "remove", "hf"], check=False)
    subprocess.run(["git", "-C", ROOT, "remote", "add", "hf", remote_url], check=True)
    print("==> 推送代码到 HF（首次构建镜像约需 1-3 分钟）...")
    push = subprocess.run(
        ["git", "-C", ROOT, "push", "hf", "main", "--force"],
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        print(push.stdout)
        print(push.stderr)
        sys.exit("ERROR: git push 失败")
    print("==> 代码已推送，HF 正在构建镜像")

    # 3. 设置环境变量（小米 Key 从本地 .env 读取，不打印）
    local = _load_local_env()
    api.add_space_secret(repo_id=repo_id, key="LLM_PROVIDER", value=local.get("LLM_PROVIDER", "xiaomi"), token=HF_TOKEN)
    if local.get("API_KEY"):
        api.add_space_secret(repo_id=repo_id, key="API_KEY", value=local["API_KEY"], token=HF_TOKEN)
        print("==> 已注入环境变量 LLM_PROVIDER / API_KEY（Secret，不在仓库中）")
    else:
        print("WARNING: 本地 .env 未找到 API_KEY，请在 Space Settings 手动填写")

    print(f"==> 完成！稍候在 https://huggingface.co/spaces/{repo_id} 查看（构建完成后即可对话）")


if __name__ == "__main__":
    main()
