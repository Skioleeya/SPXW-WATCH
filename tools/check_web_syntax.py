"""
L6 — 前端脚本语法门禁。
=======================
唯一职责：``web/*.js`` 每一个文件都必须能被 JS 解析器读通。

为什么需要它
------------
2026-09-13 的一次改动把 ``web/skew.js`` 的模块 docstring 拆成了两段，中间多留了
一个 ``*/`` —— 块注释在第 25 行提前闭合，紧随其后的说明文字 ``* 为什么不用
visualMap…`` 掉到了注释外面，整个文件成了语法错误。后果不是"少一行注释"，而是
``window.SkewPanel`` 根本不存在，**Skew 面板整块空白**。

而当时 ``tools/`` 里 13 个回归全绿：``check_period_aggregation.py`` 只加载
``period.js``，``check_matrix_codec.py`` 只加载 ``matrix_codec.js``，
``check_web_contract.py`` 只加载 ``config.js`` —— ``skew.js`` / ``heatmap.js`` /
``app.js`` / ``ws_client.js`` **没有任何检查器加载过**。这正是本项目最怕的
"探针全绿但实际是坏的"：不是断言写错了，是根本没人在看这几个文件。

本门禁把"至少能被解析"这一最低要求覆盖到 ``web/`` 全目录，且**新增文件自动纳入**
（按目录枚举，不写死名单 —— 名单漏一个就等于漏一个盲区）。

与行为回归的分工
----------------
本文件只管"能不能解析"。``SkewPanel`` 能不能真的画出来、列网格对不对齐，由
``tools/check_skew_alignment.py`` 覆盖（它会真的加载 ``skew.js`` 并构造面板）。

非空转验证（``--selftest``）
---------------------------
往每个文件的块注释开头**插入一个多余的 ``*/``**（正是上面那次事故的形态），
要求检查器逐个报出来。

用法::

    python tools/check_web_syntax.py
    python tools/check_web_syntax.py --selftest
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def _node_available() -> str | None:
    """返回 node 可执行名；不可用则返回 None（缺失时给出明确提示而非静默跳过）。"""
    try:
        proc = subprocess.run(["node", "--version"], capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return "node" if proc.returncode == 0 else None


def check_file(path: Path, node: str) -> tuple[bool, str]:
    """对单个文件跑 ``node --check``。返回 (是否通过, 详情)。"""
    proc = subprocess.run([node, "--check", str(path)],
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=60)
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, " / ".join(line.strip() for line in detail[:3])


def targets() -> list[Path]:
    """按目录枚举，不写死名单 —— 新增的前端文件自动纳入门禁。"""
    return sorted(WEB.glob("*.js"))


def _report(title: str, rows: list[tuple[str, bool, str]]) -> int:
    print(f"\n{title}")
    failures = 0
    for label, ok, detail in rows:
        if not ok:
            failures += 1
        print(f"  {GREEN if ok else RED}[{'ok' if ok else 'FAIL'}]{RESET} {label}"
              + (f"  {detail}" if detail else ""))
    return failures


# --------------------------------------------------------------------------- #
# 非空转自检
# --------------------------------------------------------------------------- #

def _break_comment(text: str) -> str | None:
    """
    复刻那次事故：在第一个块注释开始后的第一个换行处插入一个多余的 ``*/``，
    使注释提前闭合，后面的说明文字变成代码。返回 None 表示该文件没有块注释。
    """
    start = text.find("/*")
    if start < 0:
        return None
    nl = text.find("\n", start)
    if nl < 0:
        return None
    return text[:nl + 1] + "*/\n" + text[nl + 1:]


def _selftest(node: str) -> int:
    print("\n[非空转自检] 往每个前端文件注入「提前闭合块注释」缺陷，必须逐个抓住")
    failures = 0
    files = targets()

    with tempfile.TemporaryDirectory(prefix="swatch-js-syntax-") as tmp:
        tmpdir = Path(tmp)
        for path in files:
            broken = _break_comment(path.read_text("utf-8"))
            if broken is None:
                print(f"  {RED}[FAIL]{RESET} {path.name} → 没有块注释，"
                      "无法构造该变异（请更新 _break_comment）")
                failures += 1
                continue

            mutant = tmpdir / path.name
            mutant.write_text(broken, encoding="utf-8")
            ok, _ = check_file(mutant, node)
            if ok:
                print(f"  {RED}[FAIL]{RESET} {path.name} → **未被抓住**："
                      "注入提前闭合的块注释后仍然解析通过，这门禁是空转的")
                failures += 1
            else:
                print(f"  {GREEN}[ok]{RESET} {path.name} → 已抓住")
    return failures


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_web_syntax.py")
    parser.add_argument("--selftest", action="store_true",
                        help="额外验证检查器本身不是空转")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("前端脚本语法门禁（web/*.js）")
    print("=" * 72)

    node = _node_available()
    if node is None:
        print(f"{RED}找不到可用的 node，无法检查语法{RESET}"
              "  —— 这是失败而不是跳过：门禁跑不起来就等于没有门禁")
        return 1

    files = targets()
    if not files:
        print(f"{RED}{WEB} 下没有任何 .js 文件{RESET}"
              "  —— 目录枚举为空说明路径不对，不能让空集合冒充通过")
        return 1

    rows = []
    for path in files:
        ok, detail = check_file(path, node)
        rows.append((f"{path.name} 可被 JS 解析器读通", ok, detail))

    failures = _report("[1] web/*.js 语法", rows)

    if args.selftest:
        failures += _selftest(node)

    print()
    print("=" * 72)
    print(f"{GREEN}结果: 全部通过（{len(files)} 个文件）{RESET}" if not failures
          else f"{RED}结果: {failures} 项失败{RESET}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
