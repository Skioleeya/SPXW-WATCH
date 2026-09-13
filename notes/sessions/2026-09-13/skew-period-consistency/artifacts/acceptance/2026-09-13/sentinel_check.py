"""离线验证 check_page_render 的页面哨兵判据（工程外临时脚本）。

本环境下 Chrome 连不到本地监听（拿到的是 Chrome 自己的网络错误页），所以正向
用例没法用浏览器跑。改成直接把 DOM 文本喂给判据：
  · 真实 web/index.html          → 必须返回空列表（哨兵齐备）
  · Chrome 的网络错误页（已抓到） → 必须返回非空列表
"""
import sys
from pathlib import Path

ROOT = Path("E:/US.market/SPXW SWATCH/spxw_swatch")
sys.path.insert(0, str(ROOT))
from tools.check_page_render import missing_sentinels, SENTINELS

real = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
err = Path("C:/Users/Lenovo/.workbuddy-ai/tmp/d.html").read_text(encoding="utf-8")

print("哨兵:", SENTINELS)
print()
m_real = missing_sentinels(real)
print(f"真实 index.html      ({len(real):>7} 字符) → 缺失 {m_real}  "
      f"{'PASS' if not m_real else 'FAIL'}")
m_err = missing_sentinels(err)
print(f"Chrome 网络错误页    ({len(err):>7} 字符) → 缺失 {len(m_err)}/{len(SENTINELS)} 个  "
      f"{'PASS' if m_err else 'FAIL（错误页竟然被判成本项目页面）'}")

ok = (not m_real) and bool(m_err)
print()
print("判据非空转:", "PASS —— 真页面通过、错误页被拦下" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
