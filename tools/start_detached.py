"""以**分离进程**方式启动 SPXW SWATCH 服务，脱离当前进程树。

为什么需要它
------------
WorkBuddy 的后台任务约 1 小时会被杀（``RULES.md §7`` 实测 1h0m49s；2026-09-14
12:07→12:42 只跑了 35 分钟）。盯盘服务必须由一个**不属于当前会话**的进程持有，
否则工作台一收尾就把它带走。

本脚本用 Windows 的 ``DETACHED_PROCESS`` + ``CREATE_NEW_PROCESS_GROUP`` 起子进程：
  - ``DETACHED_PROCESS``：新进程没有控制台，不与本会话共享控制台、不受其 Ctrl+C 影响；
  - ``CREATE_NEW_PROCESS_GROUP``：新进程自成进程组，不随父进程组一起收信号；
  - 输出重定向到 ``logs/service_stdout.log``（否则无控制台时子进程写 stdout 会出错）。

启动后本脚本立即退出，``run.py`` 继续在后台运行 —— 这就是"独立启动"。

⚠️ **必须在 WorkBuddy 之外的普通终端里运行**
--------------------------------------------
2026-09-14 实测：**从 AI 的工具调用里启动本脚本，服务会被沙箱回收。**
三种方式（``cmd start``、``subprocess DETACHED_PROCESS``、PowerShell ``Start-Process``）
**无一例外** —— 日志都记到了"流水线已就绪"，但工具调用一返回，进程即被清理，
8060 始终未进入 LISTENING。这是沙箱的**结构性限制**（它按调用回收派生进程），
不是本脚本的缺陷。

∴ **正确用法：由 KAI 在自己的终端里执行本脚本**（或直接跑 ``run.py`` 占着前台）。
本脚本的价值在于"起完就还你终端"，不必占着一个窗口。

用法::

    venv/Scripts/python.exe tools/start_detached.py        # 启动，打印 PID 后返回
    taskkill /PID <pid> /F                                  # 停止

直接前台跑（最省事，能看见实时日志，关窗口即停）::

    venv/Scripts/python.exe run.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROLE = Path(__file__).resolve().parent.parent


def main() -> int:
    venv_py = _ROLE / "venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        print(f"[ERROR] 找不到解释器: {venv_py}")
        print("        运行与回归都必须用带依赖的 venv（RULES.md §6.1）。")
        return 1

    log_dir = _ROLE / "logs"
    log_dir.mkdir(exist_ok=True)
    out_path = log_dir / "service_stdout.log"

    # 子进程无控制台，stdout/stderr 必须重定向到文件，否则写入会失败。
    out = open(out_path, "ab")

    flags = 0
    if sys.platform == "win32":
        # 0x00000008 DETACHED_PROCESS
        # 0x00000200 CREATE_NEW_PROCESS_GROUP
        flags = 0x00000008 | 0x00000200

    proc = subprocess.Popen(
        [str(venv_py), "run.py"],
        cwd=str(_ROLE),
        stdout=out,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )

    print(f"[ok] 已独立启动，PID = {proc.pid}")
    print(f"     解释器: {venv_py}")
    print(f"     工作目录: {_ROLE}")
    print(f"     输出日志: {out_path}")
    print(f"     站点: http://127.0.0.1:8060/")
    print(f"     停止: taskkill /PID {proc.pid} /F")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
