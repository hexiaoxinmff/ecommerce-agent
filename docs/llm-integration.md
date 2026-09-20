# LLM 集成说明（LLM Integration）

> 阶段：阶段 4-任务 2（可插拔 LLM Provider + Mimo V2.5 Pro 接入）
> 日期：2026-09-15
> 本文档只记录**已经真正实现**的内容。

---

## 1. 架构

```text
上层（API 路由 / 未来 Text2SQL、LangGraph 等）
   ↓ 只依赖抽象
LLMProvider（Protocol，统一最小接口：generate(messages) -> str）
   ↑
MimoProvider（当前默认实现，内部使用 OpenAI SDK，OpenAI-compatible）
   ↓
Mimo V2.5 Pro API
```

- 抽象与工厂在 `backend/app/llm/provider.py`；
- Mimo 实现在 `backend/app/llm/mimo.py`；
- 工厂 `get_llm_provider()` 根据 `LLM_PROVIDER` 配置返回 Provider，
  当前仅 `mimo` 有实际实现。

## 2. 为什么采用 Provider 抽象

当前运行时模型是 Mimo V2.5 Pro，但它不能与上层业务（Agent / Text2SQL）
强耦合。上层只依赖 `LLMProvider` 抽象与统一 `LLMError` 异常，
不直接 import `openai` SDK、不感知 Mimo。以后增加
DeepSeekProvider / OpenAIProvider 等只需新增实现并注册工厂，
上层业务代码无需重写。

OpenAI SDK 只允许存在于 Provider 层（api/routes、service、agent 均不得
直接 import `openai`）。

## 3. 配置

全部从环境变量读取（可选加载项目根 `.env`，外部环境变量优先）：

```text
LLM_PROVIDER    Provider 名称，默认 mimo（本阶段仅支持 mimo）
MIMO_API_KEY    Mimo API Key；只从环境变量读取，未配置时服务照常启动，
                LLM 接口返回明确错误
MIMO_BASE_URL   OpenAI-compatible Base URL；官方默认（按量付费）：
                https://api.xiaomimimo.com/v1
                （2026-09-15 依据 Xiaomi MiMo 官方文档确认，真实调用验证通过）
MIMO_MODEL      模型标识；官方旗舰模型：mimo-v2.5-pro
MIMO_TIMEOUT    请求超时秒数，默认 30（必设，不许为 None）
```

- 配置示例见项目根 `.env.example`（不含真实 Key，已填入官方默认
  Base URL 与模型名）；
- 真实 `.env` 已被 `.gitignore` 排除，绝不进入 Git。

### 官方兼容性修正（真实联调后增加）

1. **关闭深度思考**：`mimo-v2.5-pro` 默认开启深度思考（官方参数
   `thinking.type`，默认 `enabled`）。该模式下 temperature/top_p 会被
   服务端强制为推荐默认值，与本阶段 `temperature=0`（低随机性）要求不符；
   且实测在深度思考模式下服务端偶发在响应生成中途断开连接
   （SSL EOF，约 5.7s 处，可稳定复现）。因此 Provider 在请求中
   通过官方参数 `extra_body={"thinking": {"type": "disabled"}}` 关闭
   深度思考——temperature 语义成立、响应更快、断连现象消失。
2. **网络类错误有限重试**：官方端点实测存在偶发的单连接主动断开
   （`Server disconnected without sending a response` / SSL EOF），
   重试期间甚至出现 TLS 层整体不可达（评估任务当天上午曾持续数小时
   不可用）。Provider 仅对网络类错误（LLMNetworkError）做**最多 2 次**
   有限重试（间隔递增 2s / 5s）；认证/限流/超时/5xx 等错误仍一次失败
   即明确失败，SDK 层仍保持 `max_retries=0`，未引入指数退避/熔断等
   复杂机制。

## 4. API

### POST /api/llm/test —— LLM 连接测试

用途：验证 `FastAPI → LLMProvider → MimoProvider → Mimo API` 链路。
不是聊天接口，也不是 Text2SQL 接口。

请求（Pydantic 校验：prompt 为字符串，1 ≤ 长度 ≤ 2000，空白拒收）：

```json
{ "prompt": "请用一句话说明你是什么模型。" }
```

成功响应（HTTP 200）：

```json
{
  "success": true,
  "provider": "mimo",
  "model": "实际配置模型名",
  "content": "模型返回内容",
  "error": ""
}
```

失败响应（示例）：

```json
{
  "success": false,
  "provider": "mimo",
  "model": "实际配置模型名",
  "content": "",
  "error": "Mimo authentication failed"
}
```

安全边界：客户端传入 `api_key` / `model` / `base_url` / `provider` /
`timeout` 等字段会被 Pydantic 忽略，模型配置全部由服务端配置决定。
System Prompt 仅用于连接验证，不含 Schema / SQL 规则 / Few-shot。

## 5. 错误处理

错误状态码约定（保持一致）：

| 场景 | HTTP | 客户端固定文案 |
|---|---|---|
| API Key 未配置 | 503 | `Mimo API key is not configured` |
| Provider 配置有误（未知 Provider / 模型未配置） | 503 | `LLM provider is not configured` |
| 上游认证失败（401 / 403） | 502 | `Mimo authentication failed` |
| 上游限流（429） | 503 | `Mimo rate limited` |
| 上游服务不可用（5xx） | 503 | `Mimo service unavailable` |
| 请求超时 | 503 | `Mimo request timeout` |
| 网络错误 | 503 | `Mimo network error` |
| 其他未预期异常 | 503 | `Mimo request failed` |

- 客户端文案全部为按异常类型的固定映射，绝不回显底层异常全文，
  因此客户端不会看到 API Key / Authorization / 完整 URL / traceback /
  内部文件路径；
- SDK 层 `max_retries=0`；仅网络类错误（官方端点偶发单连接断开）
  在 Provider 层做一次有限重试（间隔 2s），其余错误一次失败即
  明确返回失败；未实现指数退避 / 熔断 / 模型 fallback；
- `temperature = 0`（低随机性，配套关闭官方深度思考，见第 3 节）；
  未实现 top_p / function calling 等额外参数。

## 6. Secret 管理

- `MIMO_API_KEY` 只从环境变量读取，代码中无任何硬编码 Secret；
- 真实 Key 只存于本机 `.env`（不入 Git）或环境变量；
- 日志只能输出 authentication failed / timeout / rate limited /
  service unavailable 等文案，不输出完整请求头；
- 有专门的防泄漏测试：即使底层异常携带 `Bearer test-secret`，
  上层异常与 API 响应中也不会出现该 Secret。

## 7. 单元测试

`backend/tests/test_llm_provider.py`（mock，不真实调用 Mimo）：

- 正常响应 / Key 缺失 / 模型缺失 / 401 / 403 / 429 / 5xx / timeout /
  网络错误 / 未知错误映射 / Secret 防泄漏 / 工厂默认与未知 Provider。

`backend/tests/test_llm_api.py`（mock，不真实调用 Mimo）：

- 正常 200 / 空与空白 prompt 422 / 超长 prompt 422 / Key 未配置 503 /
  Provider 超时 503 / 认证失败 502 / 端到端 Secret 防泄漏 /
  未知异常固定文案 / 客户端额外字段被忽略。

## 8. 真实 API 测试

脚本 `scripts/test_mimo.py`（不进入默认 pytest）：

```bash
python scripts/test_mimo.py
```

- 从环境变量 / `.env` 读取配置，创建 MimoProvider，
  发送两条最小测试 Prompt，输出 provider、model、响应时间与模型内容，
  绝不输出 API Key；
- 结果诚实上报：成功即报告成功；未配置 Key 或调用失败时报真实原因。

### 真实验证记录（2026-09-15）

- 配置：`https://api.xiaomimimo.com/v1` + `mimo-v2.5-pro`（官方文档确认）；
- `python scripts/test_mimo.py`：两条 Prompt 均真实调用成功，
  返回 Xiaomi MiMo 真实内容（排查过程中发现并修正了两处官方兼容性问题，
  见第 3 节）；
- Live 验证：启动 uvicorn 后 `POST /api/llm/test` 两次均返回 HTTP 200，
  `success=true`，content 为 MiMo 真实回复（其中一次耗时 21.8s，
  含一次网络类错误的内部有限重试，机制生效）。

## 9. 当前限制

```text
LangGraph：未接入
Text2SQL：未实现
Schema Linking：未实现
Few-shot：未实现
SQL Validator：未实现
SQL Repair：未实现
RAG（Embedding / 向量库 / Retriever）：未实现
其他 Provider（DeepSeek / OpenAI 等）：本阶段只保留抽象，未实现
/ api/health 不依赖 Mimo：第三方 API 不可用时 SQLite 后端仍正常运行
```