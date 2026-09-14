# Startup — b2b-spot-synthesis

## STARTUP-PROOF

```
$ git log --oneline -1
92a516c docs: 更新 open_tasks + project_state —— 实盘链路验证完成、依赖已装、记录同步

$ git status --short
 M notes/context/handoff.md
 M notes/context/open_tasks.md
?? notes/sessions/2026-09-14/
```

改动前工作区**只有 notes 改动，产品代码改动数 = 0**。上面这四条就是本轮改动的基线。

```
$ netstat -ano | grep -E ":(4002|8060)"
  TCP 0.0.0.0:4002  LISTENING  1044      # IB Gateway 在线
  （8060 无监听 —— 残留进程已于上一会话中断）
```

## 本轮范围

KAI 2026-09-14 拍板 5 项，本轮**全部实现**（详见 `handoff.md`）：

1. `config/spot.json` 新建独立文件
2. 09:25 交班下线 GTH 锚定、切回 SPX 指数
3. `ĉ` 两层闸门
4. 不做 09:30 单点对拍
5. `--check` 的 venv 登记按 `pyvenv.cfg` 识别

## 先验约束（不可违反）

- 文件 < 400 行；单一文件单一职能；禁止硬编码（业务常量进 `config/`）；
  严格分层单向依赖；配置文件之间零引用。
- **fail-closed，不静默降级**：拿不到现货就报错/暂停，绝不回落到旧值。
- **不得硬编码期货到期日**（"第三个周五"是 B1 换月静默错值的同源错误）——
  合约月与到期日必须来自 IBKR。
- 探针落点 `<项目根>/tmp/`（已在 `.gitignore` + `NON_SOURCE_DIRS` 两处登记）。
- 回归必须做过非空转验证（摘掉修复要能报 FAIL）。
