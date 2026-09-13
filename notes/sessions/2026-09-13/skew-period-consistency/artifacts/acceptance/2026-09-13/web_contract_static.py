"""离线跑 check_web_contract.py 的第 1、2 段（DOM id / CFG 路径）。
顶层 import aiohttp 挡住了模块导入，这里用桩模块绕过 —— 第 1、2 段本身
不需要 aiohttp，它们只读 web/ 下的静态文件。"""
import sys, types
from pathlib import Path

ROOT = Path("E:/US.market/SPXW SWATCH/spxw_swatch")
sys.path.insert(0, str(ROOT))

stub = types.ModuleType("aiohttp")
stub.ClientSession = object
stub.ClientTimeout = object
sys.modules["aiohttp"] = stub

from tools import check_web_contract as C

print("=" * 72)
print("check_web_contract.py 第 1、2 段（静态对照，离线）")
print("=" * 72)
ok1 = C.check_dom_ids()
print()
ok2 = C.check_cfg_paths()
print()
print("DOM id:", "PASS" if ok1 else "FAIL", "| CFG 路径:", "PASS" if ok2 else "FAIL")
raise SystemExit(0 if (ok1 and ok2) else 1)
