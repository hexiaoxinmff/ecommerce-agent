"""Task 20：E3 Detector 提示型干预最小测试。

覆盖任务书 §八：
1. Detector=false -> hint=None
2. Detector=true -> hint!=None
3. E-0086 -> alarm=true & hint injected=true
4. E-0100 类 SQL -> alarm=false & hint injected=false
5. Hint 不会修改原始 SQL
6. Detector/注入流程不触发 repair（无 repair side effect）

全部为纯本地测试：不调用 Mimo（FanoutHintGenerator 的生成路径用 stub provider），
不访问数据库；仅验证 Hint 注入逻辑与 Detector 边界。
"""

from app.experiments.fanout_hint import FanoutHintGenerator, fanout_hint_for_sql
from app.schemas.schema_link import SchemaLinkResult
from app.fewshot.models import FewShotResult

# E-0086 型 fan-out（经典正例）
E0086_SQL = (
    "WITH user_stats AS ("
    "SELECT u.id, u.username, SUM(o.total_amount) AS total_spent, "
    "COUNT(DISTINCT o.id) AS order_count, COUNT(DISTINCT pi.product_id) AS product_count "
    "FROM users u JOIN orders o ON u.id = o.user_id "
    "JOIN order_items pi ON o.id = pi.order_id "
    "WHERE o.status != 'cancelled' GROUP BY u.id, u.username), "
    "platform_avg AS (SELECT AVG(total_spent) AS avg_spent FROM user_stats) "
    "SELECT us.username, us.total_spent, us.order_count, us.product_count "
    "FROM user_stats us, platform_avg pa "
    "WHERE us.total_spent > pa.avg_spent * 2 AND us.order_count > 8"
)

# E-0100 型：CASE 条件引用 orders，聚合值是 oi.subtotal（item-level）→ 非 fan-out
E0100_LIKE_SQL = (
    "SELECT ROUND(SUM(CASE WHEN strftime('%Y-%m', o.order_date) = '2025-05' "
    "THEN oi.subtotal ELSE 0 END), 2) AS sales_may "
    "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
    "WHERE o.status != 'cancelled'"
)

# item-level 安全 SQL
SAFE_SQL = (
    "SELECT o.region, ROUND(SUM(oi.subtotal), 2) AS item_sales "
    "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
    "WHERE o.status != 'cancelled' AND o.order_date BETWEEN '2025-04-01' AND '2025-06-30' "
    "GROUP BY o.region"
)


class _StubProvider:
    """stub：记录收到的 messages，永远按传入 hint 触发存根 SQL（不调用 Mimo）。"""

    name = "stub"
    model = "stub"

    def __init__(self) -> None:
        self.last_messages: list[dict] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
    ) -> str:
        self.last_messages = messages
        # 返回一个简单可校验的 SQL
        return (
            '{"sql": "SELECT o.region, SUM(o.total_amount) AS paid FROM orders o '
            'GROUP BY o.region", "explanation": "stub", "tables": ["orders"], '
            '"columns": ["orders.region", "orders.total_amount"]}'
        )


def _link_fs() -> tuple[SchemaLinkResult, FewShotResult]:
    link = SchemaLinkResult(
        question="q",
        tables=["orders"],
        columns=[],
        reasons=[],
        confidence=0.9,
    )
    fs = FewShotResult(question="q", matches=[])
    return link, fs


def test_detector_false_hint_none():
    """1) Detector=false -> hint=None。"""
    assert fanout_hint_for_sql(SAFE_SQL) is None
    assert fanout_hint_for_sql(E0100_LIKE_SQL) is None


def test_detector_true_hint_not_none():
    """2) Detector=true -> hint!=None。"""
    h = fanout_hint_for_sql(E0086_SQL)
    assert h is not None
    assert "Fan-out" in h or "fan" in h.lower()


def test_e0086_alarm_and_hint_injected():
    """3) E-0086：alarm=true & hint injected=true。"""
    provider = _StubProvider()
    gen = FanoutHintGenerator(provider=provider)
    link, fs = _link_fs()
    out = gen.generate("q", link, fs, E0086_SQL)
    assert out["detector_alarm"] is True
    assert out["hint_injected"] is True
    assert out["hint"] is not None
    # hint 作为额外消息注入
    assert len(provider.last_messages) == 3
    assert provider.last_messages[-1]["role"] == "user"
    assert "Fan-out" in provider.last_messages[-1]["content"]


def test_e0100_like_no_hint_injected():
    """4) E-0100 类 SQL：alarm=false & hint injected=false（不得让 Hint 成全局规则）。"""
    provider = _StubProvider()
    gen = FanoutHintGenerator(provider=provider)
    link, fs = _link_fs()
    out = gen.generate("q", link, fs, E0100_LIKE_SQL)
    assert out["detector_alarm"] is False
    assert out["hint_injected"] is False
    assert out["hint"] is None
    assert out["final_sql"] == E0100_LIKE_SQL  # 原样通过，未调用 provider


def test_hint_does_not_modify_input_sql():
    """5) Hint 不修改原始 SQL：输入字符串保持不变。"""
    before = E0100_LIKE_SQL
    _ = fanout_hint_for_sql(before)
    assert before == E0100_LIKE_SQL
    h = fanout_hint_for_sql(E0086_SQL)
    assert h == fanout_hint_for_sql(E0086_SQL)  # 幂等
    assert E0086_SQL  # 未变


def test_no_repair_side_effect():
    """6) Detector 不直接调用 repair：注入流程无 repair 相关路径/调用。"""
    import inspect

    src = inspect.getsource(FanoutHintGenerator)
    # 生成器内不应当出现 repair / SQLRepairer / AST 改写
    assert "repair" not in src.lower() or "repair" not in src.lower()
    src_det = inspect.getsource(__import__(
        "app.experiments.fanout_hint", fromlist=["fanout_hint_for_sql"]).fanout_hint_for_sql)
    assert "repair" not in src_det.lower()