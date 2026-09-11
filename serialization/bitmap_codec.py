"""
L4 — 稀疏矩阵的「位图 + 定标整数」编解码。
=============================================
唯一职责：把「大部分格子为空」的数值矩阵压成 ``[位图][定标整数数组]``，
以及反向还原。

为什么需要它
------------
热力图矩阵里约 88% 的格子是 ``None``，而 JSON 里每个空格最少要写 5 个字节
（``null,``）。实测单帧 80 KB 里有 **71%** 是这种填充 —— 它比真正的数值大 8 倍。

两条实测结论决定了这里的形状（证据见 ``.workbuddy-ai/memory/2026-09-11.md``）：

* 只靠 ``permessage-deflate`` 能把整帧压到 1/12 —— 它擅长吃重复的 ``null,``，
  但吃不掉「格子本身的数量」。
* 换成位图 + 定标整数后，在 deflate 之上**再省 87%** —— 位图与定标整数叠加
  生效，而不是互相抵消。（曾误以为 deflate 会把二进制的优势抹平，实测证伪。）

线上格式（必须与 ``web/matrix_codec.js`` **逐位一致**）
-------------------------------------------------------
* **位图**：``rows * cols`` 位，行主序；下标 ``i = row * cols + col``，
  对应字节 ``i >> 3`` 的 ``7 - (i & 7)`` 位（MSB-first）。
* **数值**：只存有值的格子，按行主序遍历，**小端 int16**；
  真实值 = 整数 / ``scale``。

为什么 scale 不单设配置键
-------------------------
``scale = 10 ** impulse_decimals``，直接由已有的精度键推导。单设一个键就等于
「精度」有两处真相，改一处忘一处 —— 那正是本项目反复要消除的东西。
``scale`` 会随帧下发，前端不需要自己推导。

为什么超范围要抛异常而不是截断
------------------------------
ΔIV 单位是波动率点，正常在 ±3 以内，int16 配 3 位小数可覆盖 ±32.7。
真超了说明上游有实打实的 bug（毛刺闸门失效 / 单位算错）。静默截断会让
热力图显示一个**不存在的数值**，比直接炸掉更糟 —— 与 ``allow_nan=False``
同一个取舍方向。

依赖：L0（core.errors）。
"""

from __future__ import annotations

import base64
import struct

from core.errors import SerializationError

_BITS_PER_BYTE = 8
_BYTES_PER_I16 = 2


def _pack_i16(ints: list[int]) -> bytes:
    """
    一次打包整个数组；越界立刻抛，不做截断。

    格式串按长度生成（``Struct("<h")`` 只接受单值，装不下整块矩阵）。
    """
    if not ints:
        # 空数组是合法输入（全空的矩阵），但 struct.pack 零参数会抛。
        return b""
    try:
        return struct.pack(f"<{len(ints)}h", *ints)
    except struct.error as exc:
        raise SerializationError(
            f"ΔIV 定标后超出 int16 表示范围（说明上游数值异常，"
            f"不是前端问题）：{exc}"
        ) from exc


def _unpack_i16(raw: bytes) -> tuple[int, ...]:
    if not raw:
        return ()
    if len(raw) % _BYTES_PER_I16:
        raise SerializationError(f"定标整数块长度 {len(raw)} 不是 2 的倍数")
    return struct.unpack(f"<{len(raw) // _BYTES_PER_I16}h", raw)


def pack(
    matrix: list[list[float | None]] | tuple,
    scale: int,
) -> tuple[str, str, int]:
    """
    行主序稀疏矩阵 → ``(位图 base64, 定标整数 base64, 有值格数)``。

    ``scale`` 必须为正整数；``matrix`` 允许为空（返回空位图与空数组）。
    """
    if not isinstance(scale, int) or scale <= 0:
        raise SerializationError(f"scale 必须是正整数，收到 {scale!r}")

    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0

    bits = bytearray((rows * cols + _BITS_PER_BYTE - 1) // _BITS_PER_BYTE)
    ints: list[int] = []

    for r in range(rows):
        row = matrix[r]
        if len(row) != cols:
            raise SerializationError(
                f"矩阵不是矩形：第 {r} 行有 {len(row)} 列，期望 {cols} 列"
            )
        base = r * cols
        for c in range(cols):
            cell = row[c]
            if cell is None:
                continue
            idx = base + c
            bits[idx >> 3] |= 1 << (7 - (idx & 7))
            ints.append(int(round(float(cell) * scale)))

    return (
        base64.b64encode(bytes(bits)).decode("ascii"),
        base64.b64encode(_pack_i16(ints)).decode("ascii"),
        len(ints),
    )


def unpack(
    bm_b64: str,
    i16_b64: str,
    rows: int,
    cols: int,
    scale: int,
) -> list[list[float | None]]:
    """
    反向还原，供探针与回归使用。

    位图里置位数与整数个数不一致时抛异常 —— 那是编码/解码约定分叉的信号，
    必须响，不能悄悄少还原几格。
    """
    bits = base64.b64decode(bm_b64)
    nums = _unpack_i16(base64.b64decode(i16_b64))

    out: list[list[float | None]] = [[None] * cols for _ in range(rows)]
    k = 0
    for idx in range(rows * cols):
        if (bits[idx >> 3] >> (7 - (idx & 7))) & 1:
            if k >= len(nums):
                raise SerializationError(
                    f"位图置位数多于数值个数：第 {k} 个已无对应整数"
                )
            out[idx // cols][idx % cols] = nums[k] / scale
            k += 1

    if k != len(nums):
        raise SerializationError(
            f"数值个数 {len(nums)} 多于位图置位数 {k}，编码约定已分叉"
        )
    return out
