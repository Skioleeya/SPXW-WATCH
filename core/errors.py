"""
L0 — 异常分类。
================
本模块不 import 项目内任何其他模块（``config/loader.py`` 自带 ``ConfigError``，
此处不再重复定义，避免 L0 内部互相引用）。

分层约定：每层只抛自己这一层的异常，上层负责翻译成自己的语义。
"""

from __future__ import annotations


class SwatchError(Exception):
    """本系统所有自定义异常的根。"""


# --------------------------------------------------------------------------- #
# L1 采集层
# --------------------------------------------------------------------------- #

class AcquisitionError(SwatchError):
    """采集层基类异常。"""


class ConnectionFailed(AcquisitionError):
    """无法与 TWS / IB Gateway 建立可用会话。"""


class ContractResolveError(AcquisitionError):
    """标的或期权合约无法解析（conId 缺失、合约不合格等）。"""


class ChainResolveError(AcquisitionError):
    """期权链参数缺失，或找不到当日到期的 0DTE 切片。"""


class SpotUnavailableError(AcquisitionError):
    """在超时窗口内没有拿到标的现价。"""


class SubscriptionLimitExceeded(AcquisitionError):
    """目标订阅数超过 IBKR 100 条硬上限，已触发自我保护。"""


class SubscriptionThrottled(AcquisitionError):
    """被 IBKR Error 300（行情行数超限）限流，处于退避状态。"""


# --------------------------------------------------------------------------- #
# L2 状态层
# --------------------------------------------------------------------------- #

class StateError(SwatchError):
    """状态层基类异常。"""


class StoreNotReady(StateError):
    """请求的数据分片尚不存在或已被裁剪。"""


# --------------------------------------------------------------------------- #
# L3 特征层
# --------------------------------------------------------------------------- #

class FeatureError(SwatchError):
    """特征层基类异常。"""


class InsufficientHistory(FeatureError):
    """历史样本不足以计算动能（回看窗口内没有基准点）。"""


class SkewUndefined(FeatureError):
    """无法在容差内定位到目标 Delta，Skew 本次不可用。"""


# --------------------------------------------------------------------------- #
# L4 / L5
# --------------------------------------------------------------------------- #

class SerializationError(SwatchError):
    """组装推送帧失败。"""


class TransportError(SwatchError):
    """传输层基类异常。"""
