# Project State — live-verify-and-release

本文件只写**判断与理由**。改了什么、命令证据在 `handoff.md`。

## 1. 为什么"周日跑不起来"不算失败，却必须记成风险

两种解读都成立，但只有一种是对的：

- ❌ "实盘路径验证通过" —— **假绿**。链路只走到第 3 步，出图、订阅、限速桶读数
  一个都没看到。
- ❌ "实盘路径坏了" —— **假红**。`ChainResolveError` 是设计要求的 fail-closed，
  不是回归。

正确结论是**第三条**：硬切改动的代码路径（`run.py` → `Pipeline()` 无参 →
`IbkrFeed.start()` → connect/qualify/拉链）**已被覆盖**，因为这几步真跑过了；
而**数据面**（订阅 + 帧）零覆盖，因为今天没有 0DTE 合约可订。

判据是：日志停在 `pick_zero_dte`，**它前面的每一步都成功了** ——
包括从 IBKR 真拿到 SPXW 到期列表。若连不上或权限有问题，错误会出现在更早的位置。

## 2. 硬切的一个真实代价：非交易日起不了服务

删掉模拟盘之前，`--sim` 让服务在任何时段都能起，4 个需服务的检查随时可跑。
删掉之后：

| 时段 | 服务能否常驻 | 4 个需服务检查 |
|---|---|---|
| 交易日盘中 | ✅ | ✅ |
| 交易日盘前/盘后 | ❌（无当日到期） | ❌ |
| 周末 | ❌ | ❌ |

**这是取舍的必然结果，不是缺陷** —— KAI 要的就是"没有降级路径"。
但它改变了回归的**可执行窗口**：这 4 项从此只能在盘中跑。

值得记下来的原因：它会让"回归全绿"这个说法在非交易时段**永远无法成立**。
不写清楚，下次有人在周日跑回归、看到 4 项红，会误判成回归破坏。

**备选（未采纳）**：给 `--check` 增加一个"无 0DTE 时用最近到期日跑只读自检"的模式。
不采纳 —— 那是把模拟盘的思路换个名字请回来，与硬切矛盾。宁可接受窗口限制。

## 3. `git fetch` 不落地 remote-tracking ref（**未定位**）

观察到的**事实**（全部可复现）：

| 操作 | 结果 |
|---|---|
| `git push origin main` | ✅ 成功，`ls-remote` 核实远端 = 本地 HEAD |
| `git fetch origin` | 退出码 0，输出 `* [new branch] main -> origin/main` |
| fetch 之后 `refs/remotes/origin/main` | ❌ 不存在（`show-ref` 只有 `refs/heads/main`） |
| `.git/logs/refs/remotes/origin/main` | ✅ **存在**（fetch 确实写了 reflog） |
| `git update-ref refs/remotes/origin/main HEAD` | 退出码 0，但 ref 不存在 |
| 手动 `mkdir -p .git/refs/remotes/origin` + 直接写文件 | ✅ 成功，`rev-parse` 能解析 |
| 手动建的 ref 再跑一次 `git fetch` | ❌ 被删掉 |
| 对照：`refs/tags/__probe`、`refs/zz_probe` 写入 | ✅ 都成功 |
| 对照：另一个仓库 `live-volatility-surface` | ✅ `refs/remotes/origin/main` 正常（存于 packed-refs） |

配置侧已排除：`.git/config` 正常，`remote.origin.fetch = +refs/heads/*:refs/remotes/origin/*`，
**全环境无任何 `prune` 配置**（`git config --list --show-origin` 只有 2 条 remote 项）。

**结论：根因未定位。** 不声称是沙箱、杀软或 git 版本 —— 没有证据。
`git fetch` 写了 reflog 却不留 ref，且只对 `refs/remotes/**` 如此，与 git 的正常
语义不符。

**影响**：仅 `git status -sb` 显示 `[gone]`，**不影响提交、推送与远端状态**。
**推断（未验证）**：在 KAI 自己的终端里可能不复现 —— 这需要他在本地试一次才能确认。

## 4. 踩到的坑

- **`git status -sb` 的 `[gone]` 不能当成"推送失败"。** 正确判据是
  `git ls-remote origin refs/heads/main` 与本地 HEAD 比对 —— 本次两者一致。
  只看状态行会得出相反结论。
- **提交前必须扫敏感串。** `notes/` 里有 11 个探针文件，命中 `clientId=97/98/99`
  这类字样；不逐个判读就会误判成凭据，或者反过来漏掉真凭据。
- **`notes/` 的重新入库是一次"有意反转"。** `2447d53` 的提交信息明确写了
  "Remove notes/ directory"；本次复活即反转它。**不写明就会被当成误操作。**
