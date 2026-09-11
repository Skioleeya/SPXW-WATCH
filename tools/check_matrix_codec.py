"""
L6 — 数值块编解码回归。
========================
唯一职责：证明 ``serialization/bitmap_codec.py``（打包）与
``web/matrix_codec.js``（解包）对**同一批矩阵**给出逐值一致的结果。

为什么必须有它
--------------
线上数值块从「二维数组 + null 填充」换成了「位图 + 定标整数」，前端要自己解。
这就在两种语言之间引入了一份**新的镜像**：位序（MSB-first 还是 LSB-first）、
字节序（小端还是大端）、遍历顺序（行主序还是列主序）三件事只要有一件对不上，
画面**照样能画出来**，只是数字全错 —— 比白屏危险得多。

所以这里不写"参考实现"，直接拿**原始矩阵当基准**：Python 打包 → JS 解包 →
与原始矩阵逐格比。任何一侧的约定漂移都会立刻红。

顺带钉住的两件事
----------------
* 帧里 ``enc`` 字段的值必须等于 ``config/serialization.json::heatmap_encoding``，
  且 ``web/matrix_codec.js`` 认的就是这个名字。名字分叉 → 前端只会报"未知编码"，
  所以必须在离线就发现。
* ``--selftest`` 往 JS 里注入三种典型缺陷（位序 / 字节序 / 遍历顺序），
  证明这组对照不是空转。

用法::

    python tools/check_matrix_codec.py
    python tools/check_matrix_codec.py --selftest
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))

from config import loader  # noqa: E402
from serialization.bitmap_codec import pack, unpack  # noqa: E402

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"

#: node 侧驱动：装一个最小 window/atob 垫片，求值 matrix_codec.js，逐例解包吐 JSON。
#: ``node -e`` 下 ``process.argv[1]`` 就是脚本后的第一个参数（argv[0] 是 node 本体）。
NODE_DRIVER = r"""
const fs = require("fs");
const codecPath = process.argv[1];
const payloadPath = process.argv[2];

const window = {
  console: console,
  atob: function (b64) {
    return Buffer.from(b64, "base64").toString("binary");
  }
};
eval(fs.readFileSync(codecPath, "utf8"));

const M = window.SWATCH_MATRIX;
const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
const out = { name: M.NAME, results: [] };

for (const c of payload.cases) {
  const block = Object.assign({}, c.block);
  const decoded = M.decode(block);
  out.results.push({ key: c.key, values: decoded.values || null });
}
process.stdout.write(JSON.stringify(out));
"""

SCALE = 1000


def _check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  {GREEN if condition else RED}[{'ok' if condition else 'FAIL'}]{RESET} "
          f"{label}" + (f"  {detail}" if detail else ""))
    return condition


# --------------------------------------------------------------------------- #
# 用例
# --------------------------------------------------------------------------- #

def _grid(rows: int, cols: int, fn) -> list[list[float | None]]:
    return [[fn(r, c) for c in range(cols)] for r in range(rows)]


def cases() -> list[tuple[str, list[list[float | None]]]]:
    """
    刻意覆盖的边界：空矩阵、全空、全满、首末格、负值、int16 两端、
    行列数不是 8 的倍数（位图末尾有填充位，必须为 0）。
    """
    rng = [0.001, -0.002, 3.25, -7.5, 12.125, -32.767, 32.767, 0.0]

    return [
        ("空矩阵", []),
        ("全空 3×4", _grid(3, 4, lambda r, c: None)),
        ("单格 1×1", [[0.125]]),
        ("全满 2×3", _grid(2, 3, lambda r, c: rng[(r * 3 + c) % len(rng)])),
        ("棋盘 5×7", _grid(5, 7, lambda r, c: None if (r + c) % 2 else 0.5 - r * 0.125)),
        ("首末格为空 4×5", _grid(4, 5, lambda r, c: (
            None if (r == 0 and c == 0) or (r == 3 and c == 4) else -1.25 + c * 0.25
        ))),
        ("3×3（位图有填充位）", _grid(3, 3, lambda r, c: (r - c) * 0.75)),
        ("6×125（与周期夹具同形）", _grid(6, 125, lambda r, c: (
            None if c < r * 3 else round((c - r) * 0.037 - 1.0, 3)
        ))),
        ("单列 8×1", _grid(8, 1, lambda r, c: rng[r % len(rng)])),
        ("单行 1×9", _grid(1, 9, lambda r, c: None if c % 3 == 0 else c * 0.111)),
    ]


# --------------------------------------------------------------------------- #
# node 驱动
# --------------------------------------------------------------------------- #

def run_node(codec_path: Path, payload: dict) -> dict:
    """把用例交给 node，取回 matrix_codec.js 的实际解包结果。"""
    with tempfile.TemporaryDirectory(prefix="swatch-codec-") as tmp:
        cases_file = Path(tmp) / "cases.json"
        cases_file.write_text(json.dumps(payload), encoding="utf-8")
        proc = subprocess.run(
            ["node", "-e", NODE_DRIVER, str(codec_path), str(cases_file)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"node 驱动失败: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def build_payload() -> tuple[dict, dict[str, list[list[float | None]]]]:
    """Python 侧打包，产出给 node 的载荷 + 原始矩阵基准。"""
    payload: dict = {"cases": []}
    originals: dict[str, list[list[float | None]]] = {}
    for key, matrix in cases():
        bm, i16, filled = pack(matrix, SCALE)
        rows = len(matrix)
        cols = len(matrix[0]) if rows else 0
        payload["cases"].append({
            "key": key,
            "block": {
                "enc": ENCODING, "scale": SCALE, "bm": bm, "i16": i16,
                "filled": filled, "rows": rows, "cols": cols,
            },
        })
        originals[key] = matrix
    return payload, originals


ENCODING = ""


def _same(got, want) -> bool:
    if got is None or want is None:
        return got is want
    if len(got) != len(want):
        return False
    for gr, wr in zip(got, want):
        if len(gr) != len(wr):
            return False
        for g, w in zip(gr, wr):
            if g is None or w is None:
                if g is not w:
                    return False
            elif abs(float(g) - float(w)) > 1e-9:
                return False
    return True


def _first_diff(got, want) -> str:
    for r, (gr, wr) in enumerate(zip(got or [], want)):
        for c, (g, w) in enumerate(zip(gr, wr)):
            if (g is None) != (w is None) or (
                g is not None and abs(float(g) - float(w)) > 1e-9
            ):
                return f"首处不同 r={r} c={c}: JS={g} PY={w}"
    return "长度不同"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def run(codec_path: Path, verbose: bool) -> int:
    payload, originals = build_payload()
    out = run_node(codec_path, payload)
    passed = True

    passed &= _check("JS 认的编码名与配置一致",
                     out.get("name") == ENCODING,
                     f"js={out.get('name')} cfg={ENCODING}")

    by_key = {r["key"]: r["values"] for r in out["results"]}
    for key, want in originals.items():
        got = by_key.get(key)
        ok = _same(got, want)
        detail = "" if ok else _first_diff(got, want)
        if verbose or not ok:
            passed &= _check(f"逐值一致 · {key}", ok, detail)

    # Python 自己的 unpack 也要过一遍：探针（ws_probe / heatmap_stats）靠它读数，
    # 它若与 JS 分叉，就会出现"探针全绿但前端画错"。
    for key, want in originals.items():
        got = unpack(
            *pack(want, SCALE)[:2],
            rows=len(want), cols=len(want[0]) if want else 0, scale=SCALE,
        )
        if not _same(got, want):
            passed &= _check(f"Python 自洽 · {key}", False, _first_diff(got, want))
    if passed:
        _check("Python 自洽（pack→unpack 还原）", True, f"{len(originals)} 例")

    return 0 if passed else 1


MUTATIONS: tuple[tuple[str, str, str], ...] = (
    ("位序反了（MSB-first → LSB-first）",
     "bits[i >> 3] >> (7 - (i & 7)) & 1",
     "bits[i >> 3] >> (i & 7) & 1"),
    ("字节序反了（小端 → 大端）",
     "view.getInt16(k * 2, true)",
     "view.getInt16(k * 2, false)"),
    ("遍历顺序反了（行主序 → 列主序）",
     "var i = base + c;",
     "var i = c * rows + r;"),
)


def selftest(codec_path: Path) -> int:
    """注入典型缺陷，证明上面的对照真的会红（非空转验证）。"""
    print("\n=== 变异自检：把 JS 改坏，看这组对照抓不抓得住 ===")
    source = codec_path.read_text(encoding="utf-8")
    failures = 0

    with tempfile.TemporaryDirectory(prefix="swatch-codec-mut-") as tmp:
        for name, old, new in MUTATIONS:
            if old not in source:
                print(f"  {RED}[FAIL]{RESET} 变异锚点已失效（源码改了？）：{old}")
                failures += 1
                continue
            broken = Path(tmp) / "broken_codec.js"
            broken.write_text(source.replace(old, new, 1), encoding="utf-8")
            # 内层对照会逐条打印 FAIL，那是**预期**的；静音掉，只留下面一行结论。
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink):
                try:
                    rc = run(broken, verbose=False)
                except RuntimeError:
                    rc = 1
            caught = rc != 0
            print(f"  {GREEN if caught else RED}[{'ok' if caught else 'FAIL'}]{RESET} "
                  f"{name} → {'已抓住' if caught else '**没抓住**'}")
            failures += 0 if caught else 1

    return 0 if failures == 0 else 1


def main() -> int:
    global ENCODING
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="注入缺陷验证对照有效性")
    ap.add_argument("--quiet", action="store_true", help="只打印失败项")
    args = ap.parse_args()

    serial_cfg = loader.load("serialization")
    ENCODING = loader.as_str(serial_cfg, "heatmap_encoding", module="serialization")
    codec_path = WEB / "matrix_codec.js"

    print(f"编码名 {ENCODING}  定标 {SCALE}  "
          f"（定标必须等于 10**impulse_decimals = "
          f"{10 ** loader.as_int(serial_cfg, 'impulse_decimals', module='serialization')}）")

    if args.selftest:
        return selftest(codec_path)

    print("\n=== 逐值对拍：Python 打包 → JS 解包 → 与原始矩阵比 ===")
    return run(codec_path, verbose=not args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
