"""
L2 — 采集层。

职责边界
--------
* 与 IBKR 通信、解析 0DTE 合约链、维护动态 ATM 订阅窗口、把原始 tick
  归一化成 L0 契约里的 DTO 并推给 ``TickSink``。
* **不做任何特征计算**（那是 L5 的事），**不持有任何历史状态**（那是 L3 的事）。

只依赖 L0（config / contracts）与 L1（core）。

为什么这里不做 re-export
------------------------
本包中 ``contract_factory`` 与 ``ibkr_gateway`` 会在模块加载时**直接** import
``ib_async``，``feed_service`` 又 import 了这两个 ⇒ 共 3 个模块会（直接或传递地）
拉起 ``ib_async``。如果 ``__init__.py`` 把全部子模块都导出来，那么仅仅 ``import
acquisition`` 就会强制拉起 ``ib_async``——``run.py --check`` 与 ``tools/``
下的离线回归（它们只跑 ``state`` + ``features`` + ``serialization`` +
``transport``，完全不碰行情通道）将无法脱离该依赖。

因此本文件刻意保持为空壳，调用方按需显式 import 具体子模块：

::

    from acquisition.feed_service import IbkrFeed
"""
