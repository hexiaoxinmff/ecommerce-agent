# 部署指南：把客服 Demo 上线，拿到可分享链接

本项目是 **FastAPI 后端 + 单页前端**，需要 Python 运行时。以下两种免费平台都能一键部署，部署后把链接贴进简历即可。

## 方式一：Render（推荐，最简单）

1. 把本项目推到 GitHub 仓库。
2. 打开 https://render.com → New → **Web Service** → 关联仓库。
3. 配置：
   - Runtime: `Docker`（自动读取仓库根目录 `Dockerfile`）
   - Start Command 留空（Dockerfile 已写 `uvicorn ... --port 8000`）
   - 在 **Environment** 中添加 `API_KEY`（可选，填了即升级为真实语义检索）。
4. 部署完成后，Render 会给你一个 `xxx.onrender.com` 的公开地址。

> 免费版会在闲置后休眠，首次访问稍慢属正常。

## 方式二：Hugging Face Spaces（Docker SDK）

1. 在 https://huggingface.co/spaces 新建 Space，SDK 选 **Docker**。
2. 把本项目文件上传（或直接 Git 同步），确保根目录有 `Dockerfile`。
3. Space 设置里添加 Secret：`API_KEY`（可选）。
4. 启动后即可获得 `xxx.hf.space` 公开地址。

## 上线前的小建议

- **务必填 API Key**：否则线上也是演示模式（本地 hash 向量 + 模板生成），虽然能跑，但语义能力弱。
- **知识库可继续扩充**：往 `data/kb/` 加更多 markdown，重跑 `python scripts/build_index.py` 再部署。
- **拿到链接后**：在简历里写"可在线体验：xxx.onrender.com"，比只放代码仓库更有说服力。
