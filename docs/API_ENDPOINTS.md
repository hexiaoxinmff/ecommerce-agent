# API 端点权威清单（唯一事实源）

> **本文件由 `scripts/export_api_endpoints.py` 自动生成，请勿手改。**
> 任何手改都会让 `backend/tests/test_api_endpoints_manifest.py` 变红。

- **端点总数：18**
- **router 数：12**
- **需鉴权（Bearer）：6** ／ **公开：12**

推导源：`backend/app/main.py` 的 `include_router` 顺序 + `app.openapi()` 的 `paths` / `summary` / `security`，以及 `app.routes` 展开后的 `endpoint.__module__`。
也就是说：**改代码 = 改这份清单**，没有第二个人需要记得同步。

## 清单

| # | router | method | path | 用途 | 鉴权 | 响应模型 |
|---:|---|---|---|---|---|---|
| 1 | `health` | `GET` | `/api/health` | 服务健康检查 | 公开 | `HealthResponse` |
| 2 | `system` | `GET` | `/api/system/database` | 数据库信息（只读验证） | 公开 | `DatabaseInfo` |
| 3 | `system` | `GET` | `/api/system/schema` | 数据库 Schema 元数据（只读） | 公开 | `SchemaResponse` |
| 4 | `insights` | `GET` | `/api/insights/overview` | 首页业务概览（只读聚合 + Bearer 鉴权，不调用 LLM） | 需要 Bearer | `OverviewResponse` |
| 5 | `llm` | `POST` | `/api/llm/test` | LLM 连接测试（真实调用当前 Provider） | 公开 | `LlmTestResponse` |
| 6 | `schema_link` | `POST` | `/api/schema/link` | Schema Linking（识别问题相关表与字段） | 公开 | `SchemaLinkResponse` |
| 7 | `fewshot` | `POST` | `/api/fewshot/retrieve` | Few-shot 示例检索（规则型，Top-K） | 公开 | `FewShotRetrieveResponse` |
| 8 | `sql_generate` | `POST` | `/api/sql/generate` | SQL 生成（Text2SQL，只生成不执行） | 公开 | `SQLGenerationResponse` |
| 9 | `sql_execute` | `POST` | `/api/sql/execute` | SQL 执行（只读 SELECT/WITH，结构化结果） | 公开 | `SQLExecutionResponse` |
| 10 | `sql_repair` | `POST` | `/api/sql/repair` | SQL 修复（单独测试 Repair 能力，不执行 Repair SQL） | 公开 | `SQLRepairResponse` |
| 11 | `sql_repair` | `POST` | `/api/sql/execute-with-repair` | SQL 执行（有限 Repair 闭环：最多 1 次修复 / 2 次执行） | 公开 | `SQLExecuteWithRepairResponse` |
| 12 | `auth` | `POST` | `/api/auth/register` | 注册新用户（username/email 冲突返回 409） | 公开 | `UserOut` |
| 13 | `auth` | `POST` | `/api/auth/login` | 登录并签发 Bearer access_token（会话只存 token_hash） | 公开 | `LoginResponse` |
| 14 | `auth` | `GET` | `/api/auth/me` | 当前登录用户（Bearer 认证） | 需要 Bearer | `UserOut` |
| 15 | `auth` | `POST` | `/api/auth/logout` | 登出（删除当前 token 对应的服务端会话） | 需要 Bearer | `—` |
| 16 | `history` | `GET` | `/api/history` | 当前用户的查询历史（created_at 倒序 + 分页） | 需要 Bearer | `HistoryListResponse` |
| 17 | `history` | `DELETE` | `/api/history/{history_id}` | 删除本人一条查询历史（不属于本人或不存在 → 404） | 需要 Bearer | `—` |
| 18 | `agent` | `POST` | `/api/agent/analyze` | Text2SQL Agent 编排分析（LangGraph，≤1 次修复，含 Trace，需登录） | 需要 Bearer | `AgentResponse` |

## 各文档如何引用

其余文档（`README.md`、`docs/API.md`、`docs/project-parameters.md`、`docs/DEPLOYMENT.md`、`docs/TEST_REPORT.md`）不各自维护数字，而是嵌入由本脚本重写的 marker 区块。
