"""结果归一化与 EX 等价比较（evaluation-dataset-spec.md §D1~D9 唯一权威实现）。

设计要点：
- 列名 / alias 不敏感：比较只针对「每行的值集合」，greek 列顺序任意；
- 列数量必须可比（gold 有 n 列、pred 只有 m 列 → 不等价，m≠n 判错）；
- 每行做单元格归一化（None→空串、float→round 6），再整体排序（列顺序无关）；
- 非排名结果：集合等价（行升序比较）；
- 排名结果（order_sensitive=true）：先集合验证，再按 gold 行顺序逐行
  验证（并列容忍：只要行内值集合一致即视为该位次匹配，覆盖 D7 并列键内部顺序忽略）；
- 数值：integer 精确；float 按 round(v,6)，金额 currency 按 tolerance 规则；
- 空结果：仅在 expected_empty=true 时 gold 空视为合法基准，pred 空才判对。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 与 validate_eval_dataset.normalize_result_hash 保持一致的 None 归一化
_NULL_TOK = ""


@dataclass
class NormalizedResult:
    """一套规范化后的结果（列数 + 行集合 + 行内值类型标记）。"""

    column_count: int
    rows: list[tuple[Any, ...]]  # 每行已按值排序（列顺序无关）
    order_rows: list[tuple[Any, ...]] | None  # 排名题保留 gold 原始行顺序快照
    expected_empty: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class ComparisonOutcome:
    """单题比较结果。"""

    match: bool
    reason: str = ""
    detail: str = ""
    # 诊断用途
    gold_row_count: int = 0
    pred_row_count: int = 0


def _normalize_cell(value: Any, *, tolerance: float, is_currency: bool) -> Any:
    """单元格归一化：None→""、float→round(v,6)；返回可比较对象。"""
    if value is None:
        return _NULL_TOK
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            return value
        if is_currency:
            return round(value, 2)
        return round(value, 6)
    return value


def _row_as_sorted_tuple(
    values: list[Any], *, tolerance: float, is_currency: bool
) -> tuple[Any, ...]:
    """把一行变成「按值排序的元组」，从而消除列名与列顺序差异。"""
    norm = [_normalize_cell(v, tolerance=tolerance, is_currency=is_currency) for v in values]
    # 键：类型名 + repr，保证整数/字符串/布尔不混排
    return tuple(sorted(norm, key=lambda x: (type(x).__name__, repr(x))))


def _cell_approx_equal(
    gold: Any,
    pred: Any,
    *,
    tolerance: float,
    is_currency: bool,
) -> bool:
    """单元格等值判断：数值带 tolerance / 其他精确。"""
    g = _normalize_cell(gold, tolerance=tolerance, is_currency=is_currency)
    p = _normalize_cell(pred, tolerance=tolerance, is_currency=is_currency)
    if isinstance(g, (int, float)) and isinstance(p, (int, float)) and not isinstance(g, bool) and not isinstance(p, bool):
        if tolerance and tolerance > 0:
            if is_currency:
                diff = abs(p - g)
                bound = max(0.01, abs(g) * tolerance)
                return diff <= bound
            return abs(p - g) <= abs(g) * tolerance
        return round(g, 6) == round(p, 6)
    return g == p


def _row_numeric_keys(row: tuple[Any, ...]) -> tuple:
    """抽取行内数值键（升序）；无数值时用完整 repr 键（回退精确比较）。"""
    nums = tuple(
        v for v in row if isinstance(v, (int, float)) and not isinstance(v, bool)
    )
    if nums:
        return tuple(nums)
    return tuple(repr(v) for v in row)


def _rows_ordered_equal(
    gold_rows: list[tuple[Any, ...]],
    pred_rows: list[tuple[Any, ...]],
    *,
    tolerance: float,
    is_currency: bool,
) -> bool:
    """排名 / 有序题：按「排序键序列」逐位验证（并列键内部顺序忽略，D7）。

    集合一致性已在前置验证；此处只检查排名键（名次）序列：
    - 数值键：取每行数值升序序列（如销量/金额）；
    - 同值并列时允许内部姓名等维度互换；
    - 无数值列（异常）回退完整 repr 序列精确比较。
    """
    if len(gold_rows) != len(pred_rows):
        return False
    gold_keys = [_row_numeric_keys(r) for r in gold_rows]
    pred_keys = [_row_numeric_keys(r) for r in pred_rows]
    for gk, pk in zip(gold_keys, pred_keys):
        if len(gk) != len(pk):
            return False
        for gv, pv in zip(gk, pk):
            if not _cell_approx_equal(
                gv, pv, tolerance=tolerance, is_currency=is_currency
            ):
                return False
    return True


def _rows_set_equal(
    gold_rows: list[tuple[Any, ...]],
    pred_rows: list[tuple[Any, ...]],
    *,
    tolerance: float = 0.0,
    is_currency: bool = False,
) -> bool:
    """非有序题：集合等价（行升序后整体比较，列顺序已在行内归一化消除）。"""
    if len(gold_rows) != len(pred_rows):
        return False
    g = sorted(gold_rows, key=lambda x: [repr(v) for v in x])
    p = sorted(pred_rows, key=lambda x: [repr(v) for v in x])
    for gr, pr in zip(g, p):
        if len(gr) != len(pr):
            return False
        for gv, pv in zip(gr, pr):
            if not _cell_approx_equal(
                gv, pv, tolerance=tolerance, is_currency=is_currency
            ):
                return False
    return True


def normalize_result(
    columns: list[str],
    rows: list[list[Any]],
    *,
    value_type: str = "",
    tolerance: float = 0.0,
    order_sensitive: bool = False,
    expected_empty: bool = False,
) -> NormalizedResult:
    """把原始执行结果列+行转为规范化结果对象。"""
    is_currency = value_type in ("currency", "ratio", "scalar_number")
    norm_rows = [
        _row_as_sorted_tuple(r, tolerance=tolerance, is_currency=is_currency)
        for r in rows
    ]
    order_rows = (
        list(norm_rows) if (order_sensitive and rows) else None
    )
    return NormalizedResult(
        column_count=len(columns),
        rows=norm_rows,
        order_rows=order_rows,
        expected_empty=expected_empty,
    )


def compare_results(
    gold: NormalizedResult,
    pred: NormalizedResult,
    *,
    value_type: str = "",
    tolerance: float = 0.0,
    order_sensitive: bool = False,
) -> ComparisonOutcome:
    """gold 与 pred 两个规范化结果比较，返回是否等价 + 原因。"""
    # 空结果规则（D8）
    if gold.row_count == 0 and not gold.expected_empty:
        return ComparisonOutcome(
            match=False,
            reason="gold 结果为空但未声明 expected_empty（基准异常，判错）",
            gold_row_count=0,
            pred_row_count=pred.row_count,
        )
    if gold.expected_empty and gold.row_count == 0:
        match = pred.row_count == 0
        return ComparisonOutcome(
            match=match,
            reason="基准声明空结果" if match else "基准为空结果，但 pred 非空",
            gold_row_count=0,
            pred_row_count=pred.row_count,
        )

    # pred 为空但基准非空 → 判错（D8）
    if pred.row_count == 0:
        return ComparisonOutcome(
            match=False,
            reason="pred 结果为空（基准非空）",
            gold_row_count=gold.row_count,
            pred_row_count=0,
        )

    # 列数量必须可比（D1）
    if gold.column_count != pred.column_count:
        return ComparisonOutcome(
            match=False,
            reason=f"列数不一致：gold={gold.column_count} pred={pred.column_count}",
            gold_row_count=gold.row_count,
            pred_row_count=pred.row_count,
        )

    is_currency = value_type in ("currency", "ratio", "scalar_number")

    if order_sensitive:
        # ① 集合验证：pred Top-K 集合 == gold Top-K 集合（D7）
        if not _rows_set_equal(
            gold.rows, pred.rows, tolerance=tolerance, is_currency=is_currency
        ):
            return ComparisonOutcome(
                match=False,
                reason="排名题集合不一致",
                gold_row_count=gold.row_count,
                pred_row_count=pred.row_count,
            )
        # ② 顺序验证：逐位（并列容忍）
        ordered = _rows_ordered_equal(
            gold.rows, pred.rows, tolerance=tolerance, is_currency=is_currency
        )
        if not ordered:
            return ComparisonOutcome(
                match=False,
                reason="排名题顺序不一致（非并列错位）",
                gold_row_count=gold.row_count,
                pred_row_count=pred.row_count,
            )
        return ComparisonOutcome(
            match=True,
            reason="",
            gold_row_count=gold.row_count,
            pred_row_count=pred.row_count,
        )

    # 非有序：集合等价（行内列顺序已被归一化消除）
    if not _rows_set_equal(
        gold.rows, pred.rows, tolerance=tolerance, is_currency=is_currency
    ):
        return ComparisonOutcome(
            match=False,
            reason="结果集合不一致",
            gold_row_count=gold.row_count,
            pred_row_count=pred.row_count,
        )
    return ComparisonOutcome(
        match=True,
        reason="",
        gold_row_count=gold.row_count,
        pred_row_count=pred.row_count,
    )


def rows_as_hashable_payload(
    columns: list[str], rows: list[list[Any]]
) -> list[tuple[Any, ...]]:
    """审计用：返回排序后的可序列化规范行（与 hash 逻辑一致，无需 db）。"""
    return [
        tuple(
            "" if v is None else (round(v, 6) if isinstance(v, float) else v)
            for v in row
        )
        for row in rows
    ]


def gold_hash(columns: list[str], rows: list[list[Any]]) -> str:
    """对 gold/pred 执行结果计算规范 hash（防漂移 / 审计，算法与 dataset spec §C 一致）。

    注意：Runner 判定 EX 用的是 compare_results（值比较），此 hash 仅用于
    Gold Hash Gate 的漂移检测，不用于判定预测正确。
    """
    import hashlib
    import json

    col_norm = [str(c) for c in columns]
    serialized = []
    for row in rows:
        values = []
        for value in row:
            if value is None:
                values.append("<null>")
            elif isinstance(value, float):
                values.append(round(value, 6))
            else:
                values.append(value)
        serialized.append(json.dumps(values, ensure_ascii=False, separators=(",", ":")))
    serialized.sort()
    payload = json.dumps(
        {
            "columns": col_norm,
            "rows": [json.loads(r) for r in serialized],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()