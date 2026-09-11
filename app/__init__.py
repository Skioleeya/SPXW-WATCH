"""
L6 — 组装层。

本包只包含一个模块：``pipeline``。它是整个工程的组装根，也是唯一允许
跨层 import 的地方。

把它单独成包的目的，是让"架构违规"这件事变得可检查：只要 grep 一下哪些文件
同时 import 了多个层，就能立刻看出有没有人绕过分层直接接线。
"""

from app.pipeline import PROJECT_ROOT, Pipeline

__all__ = ["PROJECT_ROOT", "Pipeline"]
