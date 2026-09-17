"""
跨文件配置不变量检查（**不属于任何运行时层**）。
==================================================

唯一职责：校验那些**单个配置值各自合法、组合起来才成立**的不变量。

为什么必须由检查器读多份配置来核对
----------------------------------
项目硬性要求第 5 条禁止配置文件之间互相引用（不得 ``$ref`` / ``include`` /
``extends``）。这是对的 —— 但代价是**跨文件的关系失去了载体**：``side`` 在
``subscription.json``、绘制/可视窗口在 ``features.json``、桶容量在
``serialization.json``，它们之间的约束没有任何一个文件能表达。

于是这类约束只能由**检查器读多份文件**来核对。配置文件之间仍然零引用，
要求第 5 条不受影响。

检查项
------
``[6]`` 订阅容量 / 绘制与可视窗口 / 窗口容差 / ``use_model_greeks`` 前置条件 / 网格容量
``[11]`` 出站限速桶容量与 IBKR 配额

为什么把"网格容量"也放进 ``[6]``
--------------------------------
它和本节的窗口不变量同族：都是"单个配置值单独看都合法，但组合起来违反一个跨模块
不变量"。放这里不新增编号，也就不牵动 ``selfcheck.py`` 的清单与文档的映射。

⚠️ 每条判据都要写清**违反之后会发生什么** —— 否则后人只看到"数字不对"，不知道
该往哪个方向修，也不知道不修会不会出事。这些约束的共同点是：**违反后程序照常
启动、照常出图、不报任何错**，只是图上悄悄少一段、或者多一条假信号。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import loader  # noqa: E402
from tools.fixtures import make_session_clock  # noqa: E402
from tools.selfcheck_core import fail, ok  # noqa: E402

#: IBKR 硬上限：单个账户最多 100 条行情行。
IBKR_SUBSCRIPTION_LIMIT = 100

#: IBKR 官方规则：出站消息速率上限 = 已分配行情行数 ÷ 2。默认 100 行 → 50 msg/s。
#: 违约错误码 100，累计 3 次会终止 API 会话。
IBKR_MESSAGES_PER_LINE = 2


def check_subscription_capacity() -> int:
    """[6] 订阅容量 / 三个窗口半径 / 容差 / 模型值前置条件 / 网格容量。"""
    print(f"\n[6] 订阅容量、绘制/可视窗口与网格容量（IBKR 硬上限 {IBKR_SUBSCRIPTION_LIMIT}）")

    sub = loader.load("subscription")
    features = loader.load("features")
    ibkr = loader.load("ibkr")
    serial = loader.load("serialization")
    pipeline = loader.load("pipeline")
    transport = loader.load("transport")

    failures = 0

    # ── 6.1 订阅条数不得超过两道上限 ────────────────────────────────
    # ⚠️ 逐键直接调 loader，**不经辅助函数转发 module=** —— 转发会让 `[7]` 的
    # 归属校验无法静态解析（它只认字面量 module=），于是这些键的归属静默失守。
    side = loader.as_int(sub, "num_strikes_each_side", module="subscription")
    cap = loader.as_int(sub, "max_total_subscriptions", module="subscription")
    projected = 4 * side + 1  # ±side 档 × Put/Call + 标的本身

    if projected > IBKR_SUBSCRIPTION_LIMIT:
        fail(f"档位 ±{side} 需要 {projected} 条行情，超过 IBKR 硬上限 "
             f"{IBKR_SUBSCRIPTION_LIMIT} —— 会触发 Error 300（行情行数超限）")
        failures += 1
    elif projected > cap:
        fail(f"档位 ±{side} 需要 {projected} 条，超过自设上限 {cap}")
        failures += 1
    else:
        ok(f"档位 ±{side} → {projected} 条行情（自设上限 {cap}，"
           f"IBKR 上限 {IBKR_SUBSCRIPTION_LIMIT}）")

    # ── 6.2 三个窗口半径的关系 ──────────────────────────────────────
    # 纵轴有两个半径（2026-09-17 起）：
    #   draw    绘制 = 后端每帧**下发**几行（HeatmapEngine 的产出宽度）
    #   visible 可视 = 前端屏幕**显示**几行
    # 加上订阅半径 S，三者必须满足：
    #   draw ≤ S        画超过订阅的档永远拿不到数据（配置看着生效、图上是空的）
    #   visible ≤ draw  可视超过已画的档，露出来的是**空白行**
    #   S − visible ≥ T 容差下限（推导见 6.3）
    draw = loader.as_int(features, "heatmap_draw_rows_each_side", module="features")
    visible = loader.as_int(
        features, "heatmap_visible_rows_each_side", module="features"
    )

    if draw > side:
        fail(f"热力图绘制窗口 ±{draw} 宽于订阅窗口 ±{side}"
             f"（features.json::heatmap_draw_rows_each_side > "
             f"subscription.json::num_strikes_each_side）—— "
             f"超出的档位**永远拿不到数据**，而配置看上去像是生效的")
        failures += 1
        return failures + _check_model_greeks(ibkr)

    ok(f"绘制窗口 ±{draw} ≤ 订阅窗口 ±{side}")

    if visible > draw:
        fail(f"可视窗口 ±{visible} 宽于绘制窗口 ±{draw}"
             f"（features.json::heatmap_visible_rows_each_side > "
             f"heatmap_draw_rows_each_side）—— 可视区两端会露出**空白行**："
             f"帧里根本没有那些档，前端裁不出数据来，而图上不报任何错，"
             f"只表现为上下各少几条数据")
        failures += 1
    else:
        ok(f"可视窗口 ±{visible} ≤ 绘制窗口 ±{draw}"
           f"（每帧发 {2 * draw} 行、屏幕显示 {2 * visible} 行）")

    # ── 6.3 窗口容差 ≥ 重建触发 ────────────────────────────────────
    # 推导（不是拿观测拟合的）：重建触发是"中心行权价偏移 ≥ T 档"。两次重建
    # 之间中心最多滞后 T 档，故现价可探出**已订阅窗口** T 档。此时**可视**窗口
    # 最低一档 = 现价 − (T + V − 1) × 步长，订阅窗口最低一档 = 中心 − (S − 1) × 步长；
    # 要求前者不低于后者即得 S − V ≥ T。
    #
    # ⚠️ 2026-09-17 修正：判据里的半径从**绘制**窗口改成**可视**窗口。旧版拿
    # `heatmap_rows_each_side` 当被减数，是因为当时两者是同一个数（帧 24 行全显示）。
    # 现在绘制窗口比可视窗口宽 8 档，那 8 档永远落在可视区之外 —— 它们退订/复订
    # 只是白跑请求，**用户看不到**，不构成"时间空洞"缺陷。真正会出洞的是**看得见**
    # 的那几档，所以容差必须对着可视窗口算。若仍按绘制窗口算，这条判据会**假红**
    # （把 20 − 20 = 0 判成违约，而实际容差是 20 − 12 = 8）。
    trigger = loader.as_float(sub, "recenter_trigger_strikes", module="subscription")
    tolerance = side - visible
    if tolerance < trigger:
        fail(f"窗口容差只有 {tolerance} 档（订阅 ±{side} − 可视 ±{visible}），"
             f"小于窗口重建触发 {trigger} 档 —— 现价一走就会退订**看得见**的档位，"
             f"热力图会在行权价轴上留下时间空洞（该行不被删掉，只在中间空一截）")
        failures += 1
    else:
        ok(f"窗口容差 {tolerance} 档 ≥ 重建触发 {trigger:g} 档"
           f"（现价在容差带内往返不掉档）")

    # ── 6.4 环形缓冲容量必须覆盖整个网格 ────────────────────────────
    app = loader.load("app")
    session, _ = make_session_clock(app, serial)
    bucket_count = session.bucket_count()
    bucket_s = session.bucket_seconds

    max_buckets = loader.as_int(serial, "heatmap_max_buckets", module="serialization")
    max_points = loader.as_int(serial, "skew_series_max_points", module="serialization")

    for label, value in (("heatmap_max_buckets", max_buckets),
                         ("skew_series_max_points", max_points)):
        if value < bucket_count:
            fail(f"config/serialization.json::{label} = {value} < 网格长度 "
                 f"{bucket_count} 桶 —— 环形缓冲装不下整个交易日，**最早那段会被"
                 f"静默裁掉**，图上表现为『左端凭空少一截』且不报任何错")
            failures += 1
        else:
            ok(f"{label} = {value} ≥ 网格 {bucket_count} 桶"
               f"（{bucket_s}s × {bucket_count} = "
               f"{bucket_count * bucket_s / 3600:.2f} 小时）")

    # ── 6.5 推送不得快于特征计算 ────────────────────────────────────
    compute_ms = loader.as_int(pipeline, "compute_interval_ms", module="pipeline")
    push_ms = loader.as_int(transport, "push_interval_ms", module="transport")
    if compute_ms > push_ms:
        fail(f"compute_interval_ms = {compute_ms} 大于 push_interval_ms = "
             f"{push_ms} —— 推送快于特征计算，会重复广播同一帧，白烧带宽与前端重绘")
        failures += 1
    else:
        ok(f"特征计算 {compute_ms}ms ≤ 推送 {push_ms}ms")

    return failures + _check_model_greeks(ibkr)


def _check_model_greeks(ibkr: dict) -> int:
    """
    ``use_model_greeks`` 必须是 true —— 它是热力图正确性的**前置条件**。

    为什么这是硬约束而不是"性能偏好"
    --------------------------------
    热力图每一行（一个行权价）只保留**一条**序列，键**不带方向**
    （``HeatmapEngine`` 的 ``_buckets[strike][bucket]``）。而现价在动，现价穿越
    某个行权价时，该行的取边会按 ``StrikeWindow`` 从 Call 翻成 Put（或反之）。
    这条合并序列**只在两侧 IV 相等时才连续**。

    实测（SPXW 0DTE，4 档 × 双向，conId 与买卖价均不同）：
    ``modelGreeks`` 口径 Put/Call 差 **0.000**（IBKR 的 model IV 一个行权价只给
    一个值）；关掉后走 last 口径，两侧差 **5.5~6.3 个波动率点**，而色标量程
    只有 ±0.5。

    也就是说：把这里误改成 false，程序**照常启动、照常出图、不报任何错**，只是
    在每次现价穿越行权价时打出一根**随现价漂移的竖直假亮条** —— 典型的静默错值。
    """
    value = ibkr.get("use_model_greeks")
    if value is True:
        ok("use_model_greeks=true（热力图合并序列的前置条件成立）")
        return 0
    if value is False:
        fail("config/ibkr.json::use_model_greeks=false：热力图每档只留一条不带方向"
             "的 IV 序列，现价穿越行权价时取边 Put↔Call 翻转；只有 model 口径两侧"
             "同值（实测差 0.000）才无跳变。关闭后走 last 口径两侧差 5.5~6.3 个"
             "波动率点（色标仅 ±0.5）⇒ 每次穿越打出一根随现价漂移的竖直假亮条，"
             "且不报任何错")
        return 1
    fail(f"config/ibkr.json::use_model_greeks={value!r} 不是布尔值")
    return 1


def check_rate_limit_bucket() -> int:
    """
    [11] 出站限速桶容量。

    为什么是这五条 —— 每条都对应一种"配置写错但程序照跑"的形态：

    1. **容量 ≥ 1**：``0`` 在 ``ib_async`` 里是"关闭限速"的开关值，不是"零容量"。
       写 0 会静默退化成不限速 —— 那不是配置失误，是把保护关掉了。
    2. **窗口 > 0**：``RequestsInterval`` 为 0 时滑动窗口永不淘汰，桶会被一次性
       填满且再也排不空。
    3. **容量 ≤ 官方上限（行数 ÷ 2）**：超了就是拿 Error 100 换性能，而累计 3 次
       违约 IBKR 会直接终止 API 会话（必须重连）。
    4. **容量 ≥ qualify_batch_size**：``qualifyContractsAsync`` 内部是
       ``asyncio.gather`` 的**瞬时并发**，一批就是一个突发。批量大于桶容量，等于
       每次窗口重建都必然触发限速。
    5. **桶速率 ≥ 订阅节奏**：``min_request_interval_s`` 反推的每秒请求数若高于桶
       容量，桶会长期满着，这个节奏配置就是一句空话。
    """
    print(f"\n[11] 出站限速桶容量与 IBKR 配额")

    ibkr = loader.load("ibkr")
    sub = loader.load("subscription")

    capacity = loader.as_int(ibkr, "rate_limit_max_requests", module="ibkr")
    interval = loader.as_float(ibkr, "rate_limit_interval_s", module="ibkr")
    batch = loader.as_int(ibkr, "qualify_batch_size", module="ibkr")
    pace_s = loader.as_float(sub, "min_request_interval_s", module="subscription")

    failures = 0
    official = IBKR_SUBSCRIPTION_LIMIT / IBKR_MESSAGES_PER_LINE

    if capacity < 1:
        fail(f"rate_limit_max_requests={capacity} 无效：0 在 ib_async 里是"
             f"'关闭限速'的开关值，会静默退化成不限速")
        failures += 1
    if interval <= 0:
        fail(f"rate_limit_interval_s={interval} 必须为正：为 0 时滑动窗口永不淘汰，"
             f"桶会被一次填满且再也排不空")
        failures += 1
    if capacity > official:
        fail(f"rate_limit_max_requests={capacity} 超过官方上限 {official:g}"
             f"（行情行数 {IBKR_SUBSCRIPTION_LIMIT} ÷ {IBKR_MESSAGES_PER_LINE}）"
             f"—— 会触发 Error 100，累计 3 次被 IBKR 终止 API 会话")
        failures += 1
    if batch > capacity:
        fail(f"qualify_batch_size={batch} 超过桶容量 {capacity}："
             f"qualifyContractsAsync 是瞬时并发的一批，每次窗口重建都会撑满桶")
        failures += 1
    if pace_s <= 0:
        fail(f"min_request_interval_s={pace_s} 必须为正")
        failures += 1
    elif capacity / interval < 1.0 / pace_s:
        fail(f"订阅节奏 {1.0 / pace_s:.0f} 条/s（min_request_interval_s={pace_s:g}）"
             f"高于桶容量 {capacity / interval:.0f} 条/s —— 桶会长期满着，"
             f"这个节奏配置等于没生效")
        failures += 1

    if not failures:
        ok(f"桶 {capacity} 条 / {interval:g}s = {capacity / interval:.0f} 条/s"
           f"（官方上限 {official:g}；qualify 单批 {batch} 条；"
           f"订阅节奏 {1.0 / pace_s:.0f} 条/s）")
    return failures


def run_invariant_checks() -> int:
    """供 ``--check`` 调用的入口。返回**失败条数**。"""
    return check_subscription_capacity() + check_rate_limit_bucket()


def main() -> int:
    failures = run_invariant_checks()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
