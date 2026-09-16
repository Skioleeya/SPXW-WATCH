"""
L6 — 数值格式化工具。
=====================
唯一职责：把内部计算值整理成适合上行的 JSON 数值。

为什么单独一个文件
------------------
"保留几位小数"和"色标上限怎么取"属于**呈现决策**，不应该散落在各个编码器里
各写一遍，否则改一次精度要翻五个文件。集中在这里，L6 其余模块只调用不定义。

依赖：无（纯函数）。
"""

from __future__ import annotations

import math
from typing import Iterable


def _finite(value: float) -> float | None:
    """非有限值（NaN / inf）一律视为缺失。"""
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def round_opt(value: float | None, ndigits: int) -> float | None:
    """可选数值的四舍五入；``None`` 与非有限值原样透传为 ``None``。"""
    if value is None:
        return None
    number = _finite(value)
    if number is None:
        return None
    return round(number, ndigits)


def round_req(value: float, ndigits: int) -> float | None:
    """必填数值的四舍五入；传入非有限值时返回 ``None`` 而不是写出 NaN。"""
    number = _finite(value)
    if number is None:
        return None
    return round(number, ndigits)


def robust_bound(
    values: Iterable[float | None],
    quantile: float,
    floor: float,
) -> float:
    """
    取一个鲁棒的正数上界，用于前端色标的对称量程。

    为什么不用最大值：0DTE 尾盘只要有一个毛刺点就能把最大值顶到几十个波动率点，
    色标被拉满之后整张热力图会变成一片灰。改用分位数后，少数极端值会被截断在
    色标之外，主图对比度得以保留。

    两个参数都**不设默认值**：它们是呈现决策，必须由配置显式给出。留默认值会
    让"忘了配"变成静默使用一个谁也不记得的常数。

    Parameters
    ----------
    values
        待统计的数值，``None`` 会被忽略。
    quantile
        分位点，``0.95`` 表示取 95 分位。
    floor
        下界保护，避免行情极度平静时色标收缩到 0 导致除零。
    """
    clean = sorted(abs(float(v)) for v in values if v is not None)
    if not clean:
        return floor

    if quantile <= 0.0:
        picked = clean[0]
    elif quantile >= 1.0:
        picked = clean[-1]
    else:
        position = quantile * (len(clean) - 1)
        lower = int(position)
        upper = min(lower + 1, len(clean) - 1)
        weight = position - lower
        picked = clean[lower] * (1.0 - weight) + clean[upper] * weight

    return max(picked, floor)
