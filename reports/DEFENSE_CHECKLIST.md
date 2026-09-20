# Defense Checklist（答辩前检查清单）

> 用途：答辩前一天与上台前的可执行检查表。按顺序逐项打勾。
> 原则：现场不修改代码、不跑 Benchmark、不临时创造问题；一切以"已验证材料"兜底。

---

## 前一天

### PPT
- [ ] `reports/基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx` 在 U 盘 + 电脑各一份
- [ ] 按 `reports/PPT_CONTENT.md` 预演一遍（16 页，10~15 分钟）
- [ ] PPT 内指标与冻结数据核对（EX 90.0% / Exec 99.0% / Pass@1 90.0% / E3 观测差异口径）

### Demo
- [ ] 4 条 Demo 问题口播稿已过（`reports/DEMO_SCRIPT.md`）
- [ ] 确认不用现场新造问题：①哪个地区的用户最多？②2025年每月销售额是多少？③近30天销量最高的商品 Top 5 是哪些？④哪个类目的销售额最高？

### Backend / Frontend
- [ ] 本机可启动后端：`cd backend && ..\.venv\Scripts\python -m uvicorn app.main:app --reload`
- [ ] 本机可启动前端：`cd frontend && npm run dev`
- [ ] 端口空闲（8000 / 5173），无残留进程占用

### Mimo Key / 数据库
- [ ] `.env` 中 `MIMO_API_KEY` 已配置（仅本机 .env，不带进任何展示材料）
- [ ] `db/ecommerce.db` 存在且可只读打开（`curl http://127.0.0.1:8000/api/health` → ok）
- [ ] 有网络（可访问 https://api.xiaomimimo.com/v1）

### 截图 / 备份材料（现场兜底包）
- [ ] 首页截图 `reports/ppt_assets/01_home.png`
- [ ] 真实结果截图 `reports/ppt_assets/03_result.png`（广东/246）
- [ ] SQL+Trace 截图 `reports/ppt_assets/05_sql_trace.png`
- [ ] E2E 实测记录 `reports/eval/task23_final_acceptance/e2e_smoke.json`
- [ ] 备份：PPT 再拷一份到 U 盘 / 网盘

---

## 上台前（教室现场）

- [ ] **Backend 已启动**（终端可见 `Uvicorn running on http://127.0.0.1:8000`）
- [ ] **Frontend 已启动**（终端可见 `localhost:5173`）
- [ ] 健康检查通过：`curl http://127.0.0.1:8000/api/health` → `status: ok`
- [ ] LLM 链路验证：`POST /api/llm/test` 返回 success（可选，10 秒）
- [ ] **浏览器页面已打开**：http://localhost:5173 停留在「智能分析」页
- [ ] Demo Query 已复制在剪贴板（4 条），不靠现场打字
- [ ] **PPT 已打开**到封面，翻页器/投屏切换正常
- [ ] 投屏分辨率下 PPT 文字可见（可提前试投一次）

---

## 演示中

- [ ] 顺序：Demo 1 普通查询 → Demo 2 聚合/时间 → Demo 3 Top-N → Demo 4 多表 JOIN
- [ ] 每个 Demo 讲链路：问题 → Schema Linking → Few-shot → SQL → Safety → Execute → Result
- [ ] **展示 SQL**（Demo 1 或 Demo 4，已默认展开，不在现场手改）
- [ ] **展示 Trace**（一次即可）：节点、成功/失败/Skip、耗时、execute_count、repair_count，强调有界（≤1 修复 / ≤2 执行）
- [ ] Demo 间穿插讲解：用户看到的是自然语言，系统内部产出的是可执行 SQL
- [ ] **最后讲 E3**（口述案例，不现场跑）：
      orders×order_items → 4.14× 放大（369854.65→89397.46）→ Detector→Alarm→Hint→1 次 regeneration→EX✗→EX✓
- [ ] 讲 E3 边界：proof of concept / alarm n=1 / **OFF 90%·ON 93% 是观测差异，不代表提升 3pt**
- [ ] 控制总时长 10~15 分钟（PPT 页时长见 `PPT_CONTENT.md`）

---

## 如果出现异常

- [ ] **Mimo 502/503/超时** → 不临时换问题、不编数据；切换到截图 / Trace 材料讲解
- [ ] **前端连不上后端** → 检查后端是否启动、`VITE_API_BASE_URL` 是否指向 8000；不行就切截图
- [ ] **模型响应过慢** → 不等，直接讲已准备的「截图 + Trace」材料
- [ ] **现场断网 / 无 Key** → 全程用截图 + PPT + e2e_smoke.json 讲完演示
- [ ] **被追问超纲** → 遵循「先一句话 → 再解释 → 给证据」，证据见 `reports/DEFENSE_QA.md`

### 绝对禁止（现场红线）
- [ ] 不修改任何代码
- [ ] 不现场跑 Benchmark（`python scripts/run_eval.py` 不执行）
- [ ] 不临时创造没人验证过的复杂问题
- [ ] 不宣称已实现的功能（Multi-turn / 用户登录 / 结论生成 / SSE / 完整 Schema 可视化均未实现）

---

*编写：Task 27（2026-09-16）。与 DEMO_SCRIPT.md / DEFENSE_QA.md / PPT_CONTENT.md 配套使用。*