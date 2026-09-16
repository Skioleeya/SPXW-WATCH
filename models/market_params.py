"""
models/market_params.py
========================
曲面拟合使用的市场假设：无风险利率 r、股息率 q。

唯一来源是 ``config/surface.json``，经 ``models/surface_params.py`` 读出。
**本模块不含任何默认值** —— 缺键即抛 ``ConfigError``（fail fast）。

与原版的差异
------------
原版从仓库根目录的 ``dashboard_config.json`` 读取，并在下面三种情况下静默退回
写死的 0.04 / 0.00：文件不存在、JSON 解析失败、键缺失。那条路径已经删除。
理由：静默兜底会把"配置写错了"和"配置没写"变成同一件事，而这两件事必须能被
区分 —— 一份用错利率的曲面不会报错，只会安静地把残差算歪。

原版返回值里的第三个键 ``contract_multiplier`` 也已删除：它在整个代码库里
**没有任何消费方**（`grep -rn contract_multiplier` 只有定义处）。契约乘数是
标的定义，唯一来源是 ``config/app.json::option_multiplier``；在这里再放一份
就是第二份真相。

用法
----
::

    from models.market_params import get_market_params

    mkt = get_market_params()
    r = mkt["risk_free_rate"]
    q = mkt["dividend_yield"]
"""

from __future__ import annotations

from models.surface_params import pricing_params


def get_market_params() -> dict:
    """
    返回曲面拟合用的市场假设。

    Returns
    -------
    dict
        ``{"risk_free_rate": float, "dividend_yield": float}``

    Raises
    ------
    config.loader.ConfigError
        ``config/surface.json`` 缺失、格式错误，或缺这两个键之一。
    """
    p = pricing_params()
    return {
        "risk_free_rate": p.risk_free_rate,
        "dividend_yield": p.dividend_yield,
    }
