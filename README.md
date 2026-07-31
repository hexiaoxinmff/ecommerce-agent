---
title: 云栖数码 · Agent 智能客服
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
short_description: 基于 LangGraph + RAG 的电商智能客服 Agent，支持意图分类、向量检索、Reranker 重排与意图分布可视化
---

# 云栖数码 · Agent 智能客服

> 基于 **LangGraph + RAG** 的电商智能客服系统，可作为数据科学 / 人工智能方向简历项目。

一个面向电商场景的智能客服 Agent：先用 **意图分类** 判断用户诉求，再对商品 / 售后 / 物流等知识库做 **向量检索（RAG）**，经 **Reranker 语义重排** 精选片段，必要时调用 **订单 / 物流查询工具**，最后由大模型生成专业、可溯源的回复。系统提供 Web 聊天界面、意图分布可视化看板，并附带一套 **检索质量评测** 脚本（Recall@k / MRR），体现数据科学工程能力。

## ✨ 核心特性

- **Agent 编排**：LangGraph 状态图 `分类 → 检索 → 重排 → (工具) → 生成`，流程清晰、可扩展。
- **RAG 知识库**：scikit-learn `NearestNeighbors` 向量检索 + 云端 Embedding（通义千问 `text-embedding-v3`），Windows 友好、知识库可热更新。
- **Reranker 重排序**：向量召回后由 LLM 做语义重排，提升送入生成的片段质量；无 Key 时规则兜底。
- **工具调用**：内置订单 / 物流查询 Mock 工具，演示 Agent 落地业务动作的能力。
- **零成本可演示**：未配置 API Key 时自动降级为本地 hash 向量 + 模板生成，开箱即跑。
- **多模型可插拔**：支持 通义千问 / DeepSeek / 豆包 / 小米 MiMo（均走 OpenAI 兼容协议）。
- **检索评测 + 可视化**：`evaluate.py` 计算 Recall@k 与 MRR（含重排对比）；`intent_dashboard.py` 生成 ECharts 意图分布看板。
- **可在线部署**：FastAPI 后端 + 单页前端，附 Dockerfile 与部署指南。

## 📁 项目结构

```
ecommerce-agent/
├── config/settings.py        # 全局配置（provider / 检索-重排参数 / 路径）
├── data/
│   ├── kb/                  # 知识库 markdown（商品/售后/FAQ/物流/政策）
│   ├── index/               # 构建出的向量索引（自动生成）
│   ├── logs/                # 会话日志 conversations.jsonl
│   └── generated/           # 评测结果 / 看板 HTML（自动生成）
├── src/
│   ├── rag/                 # embeddings / vector_store / ingest / retrieve / reranker
│   ├── agent/               # prompts / llm / tools / graph（LangGraph）
│   ├── api/main.py          # FastAPI 服务（/api/chat、/dashboard）
│   ├── frontend/index.html  # 聊天界面
│   └── eval/                # evaluate.py（评测）/ intent_dashboard.py（看板）
├── scripts/                 # build_index.py / run.py
├── requirements.txt
├── Dockerfile
├── .env.example
├── README.md
└── REPORT.md                # 技术报告（简历加分项）
```

## 🚀 快速开始

### 1. 安装依赖（建议使用虚拟环境）

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置（可选，不配置也能跑演示模式）

复制 `.env.example` 为 `.env`，填入你的 API Key：

```bash
cp .env.example .env
# 编辑 .env，例如用小米 MiMo：
#   LLM_PROVIDER=xiaomi
#   API_KEY=sk-xxxx
# 如需语义检索（豆包/小米无文本 Embedding），额外填通义：
#   EMBEDDING_PROVIDER=qwen
#   EMBED_API_KEY=sk-通义Key
```

- 通义千问：https://dashscope.console.aliyun.com/ 申请，模型 `qwen-plus` + `text-embedding-v3`
- DeepSeek：https://platform.deepseek.com/ 申请，模型 `deepseek-chat`
- 豆包（火山方舟）：https://console.volcengine.com/ark 申请，`base_url=https://ark.cn-beijing.volces.com/api/v3`
- 小米 MiMo：https://api.xiaomimimo.com 申请

### 3. 构建向量索引

```bash
python scripts/build_index.py
```

### 4. 启动服务

```bash
python scripts/run.py
# 或：
uvicorn src.api.main:app --port 8000
```

浏览器打开 `http://localhost:8000` 对话；
打开 `http://localhost:8000/dashboard` 查看意图分布可视化看板。

### 5. 运行检索评测

```bash
python -m src.eval.evaluate
# 对比「纯向量召回」与「+Reranker 重排」的 Recall@1/3/5、MRR，保存 eval_results.json
```

### 6. 生成意图分布看板

```bash
python -m src.eval.intent_dashboard
# 也可直接访问 /dashboard 由服务动态生成
```

## 🔧 接入真实业务

- **知识库**：往 `data/kb/` 放更多 markdown 文档，重跑 `build_index.py` 即可。
- **订单工具**：将 `src/agent/tools.py` 的 `lookup_order` 替换为真实 ERP / 物流 API。
- **换模型**：修改 `.env` 中 `LLM_PROVIDER` 与模型名，代码无需改动。

详见 **REPORT.md**（项目技术报告）。
