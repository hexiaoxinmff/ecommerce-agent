# Task36 幻灯片逐页检查表

> 文件：`基于Text2SQL的电商智能数据分析Agent_项目汇报.pptx`
> 风格：极简奶白汇报风（奶白背景 `#F7F3EA`、深灰文字、单强调色深棕 `#74543A`、大留白、无 3D/渐变/HUD/多色）
> 数据唯一来源：Task35（`task35_report_ready_results/`）。所有数字与 Task35 严格一致，未改动实验数据。

| 页 | 标题 | 核心信息 | 数据来源 | 视觉检查 |
|:--:|------|---------|---------|:------:|
| 01 | 封面 | 项目名称 / 自然语言驱动的数据查询与分析 / 一句话定位 | Task35 叙事 | ✅ 通过 |
| 02 | 从问题到洞察 | 自然语言 → Schema 理解 → SQL 生成 → 安全校验 → 执行/自修复 → 图表与结论（6 段横向流程） | Task35 系统流程 | ✅ 通过 |
| 03 | Agent 核心架构 | Schema Linking / Few-shot / SQL Generation / SQL Safety / SQL Execute / Repair / Result（7 模块简块图） | Task35 核心架构 | ✅ 通过 |
| 04 | Text2SQL 核心链路 | 问题解析 → Schema Link → SQL Generate → Safety → Execute → Repair；强调“错误进入受控修复链路” | Task35 Text2SQL 链路 | ✅ 通过 |
| 05 | 安全与可靠性 | SELECT/WITH only、Read-only、Multi-statement blocked、PRAGMA blocked、Result limit、Repair ≤ 1 | Task35 安全护栏清单 | ✅ 通过 |
| 06 | 正式 100Q 评测 | 大数字 100Q；Frozen Baseline 90.00%；Task58 81.00%（Raw EX，并列展示） | Task35 正式 100Q | ✅ 通过 |
| 07 | 正式评测：原始结果与可评价口径 | Frozen「Raw 90/100 · Adjusted 90/96」/ Task58「Raw 81/100 · Adjusted 81/98」 | Task35 双口径 | ✅ 通过 |
| 08 | Benchmark 口径审计 | E-0096 / E-0100 Gold↔Business Rule conflict；E-0082 / E-0083 Gold extra column；结论“评测口径所致” | Task35 Gold validity 审计 | ✅ 通过 |
| 09 | 专项 Contract 验证 | CONTRACT_A/B（Task26）10/12；CONTRACT_C（Task27）12/12 | Task35 专项契约 | ✅ 通过 |
| 10 | Blind Evaluation | Blind 10Q 8/10（80%）；Blind 25Q 21/25（84%）；Task29 34/36（94.4%） | Task35 盲测子集 | ✅ 通过 |
| 11 | Provider 与评测有效性 | Provider failures 69/100；Valid model runs 31；INVALID_FOR_CAPABILITY_ESTIMATE（29% 不作能力成绩） | Task35 · Task81 | ✅ 通过 |
| 12 | 项目结论 | 三结论（链路完成 / 分层验证体系 / Gold 审计与双口径）+ 谢谢 | Task35 | ✅ 通过 |

## 检查项目

1. **页面尺寸**：16:9（13.333 × 7.5 in）— ✅
2. **字体**：中文 Microsoft YaHei，数字/英文 Aptos；中文字体正常显示 — ✅
3. **文本溢出**：逐页检查，无溢出 — ✅
4. **元素重叠**：无重叠 — ✅
5. **空白比例**：大留白，符合一页一结论 — ✅
6. **数字一致性**（与 Task35 核对）：
   - 90%（90/100）、81%（81/100）— ✅
   - Adjusted 90/96、81/98（对应 93.75% / 82.65%）— ✅
   - Task26 10/12（83.3%）、Task27 12/12 — ✅
   - Blind 80%、84%、Task29 94.4% — ✅
   - Task81 69/100、31、INVALID — ✅
7. **中文乱码**：无乱码 — ✅
8. **每页截图检查**：全部 12 页导出 PNG 逐页查看 — ✅（封面标题已修正为单行居中）

## 合规性

- ✅ 恰好 12 页
- ✅ 奶白背景、深灰文字、单一强调色
- ✅ 无科技蓝 / 渐变 / 3D / HUD / 霓虹
- ✅ 无“显著提升 / 行业领先 / 综合优异”等宣传语
- ✅ 无“全项目总准确率”/“模型总体 100%”
- ✅ Task81 的 29% 不作为能力成绩，未做成大标题
- ✅ Task27 12/12、Task29 34/34 均标注限定，不外推为整体