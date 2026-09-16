"""
models/surface_params.py
=========================
把 ``config/surface.json`` 翻译成模型层参数对象（L4 唯一读该文件的地方）。

为什么要有这一层
----------------
原版把标定参数写死在 ``models/*.py`` 的模块顶。本项目第 3 条要求业务常量进
配置、且**加载器不含业务默认值**（缺键即抛错）。但如果直接在 6 个模型文件里
散着写 ``loader.as_float(cfg, "svi_max_iter", module="surface")``，会有两个问题：

1. 键名散落各处，改一个配置要 grep 整个目录；
2. 参数在函数体里逐个取，读代码时看不出"一次拟合到底依赖哪些旋钮"。

所以集中到这里：**一个文件 = 一张参数表**。每个 dataclass 的字段名就是
``config/surface.json`` 的键名（同名 snake_case），字段就是该层能调的旋钮全集。

模型文件只 import 一个 ``xxx_params()`` 函数，不 import ``config``。

不缓存
------
``config.loader`` 自己缓存 JSON，这里每次调用只重建一个十几字段的 frozen
dataclass（微秒级）。再加一层缓存等于制造第二份真相，还会让"改了配置要重启"
从 loader 的语义扩散到本模块。调用频次（每次拟合 1~3 次）不值得为此引入缓存。

顺序敏感键
----------
``svi_bounds`` / ``svi_random_start_ranges`` 都是 5 元组，顺序固定为
``(a, b, rho, m, sigma)``。顺序写错**不会报错**，只会拟合出垃圾 —— 所以这里
按元数（arity）做 fail-fast 校验，并把列名常量放在本模块里当唯一说明。
"""

from __future__ import annotations

from dataclasses import dataclass

from config import loader

_MODULE = "surface"

# SVI 参数向量顺序。config/surface.json 的 bounds / random_start_ranges 必须
# 与它一一对应；改这里的顺序等于改线下的标定语义。
SVI_PARAM_ORDER: tuple[str, ...] = ("a", "b", "rho", "m", "sigma")


# --------------------------------------------------------------------------- #
# 清洗参数（原版 models/raw_cleaning.py 顶部常量）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CleaningParams:
    """曲面清洗流水线的旋钮。"""

    min_valid_iv: float
    max_valid_iv: float
    outlier_rolling_window: int
    outlier_low_mult: float
    outlier_high_mult: float
    smoothing_window: int
    min_points_to_plot: int
    min_expiries: int
    min_strikes: int
    require_bid_ask_for_filter: bool
    min_option_mid: float
    max_option_spread_pct: float
    max_option_spread_abs: float
    live_max_iv_age_s: float
    delayed_max_iv_age_s: float

    def max_iv_age(self, is_delayed: bool) -> float:
        """延迟行情下放宽新鲜度门槛（原版 ``_max_iv_age`` 的语义）。"""
        return self.delayed_max_iv_age_s if is_delayed else self.live_max_iv_age_s


def cleaning_params() -> CleaningParams:
    """读取 ``config/surface.json`` 的清洗参数。缺键抛 ``ConfigError``。"""
    cfg = loader.load(_MODULE)
    return CleaningParams(
        min_valid_iv=loader.as_float(cfg, "min_valid_iv", module=_MODULE),
        max_valid_iv=loader.as_float(cfg, "max_valid_iv", module=_MODULE),
        outlier_rolling_window=loader.as_int(cfg, "outlier_rolling_window", module=_MODULE),
        outlier_low_mult=loader.as_float(cfg, "outlier_low_mult", module=_MODULE),
        outlier_high_mult=loader.as_float(cfg, "outlier_high_mult", module=_MODULE),
        smoothing_window=loader.as_int(cfg, "smoothing_window", module=_MODULE),
        min_points_to_plot=loader.as_int(cfg, "min_points_to_plot", module=_MODULE),
        min_expiries=loader.as_int(cfg, "min_expiries", module=_MODULE),
        min_strikes=loader.as_int(cfg, "min_strikes", module=_MODULE),
        require_bid_ask_for_filter=loader.as_bool(
            cfg, "require_bid_ask_for_filter", module=_MODULE
        ),
        min_option_mid=loader.as_float(cfg, "min_option_mid", module=_MODULE),
        max_option_spread_pct=loader.as_float(cfg, "max_option_spread_pct", module=_MODULE),
        max_option_spread_abs=loader.as_float(cfg, "max_option_spread_abs", module=_MODULE),
        live_max_iv_age_s=loader.as_float(cfg, "live_max_iv_age_s", module=_MODULE),
        delayed_max_iv_age_s=loader.as_float(cfg, "delayed_max_iv_age_s", module=_MODULE),
    )


# --------------------------------------------------------------------------- #
# SVI 标定参数（原版 models/svi_fit.py + models/svi_math.py 常量）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SviFitParams:
    """逐到期日 SVI 标定的旋钮。"""

    min_points_per_slice: int
    min_iv: float
    max_iv: float
    opt_tol: float
    max_iter: int
    good_rmse_vol_points: float
    warn_rmse_vol_points: float
    allowed_statuses: frozenset[str]
    n_multistart: int
    random_seed: int
    bounds: tuple[tuple[float, float], ...]
    random_start_ranges: tuple[tuple[float, float], ...]


def svi_fit_params() -> SviFitParams:
    """读取 ``config/surface.json`` 的 SVI 标定参数。缺键抛 ``ConfigError``。"""
    cfg = loader.load(_MODULE)
    return SviFitParams(
        min_points_per_slice=loader.as_int(cfg, "svi_min_points_per_slice", module=_MODULE),
        min_iv=loader.as_float(cfg, "svi_min_iv", module=_MODULE),
        max_iv=loader.as_float(cfg, "svi_max_iv", module=_MODULE),
        opt_tol=loader.as_float(cfg, "svi_opt_tol", module=_MODULE),
        max_iter=loader.as_int(cfg, "svi_max_iter", module=_MODULE),
        good_rmse_vol_points=loader.as_float(cfg, "svi_good_rmse_vol_points", module=_MODULE),
        warn_rmse_vol_points=loader.as_float(cfg, "svi_warn_rmse_vol_points", module=_MODULE),
        allowed_statuses=frozenset(
            loader.as_str_list(cfg, "svi_allowed_statuses", module=_MODULE)
        ),
        n_multistart=loader.as_int(cfg, "svi_n_multistart", module=_MODULE),
        random_seed=loader.as_int(cfg, "svi_random_seed", module=_MODULE),
        bounds=_param_pairs(cfg, "svi_bounds"),
        random_start_ranges=_param_pairs(cfg, "svi_random_start_ranges"),
    )


# --------------------------------------------------------------------------- #
# SSVI 全局标定参数（原版 models/ssvi_math.py 常量）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SsviFitParams:
    """跨到期日 SSVI 全局标定的旋钮。"""

    n_starts: int
    good_rmse_vol_points: float
    warn_rmse_vol_points: float
    min_points: int
    min_expiries: int
    random_seed: int
    data_start: tuple[float, float]
    random_start_ranges: tuple[tuple[float, float], ...]


def ssvi_fit_params() -> SsviFitParams:
    """读取 ``config/surface.json`` 的 SSVI 标定参数。缺键抛 ``ConfigError``。"""
    cfg = loader.load(_MODULE)
    return SsviFitParams(
        n_starts=loader.as_int(cfg, "ssvi_n_starts", module=_MODULE),
        good_rmse_vol_points=loader.as_float(
            cfg, "ssvi_good_rmse_vol_points", module=_MODULE
        ),
        warn_rmse_vol_points=loader.as_float(
            cfg, "ssvi_warn_rmse_vol_points", module=_MODULE
        ),
        min_points=loader.as_int(cfg, "ssvi_min_points", module=_MODULE),
        min_expiries=loader.as_int(cfg, "ssvi_min_expiries", module=_MODULE),
        random_seed=loader.as_int(cfg, "ssvi_random_seed", module=_MODULE),
        data_start=_param_pair(cfg, "ssvi_data_start"),
        random_start_ranges=_param_pairs(cfg, "ssvi_random_start_ranges", expected=2),
    )


# --------------------------------------------------------------------------- #
# 定价假设
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PricingParams:
    """远期价计算用的市场假设。"""

    risk_free_rate: float
    dividend_yield: float


def pricing_params() -> PricingParams:
    """读取 ``config/surface.json`` 的定价假设。缺键抛 ``ConfigError``。"""
    cfg = loader.load(_MODULE)
    return PricingParams(
        risk_free_rate=loader.as_float(cfg, "risk_free_rate", module=_MODULE),
        dividend_yield=loader.as_float(cfg, "dividend_yield", module=_MODULE),
    )


def active_model_name() -> str:
    """返回配置里选中的曲面模型名（**不校验**，校验归 ``contracts.enums``）。"""
    cfg = loader.load(_MODULE)
    return loader.as_str(cfg, "active_model", module=_MODULE)


# --------------------------------------------------------------------------- #
# 内部：参数区间校验
# --------------------------------------------------------------------------- #


def _param_pairs(
    cfg: dict, key: str, *, expected: int = len(SVI_PARAM_ORDER)
) -> tuple[tuple[float, float], ...]:
    """
    把 ``[[lo, hi], ...]`` 读成元组，并校验组数。

    组数写错不会让拟合报错（只会静默产出垃圾），所以这里必须 fail fast。
    ``expected`` 默认按 SVI 参数向量（a, b, rho, m, sigma）算，SSVI 的
    ``(rho, eta)`` 区间传 2。
    """
    raw = loader.get(cfg, key, module=_MODULE)

    if not isinstance(raw, (list, tuple)):
        raise loader.ConfigError(
            f"config/{_MODULE}.json::{key} 必须是二维数组，收到 {type(raw).__name__}"
        )

    if len(raw) != expected:
        raise loader.ConfigError(
            f"config/{_MODULE}.json::{key} 必须有 {expected} 组，收到 {len(raw)} 组"
        )

    return tuple(_param_pair_value(pair, f"{key}[{i}]") for i, pair in enumerate(raw))


def _param_pair(cfg: dict, key: str) -> tuple[float, float]:
    """把 ``[lo, hi]`` 读成一个区间元组（单起点用）。"""
    return _param_pair_value(loader.get(cfg, key, module=_MODULE), key)


def _param_pair_value(pair: object, label: str) -> tuple[float, float]:
    """校验并转换一个 ``[下界, 上界]``。"""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise loader.ConfigError(
            f"config/{_MODULE}.json::{label} 必须是 [下界, 上界]，收到 {pair!r}"
        )
    lo, hi = float(pair[0]), float(pair[1])
    if lo > hi:
        raise loader.ConfigError(
            f"config/{_MODULE}.json::{label} 下界 {lo} 大于上界 {hi}"
        )
    return (lo, hi)
