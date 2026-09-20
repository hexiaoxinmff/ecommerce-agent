# Task 27 Defense Materials Completion

> **勘误（Task 28 追加，2026-09-17）**：§4 中「PPTX 已重新导出覆盖 …（16 页 / **466 可编辑文本对象**）」的数字**已过期**。
> Task 28 修复 3 处渲染缺陷（P12 / P9 / P6）后已**再次重新导出**，当前为
> **16 slides / 25 media / 456 可编辑文本对象 / 20,090,263 B**（文本对象数下降系移除冗余单位 span，非可编辑性下降）。
> 另：旧版 PPTX 已归档至 `reports/_archive_pptx/`。详见 `reports/task28_final_delivery.md`。
> 本文档其余内容（Demo Script / Defense Q&A / 检查清单）**不受影响**。

> 阶段：Task 27（最终 Demo Script + Defense Q&A + 答辩检查清单）
> 日期：2026-09-16 ｜ 状态：**DEFENSE READY**
> 约束遵守：未开发新功能、未做新实验、未跑 100 条 Benchmark、未修改代码/E3/Gold/Prompt/Few-shot/DB、未 commit。

---

## 1. Demo Script

✅ `reports/DEMO_SCRIPT.md`

- 13 节结构（总时长 / 开场话术 / 环境启动 / Demo 1~4 / Trace 展示 / SQL 展示 / E3 案例讲解 / 异常处理 / 兜底方案 / 结束话术）；
- 4 个 Demo 全部为 Task 23 E2E Smoke 已验证问题（广东 246 / 12 行 / Top5 / 家用电器 1 行），来源 `reports/eval/task23_final_acceptance/e2e_smoke.json`；
- 每个 Demo 按「问题 → Schema Linking → Few-shot → SQL → Safety → Execute → Result → Trace」讲解，强调"用户面对自然语言，系统产出可执行 SQL"；
- Trace：至少展示一次，解释节点/状态/耗时/execute_count/repair_count，强调有界控制式流程；
- SQL：推荐 Demo 1/4，展示"生成 → 安全 → 只读执行 → 结构化结果"，**禁止现场手改 SQL**；
- E3：口述案例（不现场跑），含 4.14× 放大与「OFF/ON 观测差异、alarm n=1、PoC」口径；
- 异常处理与兜底：全部指向"已准备的截图/Trace/e2e_smoke.json"，不临时换问题、不编数据。

## 2. Defense Q&A

✅ `reports/DEFENSE_QA.md`

- **35 个问题**（超过"至少 20 个"要求），A~G 七组：背景(3) / 技术架构(7) / SQL·数据库(5) / Evaluation(5) / E3(5) / 项目不足(6) / AI 协作(4)；
- 每题严格五段式：**Q / 标准回答(30~80 字) / 追问 / 追问回答(30~100 字) / 证据**；
- 高风险问题 7 个全部标记【高风险·必背】并给出专项速答表（H 节）：90% 来源、E3 是否调 Prompt 涨 3%、≤8s 未达标、Spider 自造数据、Multi-turn、SSE、**创新点到底是什么**；
- 回答原则统一：先一句话 → 再解释 → 最后指向仓库证据，不回避、不夸大、不甩锅。

## 3. Defense Checklist

✅ `reports/DEFENSE_CHECKLIST.md`

- 四段可执行清单：**前一天**（PPT/Demo/Backend/Frontend/Mimo Key/数据库/截图/备份）→ **上台前**（服务启动/页面打开/Query 准备）→ **演示中**（顺序 普通→聚合→TopN→JOIN，再 SQL/Trace、最后 E3）→ **异常处理**（截图兜底，红线：不临造问题/不改代码/不跑 Benchmark）。

## 4. PPT Final Correction

✅ Task 26 P11 措辞已修正并重新导出：

- goal.json P11（page018 milestones E-0099）：
  原「生成后执行失败，交由 Repair 加固」→ 新「**生成后执行报错 → 触发 Repair，但该样本修复仍失败**」；
- 已重新渲染（16 slide）+ `validate:goal-spec / swiss / goal-copy` 全部 PASS；
- PPTX 已重新导出覆盖：`reports/基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx`（16 页 / 466 可编辑文本对象）；
- `reports/PPT_CONTENT.md` P11 同步修正；
- 已核验渲染产物包含新表述、不含旧表述；其余 PPT 数据未改动。

## 5. High-risk Questions

独立覆盖 7 个高风险问题（DEFENSE_QA.md §H + 对应编号题内标记）：

1. **90% 怎么来的** → 100 条串行实测 + Gold Hash/Leakage 双门禁 + 报告落盘可复现；
2. **E3 是否调 Prompt 涨 3%** → 观测差异、非严格单变量、仅 E-0086 +1pt 归因、alarm n=1；
3. **≤8s 未达标** → 平均 10.9s、主因两次 Mimo 串行推理、如实披露 P1 及改进方向；
4. **Spider 自造数据** → 自建合成库（seed 可复现）+ 自建 100 条评测集，数量达成、来源差异披露 + 三重校验；
5. **Multi-turn 未做** → PRD 阶段 2 / Out-of-Scope，先单轮闭环后迭代；
6. **SSE 未实现** → REST 整包返回、前端动画非流式、差异披露、列后续工作；
7. **创新点到底是什么** → ① Gold-independent Fan-out 检测（E3 实证）② 有界可审计控制式 Agent ③ 规则型可解释 Few-shot ④ 只读安全 + 有界自修复。

## 6. Evidence Coverage

- 所有答案/脚本均指向仓库真实材料：`FINAL_ACCEPTANCE_REPORT.md`、`FINAL_DELIVERY_GAP_CHECK.md`、`E3_FINAL_FREEZE.md`、`clean_baseline_v1_1/`、`task17~21/`、`e2e_smoke.json`、`docs/` 全套、`backend/app/` 关键模块路径；
- 口径统一：EX 90.0% / Exec 99.0% / Pass@1 90.0% / Provider 0 / Timeout 0 / E3 观测差异 / 4.14× / alarm n=1。

## 7. Final Delivery Files

```text
reports/
├── 基于Text2SQL的电商智能数据分析Agent_答辩PPT.pptx   ✅ 16 页可编辑（P11 已修正）
├── PPT_CONTENT.md                        ✅ 全部文字 + 演讲节奏
├── DEMO_SCRIPT.md                        ✅（Task 27 新增）
├── DEFENSE_QA.md                         ✅ 35 题 + 7 高风险（Task 27 新增）
├── DEFENSE_CHECKLIST.md                  ✅（Task 27 新增）
├── FINAL_DELIVERY_GAP_CHECK.md           ✅（Task 25）
├── FINAL_ACCEPTANCE_REPORT.md            ✅（Task 23）
└── ...（历史报告/ppt_assets 截图素材保留）
```

## 8. Final Status

**DEFENSE READY**

- 验证项：Markdown 结构正常；PPT 存在且 P11 措辞已修正；Demo Script / Defense Q&A（35 题）/ Checklist 三份材料存在；数据口径与冻结实验数据一致；
- 未违反任何禁止项：未跑 Mimo Benchmark、未修改代码 / E3 / Gold / Prompt / Few-shot / DB、未 git commit；
- 后续不再开发新功能。如老师要求再调整，改 `reports/task26_ppt/goal.json` → 重渲染 → 重导出（需 `OPENSSL_PATH=D:\Git\usr\bin\openssl.exe`）。

---

*生成：Task 27（2026-09-16）。*