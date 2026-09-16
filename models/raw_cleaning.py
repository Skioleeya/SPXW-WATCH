"""
models/raw_cleaning.py
=======================
RawSurfaceModel 的清洗 / 插值流水线。

从 raw_surface_model.py 原样拆出（拆出原因：单文件 <400 行的机械门禁，
且"清洗流水线"与"模型接口"是两件事）。逻辑、变量名、注释均未改动。

本模块不持有任何模型状态：RawSurfaceModel.fit() 调用 build_clean_surface(app)
拿到 (pivot, clean_df, stats) 后自行保存。
"""

import time

import numpy as np
import pandas as pd

from models.surface_params import cleaning_params


# ─────────────────────────────────────────────────────────────────────────────
# 可调参数
# ─────────────────────────────────────────────────────────────────────────────
# 与原版的**两处差异**（都是为了满足本项目第 3 条「禁止硬编码」）：
#
# 1. 原版把这一组常量写死在本模块顶部（IV 合理性区间、行内离群剔除、中位平滑
#    窗口、报价质量门槛、数据新鲜度），本项目把它们全部搬进
#    ``config/surface.json``，由 ``models/surface_params.py::cleaning_params()``
#    读出。**数值逐字一致。**
# 2. 原版还把"曲面成形门槛"的两个数**写死在函数体里**（``num_expiries < 2`` /
#    ``num_strikes < 8``，L416-L417），这里同样搬进配置（``min_expiries`` /
#    ``min_strikes``）。⚠️ ``min_expiries`` 的**取值**与原版不同：原版 2、本项目 1，
#    因为订阅侧只做 0DTE（单到期日）。理由与实测见 ``config/surface.json`` 的
#    ``_min_expiries_comment``。**除这一个数外，本函数逻辑与原版逐字一致。**
#
# 因此 ``build_clean_surface()`` 比原版多一行 ``p = cleaning_params()``，
# 其余逻辑、变量名、注释一字未动；原版的 ``_max_iv_age()`` 辅助函数已删除，
# 由 ``CleaningParams.max_iv_age()`` 承担（同一个语义，只是参数不再来自全局）。
#
# 3. **新增 ``Right`` 列**（本项目特有，原版没有）。原版 ``id_map`` 是两元组
#    ``(expiry, strike)``，方向在适配层就被丢掉；本项目改为三元组并把方向透传
#    进 ``clean_df``。**这不改变任何拟合数值**：``Right`` 既不参与 IV 过滤、
#    离群剔除、pivot 构造，也不参与平滑 —— 它只是一列随行下行的标记，
#    供 ``svi_reporting.residuals()`` 检出、最终成为 ``SurfaceResidual.right``。
#    理由见 ``contracts/feature.py::SurfaceResidual``：同 strike 的 Put/Call
#    各出一条残差，缺方向则前端无法区分。
# ─────────────────────────────────────────────────────────────────────────────


def build_clean_surface(app):
    """
    Core cleaning and interpolation pipeline.

    This is a direct extraction of the original build_clean_surface()
    function.  Logic is unchanged; variable names are preserved so that
    diffs against the original are easy to read.

    Returns
    -------
    pivot    : pd.DataFrame | None
    clean_df : pd.DataFrame
    stats    : dict
    """
    now = time.time()
    is_delayed = getattr(app, "is_delayed", True)
    p = cleaning_params()
    max_age_allowed = p.max_iv_age(is_delayed)

    raw_rows = []
    ages = []

    raw_count = len(app.iv_dict)

    for rid, point in list(app.iv_dict.items()):
        if rid not in app.id_map:
            continue

        # ⚠️ ``id_map`` 的值是三元组 ``(expiry, strike, right)``（本项目口径；
        # 原版是两元组）。只取前两元做曲面坐标 —— 拟合行为与本改动无关。
        # 第三元是方向，仅用于给 clean_df 打标记，最终到达 SurfaceResidual.right。
        # 用切片解包而不是 ``exp, strike, right = ...``：老实现只给两元时应
        # 得到 right = ""，而不是 ValueError（fail-loud 的位置不在这里）。
        mapped = app.id_map[rid]
        exp, strike = mapped[0], mapped[1]
        right = mapped[2] if len(mapped) > 2 else ""

        if isinstance(point, dict):
            iv         = point.get("iv")
            point_time = point.get("time", now)
            opt_price  = point.get("optPrice")
            und_price  = point.get("undPrice")
            tick_type  = point.get("tickType")
            age        = now - point_time
        else:
            iv        = point
            opt_price = None
            und_price = None
            tick_type = None
            age       = 0.0

        if iv is None:
            continue

        if age > max_age_allowed:
            continue

        quote     = getattr(app, "quote_dict", {}).get(rid, {})
        quote_time = quote.get("quote_time")
        quote_age  = now - quote_time if quote_time is not None else np.nan

        raw_rows.append({
            "Expiry":   exp,
            "Strike":   float(strike),
            "Right":    str(right),
            "IV":       float(iv),
            "Age":      age,
            "OptPrice": opt_price,
            "UndPrice": und_price,
            "TickType": tick_type,
            "Bid":      quote.get("bid"),
            "Ask":      quote.get("ask"),
            "Last":     quote.get("last"),
            "Close":    quote.get("close"),
            "BidSize":  quote.get("bidSize"),
            "AskSize":  quote.get("askSize"),
            "LastSize": quote.get("lastSize"),
            "QuoteAge": quote_age,
        })

        ages.append(age)

    fresh_count = len(raw_rows)

    stats = {
        "raw_count":   raw_count,
        "fresh_count": fresh_count,
        "clean_count": 0,
        "rejected_bad_iv":          0,
        "rejected_outlier":         0,
        "max_age":                  max(ages) if ages else 0.0,
        "num_expiries":             0,
        "num_strikes":              0,
        "surface_ok":               False,
        "max_age_allowed":          max_age_allowed,
        "missing_quote":            0,
        "rejected_missing_quote":   0,
        "rejected_crossed_quote":   0,
        "rejected_low_mid":         0,
        "rejected_wide_quote":      0,
    }

    if fresh_count == 0:
        return None, pd.DataFrame(), stats

    df = pd.DataFrame(raw_rows)

    # ── Numeric coercion ──────────────────────────────────────────────
    for col in ["Bid", "Ask", "Last", "Close",
                "BidSize", "AskSize", "LastSize", "QuoteAge"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── IV sanity filter ──────────────────────────────────────────────
    before_bad_iv = len(df)
    df = df[
        (df["IV"] >= p.min_valid_iv) &
        (df["IV"] <= p.max_valid_iv)
    ].copy()
    stats["rejected_bad_iv"] = before_bad_iv - len(df)

    if df.empty:
        return None, df, stats

    # ── Quote-quality filters ─────────────────────────────────────────
    has_quote = df["Bid"].notna() & df["Ask"].notna()
    stats["missing_quote"] = int((~has_quote).sum())

    if p.require_bid_ask_for_filter:
        before = len(df)
        df = df[has_quote].copy()
        stats["rejected_missing_quote"] = before - len(df)

    if df.empty:
        return None, df, stats

    has_quote = df["Bid"].notna() & df["Ask"].notna()

    crossed_or_bad = has_quote & (
        (df["Bid"] <= 0) |
        (df["Ask"] <= 0) |
        (df["Ask"] < df["Bid"])
    )
    stats["rejected_crossed_quote"] = int(crossed_or_bad.sum())
    df = df[~crossed_or_bad].copy()

    if df.empty:
        return None, df, stats

    has_quote = df["Bid"].notna() & df["Ask"].notna()

    df["Mid"]       = (df["Bid"] + df["Ask"]) / 2.0
    df["Spread"]    = df["Ask"] - df["Bid"]
    df["SpreadPct"] = df["Spread"] / df["Mid"]

    low_mid    = has_quote & (df["Mid"] < p.min_option_mid)
    wide_quote = has_quote & (
        (df["SpreadPct"] > p.max_option_spread_pct) |
        (df["Spread"]    > p.max_option_spread_abs)
    )

    stats["rejected_low_mid"]    = int(low_mid.sum())
    stats["rejected_wide_quote"] = int(wide_quote.sum())
    df = df[~(low_mid | wide_quote)].copy()

    if df.empty:
        return None, df, stats

    # ── Local outlier filter (within each expiry) ─────────────────────
    df = df.sort_values(["Expiry", "Strike"])

    df["local_median"] = (
        df.groupby("Expiry")["IV"]
        .transform(
            lambda x: x.rolling(
                window=p.outlier_rolling_window,
                center=True,
                min_periods=2,
            ).median()
        )
    )

    before_outlier = len(df)
    df = df[
        df["local_median"].isna() |
        df["IV"].between(
            df["local_median"] * p.outlier_low_mult,
            df["local_median"] * p.outlier_high_mult,
        )
    ].copy()
    stats["rejected_outlier"] = before_outlier - len(df)

    df = df.drop(columns=["local_median"], errors="ignore")

    # ── Minimum data check ────────────────────────────────────────────
    stats["clean_count"]  = len(df)
    stats["num_expiries"] = df["Expiry"].nunique()
    stats["num_strikes"]  = df["Strike"].nunique()

    if (
        stats["clean_count"]  < p.min_points_to_plot or
        stats["num_expiries"] < p.min_expiries or
        stats["num_strikes"]  < p.min_strikes
    ):
        return None, df, stats

    # ── Pivot + interpolation ─────────────────────────────────────────
    pivot = (
        df.pivot_table(index="Expiry", columns="Strike", values="IV")
        .sort_index()
        .sort_index(axis=1)
    )

    # Fill gaps: across strikes first, then across expiries.
    pivot = pivot.interpolate(method="linear", axis=1).bfill(axis=1).ffill(axis=1)
    pivot = pivot.interpolate(method="linear", axis=0).bfill().ffill()

    # Smooth display surface.
    pivot = pivot.T.rolling(
        window=p.smoothing_window, center=True, min_periods=1
    ).median().T

    pivot = pivot.rolling(
        window=p.smoothing_window, center=True, min_periods=1
    ).median()

    stats["surface_ok"] = True

    return pivot, df, stats
