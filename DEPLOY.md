# 部署指南：把客服 Demo 上线，拿到可分享链接

项目已**部署就绪**：`Dockerfile`（统一 Render / Hugging Face Spaces）、`.dockerignore`（已排除 `.env`，密钥不会进镜像）、本地提交已完成。
下方步骤帮你把它推到免费平台，拿到 `xxx.onrender.com` 或 `xxx.hf.space` 这种公开链接写进简历。

> ⚠️ **密钥安全**：小米 Key 在本地 `.env` 里，**绝不入库、绝不进镜像**（已被 `.gitignore` 和 `.dockerignore` 双重排除）。
> 上线时在平台后台设置环境变量即可，不要把它写进代码或提交。

---

## 方式一：Hugging Face Spaces（免费、无需信用卡，推荐）

1. 打开 https://huggingface.co/spaces → **New Space** → 名称随意（如 `ecommerce-agent`）→ **SDK 选 Docker** → 创建。
2. 进入 Space 的 **Files** 标签，把本项目的全部文件上传（或 `git clone` 后推送）。**关键**：Space 的 `README.md` 顶部必须保留下面这段 YAML（HF 靠它识别为 Docker 并监听 7860 端口）：
   ```yaml
   ---
   title: 云栖数码 · Agent 智能客服
   emoji: 🛒
   colorFrom: blue
   colorTo: gray
   sdk: docker
   app_port: 7860
   ---
   ```
   （我们 `Dockerfile` 已让容器监听 `0.0.0.0:7860`，与 `app_port` 一致。）
3. 进入 Space **Settings → Secrets / Variables**，添加变量（按需）：
   - `LLM_PROVIDER=xiaomi`
   - `API_KEY=你的小米Key`（让线上用真实大模型，而非模板兜底）
   - （可选）要做**真·语义检索**：再加 `EMBEDDING_PROVIDER=qwen` 和 `EMBED_API_KEY=通义Key`
4. 等待镜像构建完成（首次装 `scikit-learn/langchain/langgraph` 约几分钟），状态变绿即上线。
5. 访问 `https://hf.space/你的用户名/ecommerce-agent` 即可对话；`/dashboard` 看意图分布看板。

---

## 方式二：Render（免费，最简单，Docker 自动识别）

1. 把本项目推到 GitHub（仓库已 `git init` 并提交，只差 `git remote add` + `git push`）。
2. 打开 https://render.com → **New → Web Service** → 关联该仓库。
3. 配置：
   - Environment: **Docker**（自动读取根目录 `Dockerfile`）
   - Start Command / Build Command 留空（都在 Dockerfile 里）
   - **Environment → Add Environment Variable** 添加上面的变量（`LLM_PROVIDER`、`API_KEY` 等）
4. 部署完成会给你 `xxx.onrender.com` 公开地址。
   > 免费版空闲后会休眠，首次访问稍慢属正常。

---

## 上线前检查清单

- [ ] 平台环境变量已填 `API_KEY`（否则线上是演示模式：本地 hash 向量 + 模板生成，能跑但语义弱）
- [ ] 想要语义检索：额外填 `EMBEDDING_PROVIDER=qwen` + `EMBED_API_KEY`
- [ ] 知识库要扩充：往 `data/kb/` 加 markdown，重跑 `python scripts/build_index.py` 再部署
- [ ] 拿到链接后，简历里写「可在线体验：xxx.onrender.com」

## 本地复核记录（本机已验证）
- `uvicorn ... --host 0.0.0.0 --port 7860` 正常监听并对外服务（`/api/health`、`/api/chat`、 `/dashboard` 均 200）
- 小米 Key 接入：`mock_mode=false, provider=xiaomi`，真实对话 + Reranker 重排 + 来源引用正常
- 意图分布看板基于真实会话日志生成（不足 5 条时自动用演示数据兜底）
