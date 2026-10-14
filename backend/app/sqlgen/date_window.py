"""Task60 —— E12：时间窗口语义保持契约（条件性注入，默认关闭）。

背景（Task58 / Task59 证据）
----------------------------
Task58 的 19 个失败中，DATE_FILTER_ERROR 是最大单一类（7 例）。Task60 的 0-API
日期语义引擎确认：7 例全部是**真日期错误**，且 5 例是「整段丢弃时间窗」，
2 例是「收窄时间窗」——即模型把用户问题里明确给出的时间窗口**漏掉了或改小了**。

设计原则（严格对齐任务书 §10 / §12 / §21）
-----------------------------------------
1. **只做一层**：仅 Prompt constraint，不加 few-shot、不加 deterministic guard。
2. **只表达语义，不规定写法**：要求「保持用户问题中的时间窗口语义不变」，
   明确声明 range / >=、< / BETWEEN / LIKE / substr / strftime / CAST **任意写法都可以**，
   只要过滤出的日期集合一致。绝不要求与 Gold SQL 写法相同。
3. **默认关闭**：只有 `SQLGEN_EXTRA_RULES` 含 `E12` 时才可能注入；
   且**条件性**——只有题目被确定性识别为「已指定时间范围」才追加，
   其余题目即使 E12 打开也不注入 ⇒ 未开启时 Prompt 与冻结基线逐字节相同。
4. **不碰 E11**：本模块不 import `semantic_contracts`，不修改任何 E9/E10/E11 逻辑。

与 E9（Global Scope）的边界
---------------------------
E9 管的是「全局口径不得继承外层时间过滤」（参照基准问题）；
E12 管的是「用户已给出的时间窗口不得被丢弃/收窄/位移」。二者语义不同，互不替代。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- 检测

# 每一类都是「用户问题里已经给出了时间范围」的确定性线索。
# 顺序即优先级（仅用于报告展示命中原因，不影响是否注入）。
_DATE_WINDOW_PATTERNS: list[tuple[str, str]] = [
    # ⚠️ 必须带「年」字：裸 4 位数会把价格档位「2000元」误判成年份
    #    （Task60 实测踩过：E-0029 价格分档题被误命中 E12）。
    ("explicit_year", r"20\d{2}\s*年"),
    ("quarter", r"第\s*[一二三四1234]\s*季度|季度|[Qq][1-4]\b"),
    ("half_year", r"[上下]半年"),
    ("month", r"\d{1,2}\s*月|[一二三四五六七八九十]{1,3}月"),
    ("relative_days", r"最近\s*\d+\s*[天日周月年]|近\s*\d+\s*[天日周月年]|过去\s*\d+\s*[天日周月年]"),
    ("ytd", r"年初至今|截至|截止到|至今"),
    ("this_period", r"今年|去年|明年|本月|上月|上个月|本季度|上季度|本年度|当季|当期"),
    ("annual", r"全年|年度|全年度|财年"),
    ("yoy", r"同比|环比|同月|同期"),
]


@dataclass
class DateWindowContract:
    """题目里已识别出的时间窗口线索（仅作为「必须保持语义」的依据）。"""

    question: str
    matched: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        return (
            "【时间窗口语义保持】（重要）\n"
            "- 用户问题中已经给出了时间范围（年份 / 季度 / 月份 / 上半年·下半年 / "
            "最近 N 天等）时，生成 SQL **必须把该时间窗口完整地落到日期过滤上**，不得省略；\n"
            "- 不得缩小、不得扩大、不得移动窗口边界；不得改变 AND/OR 语义；"
            "不得丢失上界或下界；不得改变日期粒度（年 / 月 / 日 / 时间戳）；\n"
            "- 时间窗口必须作用于**回答该问题所需的主数据集**（即用于分组、聚合、"
            "排序取 Top-N 的那批记录），不能只写在某一个 CASE WHEN 分支里、"
            "而让其余聚合仍然覆盖全部时间；\n"
            "- 若问题本身要求某个参照量按更大范围计算（例如「全平台平均」这类全局基准），"
            "该参照量按其自身口径计算，不要强行套用时间窗口；\n"
            "- **允许使用任意语义等价的 SQL 写法**（范围比较、>= 与 <、BETWEEN、LIKE 前缀、"
            "substr、strftime、CAST 等均可），不要求与参考答案写法一致；"
            "判断标准是「过滤出的日期集合是否一致」，而不是「写法是否一致」。\n"
        )


def detect_date_window(question: str) -> DateWindowContract | None:
    """确定性识别题目是否已给出时间范围；未给出则返回 None（不注入）。"""
    if not question:
        return None
    matched = [name for name, pat in _DATE_WINDOW_PATTERNS if re.search(pat, question)]
    if not matched:
        return None
    return DateWindowContract(question=question, matched=matched)
